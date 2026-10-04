"""Field boundary lifecycle and prescription creation rules."""

import pytest

from test_helpers import (
    ApiErrorId,
    add_active_field,
    add_machine,
    create_field,
    create_prescription,
    create_prescription_payload,
    prescription_zone,
    read_field,
    setup_org_dealer,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_prescription_create_on_draft_field_rejected(api):
    """PRD section 3.3: "only `ACTIVE` fields accept new prescriptions" and
    "the field must be `ACTIVE`, or the create fails with
    `ERR_FIELD_NOT_ACTIVE`". A `DRAFT` field exists, so this is a state
    failure, not a 404, and the field's version is untouched.

    Design: Corner/entities/prescription_create_on_draft_field_rejected
    """
    ctx = setup_org_dealer(api)
    machine = add_machine(ctx, api)
    field = create_field(ctx, api)
    payload = create_prescription_payload(
        ctx["org"]["id"], field["id"], machine["id"], field["version"]
    )
    response = api.create_prescription(payload, headers=ctx["grower_headers"])
    validate_error(response, ApiErrorId.ERR_FIELD_NOT_ACTIVE)

    field = read_field(ctx, api, field["id"])
    assert field["version"] == 1
    assert field["status"] == "DRAFT"
    rows, _meta = validate_paginated(
        api.list_prescriptions(
            headers=ctx["grower_headers"], params={"field_boundary_id": field["id"]}
        )
    )
    assert len(rows) == 0


def test_field_archive_with_open_prescription_rejected(api):
    """PRD section 3.3: "the archive is refused with
    `ERR_FIELD_HAS_OPEN_PRESCRIPTIONS` while any prescription of the field
    remains in `DRAFT`, `APPROVED`, or `SENT` — only fields whose prescriptions
    have all reached `ACKNOWLEDGED` or `SUPERSEDED` may be archived."

    Design: Corner/entities/field_archive_with_open_prescription_rejected
    """
    ctx = setup_org_dealer(api)
    machine = add_machine(ctx, api)
    field = add_active_field(ctx, api)
    create_prescription(ctx, api, field["id"], machine["id"])

    response = api.archive_field_boundary(field["id"], headers=ctx["grower_headers"])
    validate_error(response, ApiErrorId.ERR_FIELD_HAS_OPEN_PRESCRIPTIONS)
    field = read_field(ctx, api, field["id"])
    assert field["status"] == "ACTIVE"


def test_prescription_create_with_empty_zones_rejected(api):
    """PRD section 3.3: "the array must be non-empty, and every rate and area
    must be strictly positive with at most two decimal places" — a present-but-
    empty `zones` array is a request-shape failure (`ERR_INVALID_REQUEST`,
    HTTP 400, PRD section 2.10 step 3).

    Design: Corner/validations/prescription_create_with_empty_zones_rejected
    """
    ctx = setup_org_dealer(api)
    machine = add_machine(ctx, api)
    field = add_active_field(ctx, api)
    field = read_field(ctx, api, field["id"])
    payload = create_prescription_payload(
        ctx["org"]["id"], field["id"], machine["id"], field["version"],
        zones=[],
    )
    response = api.create_prescription(payload, headers=ctx["grower_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

    rows, _meta = validate_paginated(
        api.list_prescriptions(
            headers=ctx["grower_headers"], params={"field_boundary_id": field["id"]}
        )
    )
    assert len(rows) == 0
    field = read_field(ctx, api, field["id"])
    assert field["version"] == 2


def test_prescription_create_with_inverted_window_rejected(api):
    """PRD section 3.3: "a validity window from `valid_from` to `valid_until`
    (both inclusive, and `valid_from` must precede `valid_until` or the request
    fails with `ERR_INVALID_REQUEST`)".

    Design: Corner/validations/prescription_create_with_inverted_window_rejected
    """
    ctx = setup_org_dealer(api)
    machine = add_machine(ctx, api)
    field = add_active_field(ctx, api)
    field = read_field(ctx, api, field["id"])
    payload = create_prescription_payload(
        ctx["org"]["id"], field["id"], machine["id"], field["version"],
        valid_from="2026-09-30T00:00:00Z",
        valid_until="2026-09-01T00:00:00Z",
    )
    response = api.create_prescription(payload, headers=ctx["grower_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)


def test_occ_stale_field_version_on_prescription_create(api):
    """PRD section 2.8: "Creating a prescription requires
    `expected_field_boundary_version`, carrying the client's last observed
    `version` of the target field boundary; if the field's version has since
    advanced — a prior prescription creation or a field activation legitimately
    advances it — the create is rejected with
    `ERR_STALE_FIELD_BOUNDARY_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting/occ_stale_field_version_on_prescription_create
    """
    ctx = setup_org_dealer(api)
    machine = add_machine(ctx, api)
    field = add_active_field(ctx, api)
    stale_version = read_field(ctx, api, field["id"])["version"]
    create_prescription(ctx, api, field["id"], machine["id"],
                        expected_field_boundary_version=stale_version)

    payload = create_prescription_payload(
        ctx["org"]["id"], field["id"], machine["id"], stale_version,
        crop_type="SOY",
        zones=[prescription_zone("z1", rate_l_per_ha=3.10, area_ha=10.00)],
    )
    response = api.create_prescription(payload, headers=ctx["grower_headers"])
    validate_error(response, ApiErrorId.ERR_STALE_FIELD_BOUNDARY_VERSION)

    rows, _meta = validate_paginated(
        api.list_prescriptions(
            headers=ctx["grower_headers"], params={"field_boundary_id": field["id"]}
        )
    )
    assert len(rows) == 1


def _create_two_zone_rounding_prescription(ctx, api):
    """The (2.55 L/ha x 1.10 ha) x 2 prescription from the rounding-order
    contract. Returns (field, prescription response data)."""
    machine = add_machine(ctx, api)
    field = add_active_field(ctx, api)
    version = read_field(ctx, api, field["id"])["version"]
    payload = create_prescription_payload(
        ctx["org"]["id"], field["id"], machine["id"], version,
        crop_type="CORN",
        zones=[
            prescription_zone("z1", rate_l_per_ha=2.55, area_ha=1.10),
            prescription_zone("z2", rate_l_per_ha=2.55, area_ha=1.10),
        ],
    )
    response = api.create_prescription(payload, headers=ctx["grower_headers"])
    return field, validate_success(response, 201)


def test_prescription_zone_rounding_order_per_zone_then_sum(api):
    """PRD section 3.3: "Each zone's quantity is its `rate_l_per_ha` multiplied
    by its `area_ha`, rounded half-up to two decimals; `total_product_liters`
    is the exact sum of those per-zone rounded values (sum-then-round is
    explicitly not the rule and yields different results — two zones of rate
    2.55 over 1.10 hectares each total 5.62 liters zone-rounded, against 5.61
    if summed first); and `weighted_avg_rate_l_per_ha` is that total divided by
    the summed zone areas, rounded half-up to three decimals."

    Design: Difficulty/combinatorial_formula/prescription_zone_rounding_order
    """
    ctx = setup_org_dealer(api)
    _field, rx = _create_two_zone_rounding_prescription(ctx, api)
    assert rx["total_product_liters"] == pytest.approx(5.62, abs=1e-9)
    assert abs(rx["total_product_liters"] - 5.61) > 0.001
    assert rx["weighted_avg_rate_l_per_ha"] == pytest.approx(2.555, abs=1e-9)


def test_prescription_zone_rounding_create_side_effects(api):
    """PRD section 3.3: "A new prescription starts `DRAFT` with `revision` 1"
    and PRD section 2.11: "creating a prescription increments the target field
    boundary's `version` (the prescription attaches to a specific field
    snapshot)".

    Design: Difficulty/combinatorial_formula/prescription_zone_rounding_order
    """
    ctx = setup_org_dealer(api)
    field, rx = _create_two_zone_rounding_prescription(ctx, api)
    assert rx["status"] == "DRAFT"
    assert rx["revision"] == 1
    assert rx["superseded_by_id"] is None
    field = read_field(ctx, api, field["id"])
    assert field["version"] == 3

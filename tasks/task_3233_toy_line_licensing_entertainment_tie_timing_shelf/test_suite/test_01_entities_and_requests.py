"""Entity creation, retrieval, listing, and request-shape corners."""
from test_helpers import (
    ApiErrorId,
    BRAND,
    NON_EXISTENT_UUID,
    assert_property,
    assert_sku,
    assert_studio,
    create_evergreen_line,
    create_property,
    create_sku,
    create_studio,
    fixtures,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_studio_create_returns_defaults_and_system_fields(api):
    """PRD §3.1: "A `PlatformAdmin` onboards a licensor by creating a `Studio` with
    a `name` and an optional `confidentiality_tier` of `STANDARD` (the default) or
    `STRICT`; the studio begins in `ACTIVE` status".

    Design: Corner/entities/studio_create_returns_defaults_and_system_fields
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api.create_studio({"name": "Studio One"}, fixtures.ADMIN)
    data = validate_success(resp, expected_status=201)
    assert_studio(data)
    assert data["confidentiality_tier"] == "STANDARD"
    assert data["status"] == "ACTIVE"
    assert data["version"] == 1


def test_property_get_round_trips_configuration(api):
    """PRD §3.1: "A `StudioRep` then registers each `Property` under a studio by
    supplying the owning `studio_id`, a `title`, a `category` of `FILM` or `SERIES`,
    a `reveal_date`, and a `release_date`. The property's `shift_count` starts at 0,
    and its `lifecycle` is derived from the clock as described in §2.6."

    Design: Corner/entities/property_get_round_trips_configuration
    """
    studio = create_studio()
    created = create_property(
        studio["id"],
        title="Galaxy Racers",
        category="FILM",
        reveal_date="2026-12-01T00:00:00Z",
        release_date="2027-06-01T00:00:00Z",
    )
    resp = api.get_property(created["id"], BRAND)
    data = validate_success(resp)
    assert_property(data)
    assert data["title"] == "Galaxy Racers"
    assert data["category"] == "FILM"
    assert data["shift_count"] == 0
    # Default clock 2026-09-01 is before reveal 2026-12-01 -> CONFIDENTIAL.
    assert data["lifecycle"] == "CONFIDENTIAL"


def test_skus_list_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "`limit` defaults to 10, with a minimum of 1 and a maximum of 100;
    `offset` defaults to 0. List responses carry `limit`, `offset`, `total_count`,
    and `has_more` inside the `meta` object."

    Design: Corner/entities/skus_list_paginates_with_total_count_and_has_more
    """
    line = create_evergreen_line()
    for name in ("A", "B", "C"):
        create_sku(line["id"], name=name)

    resp = api.list_skus(BRAND, params={"toy_line_id": line["id"], "limit": 2, "offset": 0})
    page1, meta1 = validate_paginated(resp)
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    resp = api.list_skus(BRAND, params={"toy_line_id": line["id"], "limit": 2, "offset": 2})
    page2, meta2 = validate_paginated(resp)
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_get_nonexistent_property_returns_404(api):
    """PRD §2.9: "For endpoints whose URL contains multiple path parameters, the
    referenced resources are validated for existence strictly left-to-right along
    the path; the first missing resource yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_nonexistent_property_returns_404
    """
    resp = api.get_property(NON_EXISTENT_UUID, BRAND)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_sku_create_missing_required_field_returns_400(api):
    """PRD §3.3: "Each `Sku` belongs to a line (supplied as `toy_line_id`) and
    carries a `name`; a claimed `age_grade_months` printed on the packaging, which
    must be at least 36 and at most 168; a set of `packaging_claims` drawn from
    `CHOKING_HAZARD_FREE`, `FLAME_RESISTANT`, and `BPA_FREE`; a factory minimum
    order quantity `moq_units` of at least 1; a landed `unit_cost_cents`; and a
    one-time `tooling_cost_cents`."
    PRD §2.9: "and finally general request-shape problems such as missing required
    fields, wrong types, or invalid enum members (`ERR_INVALID_REQUEST`, HTTP 400)".

    Design: Corner/entities/sku_create_missing_required_field_returns_400
    """
    line = create_evergreen_line()
    payload = {
        "toy_line_id": line["id"],
        "name": "A",
        "age_grade_months": 36,
        "packaging_claims": ["BPA_FREE"],
        "unit_cost_cents": 100,
        "tooling_cost_cents": 1000,
    }  # moq_units omitted
    resp = api.create_sku(payload, BRAND)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_property_lifecycle_boundary_at_reveal_date(api):
    """PRD §2.6: "The boundaries are inclusive on the later state: the instant the
    clock equals `reveal_date` the property is `REVEALED`, and the instant it equals
    `release_date` the property is `RELEASED`."

    Design: Corner/entities/property_lifecycle_boundary_at_reveal_date
    """
    studio = create_studio()
    prop = create_property(
        studio["id"],
        title="P",
        category="SERIES",
        reveal_date="2026-10-01T00:00:00Z",
        release_date="2027-01-01T00:00:00Z",
    )
    set_clock("2026-10-01T00:00:00Z")
    data = validate_success(api.get_property(prop["id"], BRAND))
    assert data["lifecycle"] == "REVEALED"

    set_clock("2027-01-01T00:00:00Z")
    data = validate_success(api.get_property(prop["id"], BRAND))
    assert data["lifecycle"] == "RELEASED"


def test_sku_invalid_packaging_claim_enum_rejected(api):
    """PRD §3.3: "An age grade outside the 36-to-168-month band, or a claim outside
    the declared enum, is rejected with `ERR_SAFETY_GATE` (HTTP 422)".

    Design: Corner/entities/sku_invalid_packaging_claim_enum_rejected
    """
    line = create_evergreen_line()
    payload = {
        "toy_line_id": line["id"],
        "name": "A",
        "age_grade_months": 36,
        "packaging_claims": ["EDIBLE"],
        "moq_units": 1,
        "unit_cost_cents": 100,
        "tooling_cost_cents": 1000,
    }
    resp = api.create_sku(payload, BRAND)
    validate_error(resp, ApiErrorId.ERR_SAFETY_GATE, expected_status=422)

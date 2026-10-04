"""Sourcing commitments: state gates, windows, supersede invariant, OCC (PRD §3.1, §2.5, §2.7)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, api_client,
    create_commitment_payload,
    make_supplier, create_approved_supplier, make_commitment,
    get_supplier_version,
)

SM = TEST_USERS["sourcing_manager_headers"]
POC = TEST_USERS["parent_ops_controller_headers"]


def test_commitment_create_requires_approved_supplier(api):
    """PRD §3.1: "Creating a commitment against a supplier that is not
    `APPROVED` fails with `ERR_SUPPLIER_NOT_APPROVED` (HTTP 409)."

    Design: Corner/state_machines/commitment_create_requires_approved_supplier
    """
    supplier = make_supplier(name="Unvetted Vanilla", category="VANILLA",
                             country_code="MG")
    payload = create_commitment_payload(
        supplier["version"], ingredient_category="VANILLA")
    resp = api.create_commitment(supplier["id"], payload, SM)
    validate_error(resp, ApiErrorId.ERR_SUPPLIER_NOT_APPROVED)


def test_commitment_window_invalid_rejected(api):
    """PRD §3.1: "The window must be non-degenerate — `effective_to` strictly
    later than `effective_from` — or the create fails with
    `ERR_COMMITMENT_WINDOW_INVALID` (HTTP 422)."

    Design: Corner/validations/commitment_window_invalid_rejected
    """
    supplier = create_approved_supplier(name="Bad Commitment Window", category="SUGAR")
    payload = create_commitment_payload(
        get_supplier_version(supplier["id"]),
        ingredient_category="SUGAR",
        effective_from="2027-01-01T00:00:00Z",
        effective_to="2026-01-01T00:00:00Z")
    resp = api.create_commitment(supplier["id"], payload, SM)
    validate_error(resp, ApiErrorId.ERR_COMMITMENT_WINDOW_INVALID)


def test_commitment_lapses_on_clock_advance(api):
    """PRD §2.5: "A sourcing commitment in `ACTIVE` whose `effective_to` is
    strictly earlier than the current logical time transitions to `LAPSED`. At
    exactly `effective_to` the commitment is still `ACTIVE`; the window end is
    exclusive."

    Design: Corner/state_machines/commitment_lapses_on_clock_advance
    """
    supplier = create_approved_supplier(name="Lapse Supplier", category="SUGAR")
    commitment = make_commitment(
        supplier["id"], category="SUGAR",
        effective_from="2026-01-01T00:00:00Z",
        effective_to="2026-12-31T00:00:00Z")
    validate_success(api.set_clock({"to_iso8601": "2027-01-01T00:00:00Z"}, POC))
    data, _ = validate_paginated(api.list_commitments(supplier["id"], SM))
    by_id = {c["id"]: c for c in data}
    assert by_id[commitment["id"]]["status"] == "LAPSED"


def test_commitment_list_pagination_envelope(api):
    """PRD §2.3: "Every list response carries the pagination fields `limit`,
    `offset`, `total_count`, and `has_more` in the `meta` object of the
    envelope."

    Design: Corner/endpoints/commitment_list_pagination_envelope
    """
    supplier = create_approved_supplier(name="Page Supplier", category="COCOA")
    make_commitment(supplier["id"], category="COCOA")
    make_commitment(supplier["id"], category="SUGAR")
    data, meta = validate_paginated(
        api.list_commitments(supplier["id"], SM, params={"limit": 1}))
    assert len(data) == 1, "limit must be honored"
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert meta["limit"] == 1
    assert meta["offset"] == 0


def test_commitment_supersede_single_active(api):
    """PRD §3.1: "A new commitment lands `ACTIVE` and supersedes whatever
    commitment was `ACTIVE` for the same supplier and category: the prior
    commitment moves to `SUPERSEDED`, so exactly one `ACTIVE` commitment exists
    per supplier-and-category pair, and the supplier's `version` bumps as part
    of the write."

    Design: Difficulty/compensating_invariant/commitment_supersede_single_active
    """
    supplier = create_approved_supplier(name="Supersede Supplier", category="COCOA")
    v1 = get_supplier_version(supplier["id"])
    c1 = validate_success(api.create_commitment(
        supplier["id"],
        create_commitment_payload(v1, ingredient_category="COCOA",
                                  min_social_score=60), SM),
        expected_status=201)
    v2 = get_supplier_version(supplier["id"])
    assert v2 == v1 + 1, "the superseding create bumps Supplier.version once"
    c2 = validate_success(api.create_commitment(
        supplier["id"],
        create_commitment_payload(v2, ingredient_category="COCOA",
                                  min_social_score=70), SM),
        expected_status=201)

    active, _ = validate_paginated(
        api.list_commitments(supplier["id"], SM, params={"status": "ACTIVE"}))
    superseded, _ = validate_paginated(
        api.list_commitments(supplier["id"], SM, params={"status": "SUPERSEDED"}))
    assert [c["id"] for c in active] == [c2["id"]]
    assert [c["id"] for c in superseded] == [c1["id"]]
    assert len(active) == 1, "exactly one ACTIVE commitment per (supplier, category)"


def test_commitment_supersede_scoped_to_category(api):
    """PRD §3.1: "A new commitment lands `ACTIVE` and supersedes whatever commitment was `ACTIVE` for the same supplier and category: the prior commitment moves to `SUPERSEDED`, so exactly one `ACTIVE` commitment exists per supplier-and-category pair, and the supplier's `version` bumps as part of the write."

    Design: Difficulty/compensating_invariant/commitment_supersede_single_active
    """
    supplier = create_approved_supplier(name="Two Category Supplier", category="COCOA")
    c1 = make_commitment(supplier["id"], category="COCOA")
    c2 = make_commitment(supplier["id"], category="SUGAR")

    active, _ = validate_paginated(
        api.list_commitments(supplier["id"], SM, params={"status": "ACTIVE"}))
    active_ids = sorted(c["id"] for c in active)
    assert active_ids == sorted([c1["id"], c2["id"]]), \
        "different categories must not supersede each other"
    superseded, _ = validate_paginated(
        api.list_commitments(supplier["id"], SM, params={"status": "SUPERSEDED"}))
    assert superseded == []


def test_occ_commitment_stale_version_rejected(api):
    """PRD §2.7: "`POST /creamery/suppliers/{id}/commitments` requires `expected_supplier_version`, carrying the client's last observed `version` of the parent Supplier." PRD §2.7: "If the value does not match the supplier's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_commitment_stale_version_rejected
    """
    supplier = create_approved_supplier(name="OCC Supplier", category="COCOA")
    stale_v = get_supplier_version(supplier["id"])
    first = api.create_commitment(
        supplier["id"],
        create_commitment_payload(stale_v, ingredient_category="COCOA"), SM)
    validate_success(first, expected_status=201)

    resp = api.create_commitment(
        supplier["id"],
        create_commitment_payload(stale_v, ingredient_category="SUGAR"), SM)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

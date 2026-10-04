"""Cross-cutting corners: OCC staleness, safety cascade, clock default, street-date inheritance."""
from test_helpers import (
    ApiErrorId,
    BRAND,
    STUDIO,
    canonical_instant,
    create_licensed_line,
    create_property,
    create_sku,
    create_studio,
    fixtures,
    setup_active_agreement,
    setup_licensed_chain,
    setup_review_with_commitment,
    setup_tooled_line,
    set_clock,
    validate_error,
    validate_success,
)


def test_stale_toy_line_version_rejected_on_advance(api):
    """PRD §2.8: "Advancing a toy line requires the request to carry
    `expected_toy_line_version`, the client's last observed `version` of the line.
    A mismatch with the line's current `version` — which may have moved because a
    release-shift cascade or a safety-invalidation cascade touched the line — is
    likewise rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_toy_line_version_rejected_on_advance
    """
    set_clock("2026-10-01T00:00:00Z")
    studio, prop, agreement = setup_active_agreement()
    line = create_licensed_line(prop["id"], agreement["id"], name="Racers")
    observed_version = line["version"]

    # The release-shift cascade bumps the line's version beyond the observed one.
    validate_success(api.shift_release(prop["id"], {"new_release_date": "2027-06-01T00:00:00Z"}, STUDIO))

    resp = api.advance_toy_line(line["id"], {"expected_toy_line_version": observed_version}, BRAND)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


def test_safety_patch_invalidates_passed_test_and_reverts_tooled_line(api):
    """PRD §3.4: "Editing a passed SKU's `age_grade_months` invalidates its
    certification: the latest `PASSED` test for that SKU is marked `INVALIDATED`
    (a non-terminal log marker — the test's terminal states remain `PASSED` and
    `FAILED` for result-recording purposes, and an invalidated test stays
    readable), the SKU's `safety_status` drops to `FAILED`, `claims_validated`
    becomes false, and `tested_age_grade_months` keeps its last value. If the
    owning line was `TOOLED`, the safety regression cascades: the line reverts to
    `IN_DEVELOPMENT`."

    Design: Corner/cross_cutting_complexity_layers/safety_patch_invalidates_passed_test_and_reverts_tooled_line
    """
    set_clock("2026-10-01T00:00:00Z")
    line, sku, factory, order = setup_tooled_line(
        street="2027-06-01T00:00:00Z", age_grade_months=48
    )
    assert line["status"] == "TOOLED"
    # Identify the PASSED test for the SKU.
    from test_helpers import validate_paginated

    tests, _ = validate_paginated(api.list_safety_tests(BRAND, params={"sku_id": sku["id"]}))
    passed_test = [t for t in tests if t["status"] == "PASSED"][0]

    resp = api.patch_sku(sku["id"], {"age_grade_months": 36}, BRAND)
    sku_data = validate_success(resp)
    assert sku_data["safety_status"] == "FAILED"
    assert sku_data["claims_validated"] is False
    assert sku_data["tested_age_grade_months"] == 48

    test_data = validate_success(api.get_safety_test(passed_test["id"], BRAND))
    assert test_data["status"] == "INVALIDATED"

    line_data = validate_success(api.get_toy_line(line["id"], BRAND))
    assert line_data["status"] == "IN_DEVELOPMENT"


def test_clock_default_is_2026_09_01(api):
    """PRD §2.5: "The system never reads the wall clock. All temporal logic runs
    against a logical clock whose startup value is exactly `2026-09-01T00:00:00Z`."
    PRD §2.6: "The boundaries are inclusive on the later state: the instant the
    clock equals `reveal_date` the property is `REVEALED`".

    Design: Corner/endpoints/clock_default_is_2026_09_01
    """
    # No clock-set call at all: the default clock is 2026-09-01T00:00:00Z.
    studio = create_studio(name="S")
    prop = create_property(
        studio["id"],
        title="P",
        reveal_date="2026-09-01T00:00:00Z",
        release_date="2027-01-01T00:00:00Z",
    )
    data = validate_success(api.get_property(prop["id"], BRAND))
    assert data["lifecycle"] == "REVEALED"


def test_shipment_street_date_inherited_from_line(api):
    """PRD §3.7: "The shipment's `street_date` is copied at creation from the target
    street date of the SKU's line, and thereafter moves only via the release-shift
    cascade of §3.1."
    PRD §3.3: "for a `LICENSED` line it mirrors the property's `release_date`".

    Design: Corner/endpoints/shipment_street_date_inherited_from_line
    """
    studio, prop, agreement, line, sku = setup_licensed_chain(release_date="2027-03-01T00:00:00Z")
    retailer, review, commitment = setup_review_with_commitment(
        sku, committed_units=100, unit_price_cents=100, shelf_slots=2
    )
    shipment = fixtures.create_shipment(
        commitment["id"], planned_ship_date="2027-02-01T00:00:00Z", units=100
    )
    assert canonical_instant(shipment["street_date"]) == canonical_instant("2027-03-01T00:00:00Z")

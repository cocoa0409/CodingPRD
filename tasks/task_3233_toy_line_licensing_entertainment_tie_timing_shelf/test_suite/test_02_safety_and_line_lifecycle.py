"""Safety testing, SKU safety state machine, and toy-line lifecycle corners."""
from test_helpers import (
    ApiErrorId,
    BRAND,
    SAFETY,
    assert_safety_test,
    assert_sku,
    certify_sku,
    create_agreement,
    create_evergreen_line,
    create_property,
    create_sku,
    create_studio,
    fixtures,
    set_clock,
    setup_tooled_line,
    submit_safety_test,
    validate_error,
    validate_success,
)


def test_license_amend_from_negotiation_returns_invalid_state(api):
    """PRD §3.2: "A `BrandManager` may propose new terms on an `ACTIVE` agreement by
    supplying a `royalty_rate_pct`, `advance_guarantee_cents`, and `end_date`".
    PRD §3.2: "acting on an agreement that is not in `AMENDMENT_PENDING` yields
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/license_amend_from_negotiation_returns_invalid_state
    """
    set_clock("2026-10-01T00:00:00Z")
    studio = create_studio(name="S")
    prop = create_property(studio["id"], title="P", release_date="2027-01-01T00:00:00Z")
    agreement = create_agreement(prop["id"])  # stays NEGOTIATION
    resp = api.amend_license_agreement(
        agreement["id"],
        {
            "royalty_rate_pct": 0.15,
            "advance_guarantee_cents": 0,
            "end_date": "2029-12-31T00:00:00Z",
        },
        BRAND,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_safety_test_record_result_drives_sku_status(api):
    """PRD §3.4: "A pass moves the SKU's `safety_status` to `PASSED`, sets its
    `tested_age_grade_months` to the lab value, and sets `claims_validated` true."

    Design: Corner/state_machines/safety_test_record_result_drives_sku_status
    """
    line = create_evergreen_line()
    sku = create_sku(line["id"], name="Bucket", age_grade_months=48)
    test = submit_safety_test(sku)
    resp = api.record_safety_result(
        test["id"],
        {"outcome": "PASS", "result_age_grade_months": 48, "validated_claims": ["BPA_FREE"]},
        SAFETY,
    )
    test_data = validate_success(resp)
    assert_safety_test(test_data)
    assert test_data["status"] == "PASSED"

    sku_data = validate_success(api.get_sku(sku["id"], BRAND))
    assert_sku(sku_data)
    assert sku_data["safety_status"] == "PASSED"
    assert sku_data["tested_age_grade_months"] == 48
    assert sku_data["claims_validated"] is True


def test_record_result_pass_with_age_over_claim_fails_test(api):
    """PRD §3.4: "A conformance failure on an otherwise-passing result is
    reported through the safety gate (`ERR_SAFETY_GATE`) rather than recorded."

    Design: Corner/state_machines/record_result_pass_with_age_over_claim_fails_test
    """
    line = create_evergreen_line()
    sku = create_sku(line["id"], name="Bucket", age_grade_months=36)
    test = submit_safety_test(sku)
    resp = api.record_safety_result(
        test["id"],
        {"outcome": "PASS", "result_age_grade_months": 48, "validated_claims": ["BPA_FREE"]},
        SAFETY,
    )
    validate_error(resp, ApiErrorId.ERR_SAFETY_GATE, expected_status=422)

    # "rather than recorded": the test is still SUBMITTED and the SKU is still
    # TESTING — no failure was persisted.
    test_data = validate_success(api.get_safety_test(test["id"], SAFETY))
    assert test_data["status"] == "SUBMITTED"
    sku_data = validate_success(api.get_sku(sku["id"], BRAND))
    assert sku_data["safety_status"] == "TESTING"


def test_retired_line_is_terminal_no_transitions(api):
    """PRD §3.7: "From `CLOSEOUT` a line may instead be retired to `RETIRED`, its
    terminal state, but only when no shipment referencing the line's SKUs remains
    `PLANNED` and no tooling order of the line remains `APPROVED`; otherwise the
    retire is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/retired_line_is_terminal_no_transitions
    """
    set_clock("2026-10-01T00:00:00Z")
    line, sku, factory, order = setup_tooled_line(street="2026-09-01T00:00:00Z", line_name="Nostalgia Minis")
    retailer, review = fixtures.setup_retail_open_review()
    fixtures.create_commitment(review["id"], sku["id"], committed_units=10, unit_price_cents=500, shelf_slots=1)
    line = fixtures.advance_line(line)  # TOOLED -> COMMITTED
    line = validate_success(api.enter_closeout(line["id"], {"markdown_pct": 0.20}, BRAND))
    assert line["status"] == "CLOSEOUT"
    # Retire requires no APPROVED tooling order: scrap it first.
    validate_success(api.scrap_tooling_order(order["id"], {}, BRAND))
    line = validate_success(api.retire_toy_line(line["id"], {}, BRAND))
    assert line["status"] == "RETIRED"

    # Any further lifecycle action on a terminal line fails with ERR_INVALID_STATE.
    resp = api.exit_closeout(line["id"], {}, BRAND)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_retired_line_rejects_advance_and_revert_and_retire(api):
    """PRD §3.4: "any advance attempt whose preconditions fail is rejected with
    `ERR_INVALID_STATE` (HTTP 409)".
    PRD §3.7: "From `CLOSEOUT` a line may instead be retired to `RETIRED`, its
    terminal state".

    Design: Corner/state_machines/retired_line_is_terminal_no_transitions
    """
    set_clock("2026-10-01T00:00:00Z")
    line, sku, factory, order = setup_tooled_line(street="2026-09-01T00:00:00Z", line_name="Nostalgia Minis")
    retailer, review = fixtures.setup_retail_open_review()
    fixtures.create_commitment(review["id"], sku["id"], committed_units=10, unit_price_cents=500, shelf_slots=1)
    line = fixtures.advance_line(line)
    line = validate_success(api.enter_closeout(line["id"], {"markdown_pct": 0.20}, BRAND))
    validate_success(api.scrap_tooling_order(order["id"], {}, BRAND))
    line = validate_success(api.retire_toy_line(line["id"], {}, BRAND))
    assert line["status"] == "RETIRED"

    resp = api.advance_toy_line(line["id"], {"expected_toy_line_version": line["version"]}, BRAND)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    resp = api.revert_toy_line(line["id"], {}, BRAND)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    resp = api.enter_closeout(line["id"], {"markdown_pct": 0.10}, BRAND)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    resp = api.retire_toy_line(line["id"], {}, BRAND)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

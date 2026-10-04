"""Cascade precedence and the compound-print-run read.

Two validation rows qualify a request ahead of another, and the compound
print-run status is the platform's one synthesised field.
"""

from test_helpers import (
    ApiErrorId,
    approve_artwork_for_set,
    approve_card_set,
    create_active_license,
    create_card_set_raw,
    create_line_ready,
    get_success_data,
    submit_card_set_for_review,
    TEST_USERS,
    validate_error,
    validate_success,
)

PM = TEST_USERS["product_manager_headers"]
QA = TEST_USERS["quality_analyst_headers"]
CS = TEST_USERS["collector_support_headers"]
ANALYST = TEST_USERS["redemption_analyst_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
PLANNER = TEST_USERS["production_planner_headers"]


def _approved_set_and_redemption(api):
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    card_set = submit_card_set_for_review(api, card_set["id"])
    card_set = get_success_data(approve_card_set(api, card_set["id"], card_set["version"]))
    redemption = get_success_data(
        api.issue_redemption(
            card_set["id"],
            {
                "redemption_code": "RDM-2001",
                "signer_name": "Ken Griffey Jr",
                "estimated_value_cents": 400000,
                "opened_on": "2026-09-01T00:00:00Z",
            },
            ANALYST,
        )
    )
    # PRD 3.5: closing requires the redemption to be FULFILLED, so the
    # deadline row is only reachable after a fulfilment.
    redemption = get_success_data(api.fulfill_redemption(redemption["id"], ANALYST))
    return license_obj, line, card_set, redemption


def test_the_back_date_check_precedes_the_redemption_deadline_check(api):
    """PRD §3.9: "The back-dating window on claim review
    (`ERR_CLAIM_BACKDATE_EXCEEDED`) and the licensor's artwork decision SLA
    (`ERR_APPROVAL_WINDOW_CLOSED`) are evaluated in this band, followed by the
    print-run decision's validity window (`ERR_PRINT_DECISION_WINDOW_CLOSED`)".

    PRD §2.9: "The back-dating window on claim review".

    Design: Corner/validations/price_checked_after_the_collector_facing_safety_rules
    """
    license_obj, line, card_set, _redemption = _approved_set_and_redemption(api)
    claim = get_success_data(
        api.file_quality_claim(
            card_set["id"],
            {
                "claim_type": "MISPRINT",
                "severity": "MINOR",
                "affected_quantity": 10,
                "filed_on": "2026-01-01T00:00:00Z",
            },
            QA,
        )
    )
    get_success_data(api.set_clock("2029-01-01T00:00:00Z", ADMIN))

    resp = api.open_claim_review(claim["id"], QA)
    error_id = validate_error(
        resp, ApiErrorId.ERR_CLAIM_BACKDATE_EXCEEDED, expected_status=422
    )["error_id"]
    assert error_id != ApiErrorId.ERR_REDEMPTION_DEADLINE_EXCEEDED, (
        "the collector-facing safety row outranks the fiscal deadline row"
    )
    after = validate_success(api.get_quality_claim(claim["id"], QA))
    assert after["status"] == "FILED"


def test_the_fiscal_deadline_row_is_independently_reachable(api):
    """PRD §3.5: "Closing a fulfilled redemption requires the clock to be at or
    before `opened_on` plus `deadline_days`; closing after that is refused with
    `ERR_REDEMPTION_DEADLINE_EXCEEDED`."

    Design: Corner/validations/price_checked_after_the_collector_facing_safety_rules
    """
    license_obj, line, card_set, redemption = _approved_set_and_redemption(api)
    get_success_data(api.set_clock("2029-01-01T00:00:00Z", ADMIN))
    resp = api.close_redemption(redemption["id"], ANALYST)
    validate_error(resp, ApiErrorId.ERR_REDEMPTION_DEADLINE_EXCEEDED, expected_status=422)


def test_a_conforming_complaint_passes_every_validation_row(api):
    """PRD §3.7: "A `CollectorSupportSpecialist` files one against a set with a
    `complaint_label` for display, a `breach_reason` classified as either
    `UNDISCLOSED_PRINT_RUN` or `NO_REPLACEMENT_POLICY`, and a `claim_quantity`
    asserting how many cards the collector says were affected."

    PRD §3.7: "A new complaint opens in `OPEN` status."

    Design: Corner/validations/a_wildcard_free_request_still_passes_every_validation
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    card_set = submit_card_set_for_review(api, card_set["id"])
    card_set = get_success_data(approve_card_set(api, card_set["id"], card_set["version"]))

    resp = api.file_complaint(
        card_set["id"],
        {
            "complaint_label": "Replacement policy absent",
            "breach_reason": "NO_REPLACEMENT_POLICY",
            "claim_quantity": 250,
        },
        CS,
    )
    complaint = validate_success(resp, expected_status=201)
    assert complaint["status"] == "OPEN"
    assert complaint["breach_reason"] == "NO_REPLACEMENT_POLICY"
    assert complaint["claim_quantity"] == 250
    assert "error_id" not in resp.json()


def test_an_open_complaint_does_not_yet_move_the_settled_counter(api):
    """PRD §3.7: "Approval moves the complaint to `APPROVED` and recomputes
    `settled_complaint_count` on the parent set — note that the counter tracks
    approved complaints while its name refers to settlement".

    Design: Corner/validations/a_wildcard_free_request_still_passes_every_validation
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    card_set = submit_card_set_for_review(api, card_set["id"])
    get_success_data(approve_card_set(api, card_set["id"], card_set["version"]))
    get_success_data(
        api.file_complaint(
            card_set["id"],
            {
                "complaint_label": "Run never disclosed",
                "breach_reason": "UNDISCLOSED_PRINT_RUN",
                "claim_quantity": 5,
            },
            CS,
        )
    )
    read = validate_success(api.get_card_set(card_set["id"], PM))
    assert read["settled_complaint_count"] == 0


def test_the_availability_authority_outranks_the_quantity_rule(api):
    """PRD §3.7: "A complaint alleging `NO_REPLACEMENT_POLICY` is approved only
    if the set carries no quality claims at all, `quality_claim_count` being
    zero — a set that already has claims on record plainly does have a
    replacement policy in effect, and the complaint is refused with
    `ERR_REPLACEMENT_POLICY_EXISTS`."

    PRD §3.7: "Both branches independently require `claim_quantity` to be at
    least 1, and a complaint asserting fewer is refused with
    `ERR_CLAIM_QUANTITY_INVALID` regardless of which breach reason it names."

    Design: Corner/validations/claim_quantity_override_is_checked_after_the_availability_authority
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    card_set = submit_card_set_for_review(api, card_set["id"])
    card_set = get_success_data(approve_card_set(api, card_set["id"], card_set["version"]))

    get_success_data(
        api.file_quality_claim(
            card_set["id"],
            {
                "claim_type": "MISPRINT",
                "severity": "MINOR",
                "affected_quantity": 10,
                "filed_on": "2026-09-01T00:00:00Z",
            },
            QA,
        )
    )
    complaint = get_success_data(
        api.file_complaint(
            card_set["id"],
            {
                "complaint_label": "No replacement policy",
                "breach_reason": "NO_REPLACEMENT_POLICY",
                "claim_quantity": 0,
            },
            CS,
        )
    )
    get_success_data(api.start_complaint_review(complaint["id"], CS))

    resp = api.approve_complaint(complaint["id"], CS)
    error_id = validate_error(
        resp, ApiErrorId.ERR_REPLACEMENT_POLICY_EXISTS, expected_status=422
    )["error_id"]
    assert error_id != ApiErrorId.ERR_CLAIM_QUANTITY_INVALID, (
        "the availability gate precedes the quantity rule on the same request"
    )
    after = validate_success(api.get_complaint(complaint["id"], CS))
    assert after["status"] == "UNDER_REVIEW"


def test_without_any_claims_the_same_complaint_reports_the_quantity_rule(api):
    """PRD §3.7: "a complaint asserting fewer is refused with
    `ERR_CLAIM_QUANTITY_INVALID` regardless of which breach reason it names."

    Design: Corner/validations/claim_quantity_override_is_checked_after_the_availability_authority
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(api, line["id"], set_tier="BASE", print_run_quantity=500)
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    card_set = submit_card_set_for_review(api, card_set["id"])
    card_set = get_success_data(approve_card_set(api, card_set["id"], card_set["version"]))
    complaint = get_success_data(
        api.file_complaint(
            card_set["id"],
            {
                "complaint_label": "No replacement policy",
                "breach_reason": "NO_REPLACEMENT_POLICY",
                "claim_quantity": 0,
            },
            CS,
        )
    )
    get_success_data(api.start_complaint_review(complaint["id"], CS))
    resp = api.approve_complaint(complaint["id"], CS)
    validate_error(resp, ApiErrorId.ERR_CLAIM_QUANTITY_INVALID, expected_status=422)


def test_the_undisclosed_breach_tests_the_sets_compound_run_status(api):
    """PRD §3.8: "A complaint alleging `UNDISCLOSED_PRINT_RUN` is approved only
    if the card set's compound print-run status is currently `UNDISCLOSED` —
    the complaint is refused with `ERR_UNDISCLOSED_RUN_DECLARED` when the set's
    run was in fact `DISCLOSED`."

    Design: Corner/validations/claim_quantity_override_is_checked_after_the_availability_authority
    """
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(
        api, line["id"], set_tier="BASE", print_run_quantity=500, announced=True
    )
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    card_set = submit_card_set_for_review(api, card_set["id"])
    card_set = get_success_data(approve_card_set(api, card_set["id"], card_set["version"]))
    decision = get_success_data(
        api.create_print_run_decision(
            {
                "card_set_id": card_set["id"],
                "authority": "BRAND_DIRECTIVE",
                "proposed_against_line_version": line["version"],
                "demand_multiplier": 1.0,
                "declared_quantity": 12000,
                "announced": True,
                "proposed_on": "2026-09-05T00:00:00Z",
            },
            PLANNER,
        )
    )
    frozen = validate_success(
        api.approve_print_run_decision(
            decision["id"],
            {
                "expected_card_set_version": card_set["version"],
                "expected_product_line_version": line["version"],
            },
            PLANNER,
        )
    )
    assert frozen["announced"] is True
    read = validate_success(api.get_card_set(card_set["id"], PM))
    assert read["print_run_status"] == "DISCLOSED"

    complaint = get_success_data(
        api.file_complaint(
            card_set["id"],
            {
                "complaint_label": "Run never disclosed",
                "breach_reason": "UNDISCLOSED_PRINT_RUN",
                "claim_quantity": 5,
            },
            CS,
        )
    )
    get_success_data(api.start_complaint_review(complaint["id"], CS))
    resp = api.approve_complaint(complaint["id"], CS)
    validate_error(resp, ApiErrorId.ERR_UNDISCLOSED_RUN_DECLARED, expected_status=422)
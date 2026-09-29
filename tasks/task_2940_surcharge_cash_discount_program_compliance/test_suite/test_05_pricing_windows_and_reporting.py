"""Pricing arithmetic at the awkward boundaries, the two reporting surfaces, and the
window conventions that decide what counts."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_days_apart,
    assert_instant_equals,
    assert_terminal_census,
    attest_disclosures,
    capture_sale,
    file_complaint,
    investigation_action,
    list_total,
    read_artifact,
    read_merchant,
    read_program,
    read_terminal,
    read_transaction,
    set_clock,
    setup_active_surcharge_program,
    setup_configured_terminal,
    setup_draft_program,
    setup_enforcing_surcharge_estate,
    setup_program_with_effective_registration,
    terminal_action,
    validate_error,
    validate_success,
)
from test_helpers.constants import (
    CLOCK_AUG_01,
    CLOCK_SEP_01,
    OFFICER_TWO_USER_ID,
    TS_AUG_01,
    TS_AUG_31,
    TS_SEP_01,
)
from test_helpers.fixtures import ADMIN, AUDITOR, OFFICER_ONE, REGULATOR
from test_helpers.test_users import make_terminal_agent_headers

CLOCK_SEP_02 = "2026-09-02T00:00:00Z"
TS_SEP_02 = "2026-09-02T00:00:00.000Z"
TS_AUG_11 = "2026-08-11T00:00:00.000Z"
TS_AUG_21 = "2026-08-21T00:00:00.000Z"


def test_a_debit_sale_prices_at_zero_without_ever_selecting_a_rule(api):
    """PRD §3.9: "**Rate selection.** The server then chooses which rate applies, and it begins with the credit-only guard: on a `SURCHARGE` program whose sale carries `card_funding` other than `CREDIT`, no rule is selected at all, `applied_rate_pct` is 0, and the absence of a rule is explicitly *not* an error."
    PRD §3.9: "On a `SURCHARGE` program with `card_funding` of `DEBIT` or `PREPAID`: `surcharge_amount_cents` is 0, `cash_discount_amount_cents` is 0, `cash_price_cents` equals `base_amount_cents`, `total_amount_cents` equals `base_amount_cents`, and `outcome` is `APPROVED_NO_SURCHARGE`."

    Design: Corner/calculations/credit_only_guard_prices_a_debit_sale_at_zero_without_consulting_rate_rules
    """
    ctx = setup_enforcing_surcharge_estate(serial_prefix="TRM-AZ-")
    terminal_id = ctx["terminal"]["id"]

    sale = validate_success(
        api_client.create_transaction(
            {
                "terminal_id": terminal_id,
                "program_id": ctx["program"]["id"],
                "card_brand": "AMEX",
                "card_funding": "DEBIT",
                "product_tier": "NOT_APPLICABLE",
                "base_amount_cents": 10000,
                "requested_surcharge_cents": 0,
                "receipt_line_present": False,
            },
            make_terminal_agent_headers(terminal_id),
        ),
        expected_status=201,
    )
    assert sale["outcome"] == "APPROVED_NO_SURCHARGE"
    assert sale["applied_rate_pct"] == pytest.approx(0.0, abs=0.00001)
    assert sale["surcharge_amount_cents"] == 0
    assert sale["cash_discount_amount_cents"] == 0
    assert sale["cash_price_cents"] == 10000
    assert sale["total_amount_cents"] == 10000

    merchant = read_merchant(ctx["merchant"]["id"])
    assert merchant["gross_surcharge_collected_cents"] == 0
    assert merchant["net_surcharge_collected_cents"] == 0


def test_an_exact_half_cent_surcharge_rounds_up(api):
    """PRD §2.8: "Any conversion from a percentage to cents rounds **half up to the nearest whole cent**, and that rounding happens exactly once per transaction line."
    PRD §3.9: "On a `SURCHARGE` program with `card_funding` of `CREDIT`: `surcharge_amount_cents` is `base_amount_cents` multiplied by the applied rate, divided by 100, rounded half up to a whole cent; `cash_discount_amount_cents` is 0; `cash_price_cents` equals `base_amount_cents`; `total_amount_cents` is `base_amount_cents` plus `surcharge_amount_cents`; and `outcome` is `APPROVED_WITH_SURCHARGE`."
    PRD §3.9: "The merchant's `gross_surcharge_collected_cents` is the sum of `surcharge_amount_cents` over every sale captured by that merchant's terminals whose `outcome` is `APPROVED_WITH_SURCHARGE`, taken over all time with no window; it increases by this sale's surcharge and never decreases for any reason."

    Design: Corner/calculations/surcharge_rounding_uses_round_half_up_at_the_exact_half_cent
    """
    ctx = setup_enforcing_surcharge_estate(serial_prefix="TRM-AZ-")
    terminal_id = ctx["terminal"]["id"]

    sale = validate_success(
        api_client.create_transaction(
            {
                "terminal_id": terminal_id,
                "program_id": ctx["program"]["id"],
                "card_brand": "VISA",
                "card_funding": "CREDIT",
                "product_tier": "CONSUMER_CREDIT",
                "base_amount_cents": 5000,
                "requested_surcharge_cents": 110,
                "receipt_line_present": True,
            },
            make_terminal_agent_headers(terminal_id),
        ),
        expected_status=201,
    )
    assert sale["surcharge_amount_cents"] == 110
    assert sale["total_amount_cents"] == 5110
    assert sale["applied_rate_pct"] == pytest.approx(2.19, abs=0.00001)
    assert sale["outcome"] == "APPROVED_WITH_SURCHARGE"

    merchant = read_merchant(ctx["merchant"]["id"])
    assert merchant["gross_surcharge_collected_cents"] == 110
    assert merchant["net_surcharge_collected_cents"] == 110


def test_the_settlement_window_excludes_a_sale_sitting_on_the_upper_bound(api):
    """PRD §3.11: "A sale is in scope when its `occurred_at` is at or after `from_iso8601` — an inclusive lower bound — and strictly before `to_iso8601` — an exclusive upper bound; an omitted bound imposes no constraint on that side."
    PRD §3.11: "The summary reports `program_id`; `transaction_count` as the number of in-scope sales, counting all three outcome arms; `base_amount_total_cents` as the sum of `base_amount_cents` over all in-scope sales, again across all three arms; and `per_line_rounded_surcharge_cents` as the sum of the `surcharge_amount_cents` already stored on those sales."
    PRD §3.11: "`rounding_divergence_cents` is then `per_line_rounded_surcharge_cents` minus `pooled_rounding_reference_cents`."

    Design: Corner/calculations/settlement_window_upper_bound_is_exclusive
    """
    ctx = setup_enforcing_surcharge_estate(serial_prefix="TRM-AZ-")
    program_id = ctx["program"]["id"]
    terminal_id = ctx["terminal"]["id"]
    capture_sale(terminal_id, program_id, base_amount_cents=1234, requested_surcharge_cents=27)
    set_clock(CLOCK_SEP_01)
    capture_sale(terminal_id, program_id, base_amount_cents=5678, requested_surcharge_cents=124)
    set_clock(CLOCK_SEP_02)
    third = capture_sale(
        terminal_id, program_id, base_amount_cents=9012, requested_surcharge_cents=197
    )

    windowed = validate_success(
        api_client.get_settlement_summary(
            program_id,
            OFFICER_ONE,
            params={"from_iso8601": "2026-08-31T00:00:00Z", "to_iso8601": CLOCK_SEP_02},
        )
    )
    assert windowed["transaction_count"] == 2
    assert windowed["base_amount_total_cents"] == 6912
    assert windowed["per_line_rounded_surcharge_cents"] == 151
    assert windowed["pooled_rounding_reference_cents"] == 151
    assert windowed["rounding_divergence_cents"] == 0
    assert windowed["refunded_surcharge_cents"] == 0
    assert windowed["net_surcharge_cents"] == 151

    assert_instant_equals(read_transaction(third["id"])["occurred_at"], TS_SEP_02, "occurred_at")

    unbounded = validate_success(
        api_client.get_settlement_summary(program_id, OFFICER_ONE)
    )
    assert unbounded["transaction_count"] == 3
    assert unbounded["base_amount_total_cents"] == 15924
    assert unbounded["per_line_rounded_surcharge_cents"] == 348


def test_three_substantiated_attorney_general_cases_clamp_the_network_score(api):
    """PRD §3.10: "Each such case contributes a base of 20 points multiplied by the weight of its filing `source`: 1.5 for `NETWORK`, 2.0 for `ATTORNEY_GENERAL`, and 1.0 for `CARDHOLDER`."
    PRD §3.10: "Those contributions are summed, the sum is rounded half up to two decimal places, and the result is capped at 100."
    PRD §3.11: "It reports `program_id`, the persisted `network_exposure_score` and `ag_exposure_score`, `substantiated_case_count` as the number of that program's cases whose `investigation_state` is `SUBSTANTIATED`, `unresolved_case_count` as the number whose `investigation_state` is `OPEN` or `UNDER_REVIEW`, `posture_multiplier` as the weight implied by the jurisdiction's `ag_enforcement_posture`, and `remediation_threshold` as the network-method trigger of 30."
    PRD §3.10: "If the recomputed score stays below 30, or the program was not `ACTIVE`, only the case's own fields move."

    Design: Corner/calculations/exposure_score_ceiling_caps_the_network_method_at_one_hundred
    """
    ctx = setup_draft_program(jurisdiction_profile="NY")
    program_id = ctx["program"]["id"]
    cases = [
        file_complaint(program_id, "ATTORNEY_GENERAL", allegation_type="CAP_EXCEEDED")
        for _ in range(3)
    ]
    investigation_action(cases[0]["id"], "SUBSTANTIATE", "ATTORNEY_GENERAL")
    investigation_action(cases[1]["id"], "SUBSTANTIATE", "ATTORNEY_GENERAL")

    third = validate_success(
        api_client.complaint_investigation_action(
            cases[2]["id"],
            {"action": "SUBSTANTIATE", "note": "rate table confirms"},
            REGULATOR,
        )
    )
    assert third["investigation_state"] == "SUBSTANTIATED"
    assert third["remediation_state"] == "PLAN_REQUIRED"

    summary = validate_success(api_client.get_exposure_summary(program_id, REGULATOR))
    assert summary["network_exposure_score"] == pytest.approx(100.00, abs=0.005)
    assert summary["ag_exposure_score"] == pytest.approx(60.00, abs=0.005)
    assert summary["substantiated_case_count"] == 3
    assert summary["unresolved_case_count"] == 0
    assert summary["posture_multiplier"] == pytest.approx(1.0, abs=0.00001)
    assert summary["remediation_threshold"] == 30

    program = read_program(program_id)
    assert program["status"] == "DRAFT"
    assert program["disable_reason"] == "NONE"


def test_the_two_methods_split_an_open_case_from_a_dismissed_one(api):
    """PRD §3.10: "The **attorney-general method**, persisted as `ag_exposure_score`, counts a wider set and ignores the source entirely."
    PRD §3.10: "Every case whose `investigation_state` is `OPEN`, `UNDER_REVIEW`, or `SUBSTANTIATED` contributes: 20 points if it is `SUBSTANTIATED`, and 8 points if it is merely `OPEN` or `UNDER_REVIEW`."
    PRD §3.10: "That sum is then multiplied by the posture weight of the program's jurisdiction — 0.5 for `PERMISSIVE`, 1.0 for `MONITORED`, and 2.0 for `RESTRICTIVE` — the product is rounded half up to two decimal places, and the result is capped at 100."
    PRD §3.10: "The **network method**, persisted as `network_exposure_score`, counts *only* cases whose `investigation_state` is `SUBSTANTIATED`."

    Design: Corner/calculations/open_and_dismissed_cases_split_between_the_two_exposure_variants
    """
    ctx = setup_draft_program(jurisdiction_profile="AZ")
    program_id = ctx["program"]["id"]
    still_open = file_complaint(program_id, "NETWORK", allegation_type="MISSING_RECEIPT_LINE")
    assert still_open["investigation_state"] == "OPEN"
    to_dismiss = file_complaint(program_id, "CARDHOLDER", allegation_type="UNDISCLOSED_SURCHARGE")
    dismissed = investigation_action(to_dismiss["id"], "DISMISS", "CARDHOLDER")
    assert dismissed["investigation_state"] == "DISMISSED"
    assert dismissed["remediation_state"] == "NONE"

    summary = validate_success(api_client.get_exposure_summary(program_id, AUDITOR))
    assert summary["network_exposure_score"] == pytest.approx(0.00, abs=0.005)
    assert summary["ag_exposure_score"] == pytest.approx(4.00, abs=0.005)
    assert summary["substantiated_case_count"] == 0
    assert summary["unresolved_case_count"] == 1
    assert summary["posture_multiplier"] == pytest.approx(0.5, abs=0.00001)

    program = read_program(program_id)
    assert program["network_exposure_score"] == pytest.approx(0.00, abs=0.005)
    assert program["ag_exposure_score"] == pytest.approx(4.00, abs=0.005)


def test_each_filing_channel_gets_its_own_response_deadline(api):
    """PRD §3.10: "`response_due_at` is `received_at` plus the window for the case's `source`: 10 days for a `NETWORK` complaint, 20 days for an `ATTORNEY_GENERAL` complaint, and 30 days for a `CARDHOLDER` complaint, with day arithmetic in exact 24-hour multiples and the result rendered as an ISO 8601 UTC instant with three fractional digits."
    PRD §3.10: "The server stamps `received_at` from the logical clock, records the filer's `X-User-ID` as `filed_by_user_id`, and opens the case with `investigation_state` of `OPEN` and `remediation_state` of `NONE`."
    PRD §3.10: "A newly filed case carries `reviewed_by_user_id` null, `plan_summary` null, and `refund_total_cents` 0."

    Design: Corner/calculations/response_due_at_applies_the_source_specific_response_window
    """
    ctx = setup_draft_program(jurisdiction_profile="AZ")
    program_id = ctx["program"]["id"]

    network_case = file_complaint(program_id, "NETWORK", allegation_type="CAP_EXCEEDED")
    assert_instant_equals(network_case["received_at"], TS_AUG_01, "received_at")
    assert_instant_equals(
        network_case["response_due_at"], TS_AUG_11, "NETWORK response_due_at"
    )
    assert_days_apart(
        network_case["response_due_at"], network_case["received_at"], 10, "NETWORK window"
    )

    ag_case = file_complaint(program_id, "ATTORNEY_GENERAL", allegation_type="CAP_EXCEEDED")
    assert_instant_equals(
        ag_case["response_due_at"], TS_AUG_21, "AG response_due_at"
    )
    assert_days_apart(ag_case["response_due_at"], ag_case["received_at"], 20, "AG window")

    cardholder_case = file_complaint(
        program_id, "CARDHOLDER", allegation_type="MISSING_RECEIPT_LINE"
    )
    assert_instant_equals(
        cardholder_case["response_due_at"], TS_AUG_31, "CARDHOLDER response_due_at"
    )
    assert_days_apart(
        cardholder_case["response_due_at"],
        cardholder_case["received_at"],
        30,
        "CARDHOLDER window",
    )
    assert cardholder_case["reviewed_by_user_id"] is None
    assert cardholder_case["plan_summary"] is None
    assert cardholder_case["refund_total_cents"] == 0


def test_a_clock_landing_exactly_on_expiry_leaves_the_program_unready(api):
    """PRD §3.6: "An attested window is **half-open**: it runs from `effective_from` inclusive up to `expires_at` exclusive."
    PRD §3.6: "Artifacts in `DRAFT` and artifacts in `EXPIRED` never satisfy a requirement, and neither does an `ATTESTED` artifact whose window the clock has left."
    PRD §2.5: "This means an artifact whose window has lapsed does not become `EXPIRED` merely because the clock moved past `expires_at`; it simply stops satisfying a disclosure requirement, because readiness is evaluated against the clock at the moment of evaluation."

    Design: Corner/calculations/disclosure_readiness_window_upper_bound_is_exclusive_at_expiry
    """
    ctx = setup_program_with_effective_registration(jurisdiction_profile="NY")
    program_id = ctx["program"]["id"]
    artifacts = attest_disclosures(
        program_id,
        ctx["merchant"]["id"],
        ["ENTRY_SIGNAGE", "POS_SIGNAGE", "RECEIPT_TEMPLATE"],
        CLOCK_AUG_01,
        CLOCK_SEP_01,
        OFFICER_TWO_USER_ID,
    )
    assert read_program(program_id)["disclosure_ready"] is True

    set_clock(CLOCK_SEP_01)
    response = api_client.activate_program(program_id, OFFICER_ONE)
    validate_error(response, ApiErrorId.ERR_DISCLOSURE_INCOMPLETE)

    program = read_program(program_id)
    assert program["status"] == "PENDING_REGISTRATION"
    # The stored disclosure_ready flag is deliberately not asserted here: PRD §2.11
    # states a failing request "changes nothing", so the rejected activation leaves
    # the persisted flag untouched rather than writing the recomputed false value.
    assert program["activated_at"] is None

    for artifact in artifacts.values():
        row = read_artifact(artifact["id"])
        assert row["state"] == "ATTESTED"
        assert row["expired_reason"] == "NONE"
        assert_instant_equals(row["expires_at"], TS_SEP_01, "expires_at")
    assert (
        list_total(
            api_client.list_disclosure_artifacts(
                ADMIN, params={"program_id": program_id, "state": "ATTESTED"}
            )
        )
        == 3
    )


def test_the_census_counts_only_the_terminal_that_reached_enforcing(api):
    """PRD §3.8: "A merchant's `enforcing_terminal_count` is always the number of that merchant's terminals whose `state` is exactly `ENFORCING`; terminals in `PROVISIONED`, `CONFIGURED`, `QUARANTINED`, and `DISABLED` are all excluded, and the count is a non-negative integer recomputed on every transition into or out of `ENFORCING`, including the quarantine cascades and configuration."
    PRD §3.8: "**`ENFORCE`**, available to a `MerchantOperator` only, requires the terminal to be in `CONFIGURED` and moves it to `ENFORCING`."
    PRD §3.8: "On success `quarantine_reason` is reset to `NONE`, `enforcing_terminal_count` is recomputed for the merchant, and the terminal's `version` is bumped by 1."

    Design: Corner/calculations/enforcing_census_excludes_configured_terminals
    """
    ctx = setup_active_surcharge_program(jurisdiction_profile="AZ")
    merchant_id = ctx["merchant"]["id"]
    program_id = ctx["program"]["id"]
    first = setup_configured_terminal(merchant_id, program_id, "TRM-AZ-0001")
    second = setup_configured_terminal(merchant_id, program_id, "TRM-AZ-0002")
    assert_terminal_census(read_merchant(merchant_id), 0)

    enforcing = terminal_action(first["id"], merchant_id, "ENFORCE")
    assert enforcing["state"] == "ENFORCING"
    assert enforcing["quarantine_reason"] == "NONE"
    assert enforcing["version"] == first["version"] + 1
    assert_terminal_census(read_merchant(merchant_id), 1)

    assert read_terminal(second["id"])["state"] == "CONFIGURED"
    assert (
        list_total(
            api_client.list_terminals(
                ADMIN, params={"merchant_id": merchant_id, "state": "ENFORCING"}
            )
        )
        == 1
    )
    assert (
        list_total(
            api_client.list_terminals(
                ADMIN, params={"merchant_id": merchant_id, "state": "CONFIGURED"}
            )
        )
        == 1
    )

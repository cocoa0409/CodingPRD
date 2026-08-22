"""The Medicare sixty-day repayment obligation, its lateness tiers and self-report."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_instant_equals,
    assert_medicare_obligation,
    attribute_all,
    create_compliance_report_payload,
    find_obligation_for_credit_balance,
    read_credit_balance,
    read_obligation,
    read_report,
    read_account,
    report_obligation,
    run_ops_checkpoint,
    set_clock,
    setup_attributed_credit,
    setup_multi_credit_scenario,
    validate_error,
    validate_success,
)

COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def _two_medicare_obligations():
    """Two MEDICARE credits of 12,000 cents identified on the same sweep."""
    scenario = setup_multi_credit_scenario(
        accounts=[
            {"account_number": "ACCT-MB1", "payment_source": "PAYER",
             "financial_class": "INPATIENT"},
            {"account_number": "ACCT-MB2", "payment_source": "PAYER",
             "financial_class": "INPATIENT"},
        ],
        payer_code="MCR", payer_type="MEDICARE",
    )
    scenario["credit_balances"] = attribute_all(
        [cb["id"] for cb in scenario["credit_balances"]]
    )
    scenario["obligations"] = [
        find_obligation_for_credit_balance(cb["id"])
        for cb in scenario["credit_balances"]
    ]
    return scenario


def test_obligation_reported_on_day_sixty_is_on_time_with_no_penalty(api):
    """PRD §3.11: "The new obligation carries the `credit_balance_id` of the credit, the `payer_id` of that payer, an `identified_at` copied verbatim from the credit balance's own `identified_at`, a `reportable_amount_cents` frozen at the credit's `payer_portion_cents`, and a `due_at` exactly 60 days after `identified_at`."
    PRD §3.11: "`days_elapsed` is the whole floored days from `identified_at` to the logical clock. The obligation is on time exactly when `days_elapsed` is at most 60 — day sixty itself is compliant. `days_late` is `days_elapsed` minus 60 when that difference is positive, and 0 otherwise."
    PRD §3.11: "A report filed while the obligation is on time lands `OPEN → REPORTED` and leaves `penalty_cents` at 0."

    Design: Difficulty/boundary_precision_check/medicare_sixty_day_window_day60_on_time_versus_day61_late
    """
    scenario = _two_medicare_obligations()
    obligation_id = scenario["obligations"][0]["id"]
    assert_medicare_obligation(scenario["obligations"][0])
    assert_instant_equals(
        scenario["obligations"][0]["due_at"], "2026-10-14T00:00:00Z", "due_at"
    )

    set_clock("2026-10-14T00:00:00Z")
    reported = validate_success(
        api.report_medicare_obligation(
            obligation_id, {"report_reference": "CBR-ONTIME-1"}, COMPLIANCE
        )
    )

    assert reported["state"] == "REPORTED"
    assert reported["days_elapsed"] == 60
    assert reported["days_late"] == 0
    assert reported["penalty_cents"] == 0
    assert reported["report_reference"] == "CBR-ONTIME-1"


def test_obligation_reported_on_day_sixty_one_is_late_with_a_two_percent_penalty(api):
    """PRD §3.11: "A report filed on an obligation that is `LATE` lands `LATE → REPORTED_LATE` and writes `penalty_cents` from the tiered assessment. So an obligation reported on day sixty is `REPORTED` with no penalty, while the same obligation reported on day sixty-one is `REPORTED_LATE` with one day late and a two-percent penalty."
    PRD §3.11: "When `days_late` is at least 1 and at most 30, the penalty is two percent of `reportable_amount_cents`, rounded half up to a whole cent."
    PRD §3.14: "Every Medicare repayment obligation in `state` `OPEN` whose `due_at` is strictly before the logical clock moves `OPEN → LATE`, with `days_elapsed`, `days_late` and `penalty_cents` recomputed."

    Design: Difficulty/boundary_precision_check/medicare_sixty_day_window_day60_on_time_versus_day61_late
    """
    scenario = _two_medicare_obligations()
    on_time_id = scenario["obligations"][0]["id"]
    late_id = scenario["obligations"][1]["id"]

    set_clock("2026-10-14T00:00:00Z")
    report_obligation(on_time_id, "CBR-ONTIME-1")

    set_clock("2026-10-15T00:00:00Z")
    run_ops_checkpoint(COMPLIANCE)
    reported_late = validate_success(
        api.report_medicare_obligation(
            late_id, {"report_reference": "CBR-LATE-1"}, COMPLIANCE
        )
    )

    assert reported_late["state"] == "REPORTED_LATE"
    assert reported_late["days_elapsed"] == 61
    assert reported_late["days_late"] == 1
    assert reported_late["penalty_cents"] == 240
    assert read_obligation(on_time_id)["state"] == "REPORTED"


def test_penalty_uses_the_five_percent_tier_at_thirty_one_days_late(api):
    """PRD §3.11: "When `days_late` is at least 31 and at most 90, the penalty is five percent, rounded half up."
    PRD §3.11: "The boundaries are pinned: 30 days late is still tier one at two percent, and 31 days late is tier two at five percent; 90 days late is still tier two, and 91 days late is tier three at ten percent."
    PRD §3.11: "The officer supplies a `report_reference` — the reference string the Medicare contractor issued — and the service stamps `reported_at` from the logical clock and stores that reference."

    Design: Corner/calculations/medicare_penalty_uses_tier_two_rate_at_thirty_one_days_late
    """
    scenario = setup_attributed_credit(
        payer_type="MEDICARE", payer_code="MCR", account_number="ACCT-PT1",
        financial_class="INPATIENT", payment_source="PAYER",
    )
    obligation_id = find_obligation_for_credit_balance(
        scenario["credit_balance"]["id"]
    )["id"]

    set_clock("2026-11-14T00:00:00Z")
    run_ops_checkpoint(COMPLIANCE)
    reported = report_obligation(obligation_id, "CBR-TIER2-1")

    assert reported["days_elapsed"] == 91
    assert reported["days_late"] == 31
    assert reported["penalty_cents"] == 600
    assert reported["state"] == "REPORTED_LATE"
    assert reported["report_reference"] == "CBR-TIER2-1"
    assert_instant_equals(
        reported["reported_at"], "2026-11-14T00:00:00Z", "reported_at"
    )

    credit_balance = read_credit_balance(scenario["credit_balance"]["id"])
    assert credit_balance["aging_days"] == 91
    assert credit_balance["aging_bucket"] == "D91_180"


def test_write_off_is_blocked_by_an_open_obligation_then_by_the_de_minimis_ceiling(api):
    """PRD §3.4: "And no Medicare obligation on that credit balance may still be unresolved: if one sits in `OPEN` or `LATE`, the write-off is refused with `ERR_MEDICARE_OBLIGATION_OPEN`, because a federal overpayment cannot be made to disappear by an internal accounting entry."
    PRD §3.4: "The outstanding credit must be small: `outstanding_cents` must be at most 1,000 cents — ten dollars — or the attempt fails with `ERR_WRITE_OFF_LIMIT_EXCEEDED`."
    PRD §2.8: "20. No Medicare obligation on the credit balance is `OPEN` or `LATE` when a write-off is attempted — `ERR_MEDICARE_OBLIGATION_OPEN`."

    Design: Corner/validations/write_off_rejected_over_limit_and_while_medicare_obligation_open
    """
    scenario = setup_attributed_credit(
        payer_type="MEDICARE", payer_code="MCR", account_number="ACCT-WL1",
        financial_class="INPATIENT", payment_source="PAYER",
    )
    credit_balance_id = scenario["credit_balance"]["id"]
    obligation_id = find_obligation_for_credit_balance(credit_balance_id)["id"]

    blocked_by_obligation = api.write_off_credit_balance(
        credit_balance_id, {"reason_code": "DE_MINIMIS"}, COMPLIANCE
    )
    validate_error(blocked_by_obligation, ApiErrorId.ERR_MEDICARE_OBLIGATION_OPEN.value)

    reported = validate_success(
        api.report_medicare_obligation(
            obligation_id, {"report_reference": "CBR-WL1"}, COMPLIANCE
        )
    )
    assert reported["state"] == "REPORTED"

    blocked_by_ceiling = api.write_off_credit_balance(
        credit_balance_id, {"reason_code": "DE_MINIMIS"}, COMPLIANCE
    )
    validate_error(blocked_by_ceiling, ApiErrorId.ERR_WRITE_OFF_LIMIT_EXCEEDED.value)

    assert read_credit_balance(credit_balance_id)["status"] == "ATTRIBUTED"
    assert read_account(scenario["account"]["id"])["credit_balance_cents"] == 12_000


def test_second_self_report_and_second_finalize_both_report_invalid_state(api):
    """PRD §3.11: "An obligation that has already been reported, or that has already been satisfied in any manner, cannot be reported again and is refused with `ERR_OBLIGATION_INVALID_STATE`."
    PRD §3.13: "Finalising a report moves it `DRAFT → FINALIZED`, freezing every computed total so the figures can never be regenerated; a report already `FINALIZED` refuses the call with `ERR_REPORT_INVALID_STATE`."

    Design: Corner/errors/obligation_and_report_second_action_returns_invalid_state_errors
    """
    scenario = setup_attributed_credit(
        payer_type="MEDICARE", payer_code="MCR", account_number="ACCT-OR1",
        financial_class="INPATIENT", payment_source="PAYER",
    )
    credit_balance_id = scenario["credit_balance"]["id"]
    obligation_id = find_obligation_for_credit_balance(credit_balance_id)["id"]

    set_clock("2026-09-01T00:00:00Z")
    report_obligation(obligation_id, "CBR-OR1")
    report = validate_success(
        api.create_compliance_report(
            create_compliance_report_payload(
                "CREDIT_BALANCE_LIABILITY", "ALL", "2026-08-01T00:00:00Z",
                "2026-08-16T00:00:00Z", "2026-09-01T00:00:00Z",
            ),
            COMPLIANCE,
        ),
        201,
    )
    finalized = validate_success(
        api.finalize_compliance_report(report["id"], {}, COMPLIANCE)
    )
    assert finalized["state"] == "FINALIZED"

    validate_error(
        api.report_medicare_obligation(
            obligation_id, {"report_reference": "CBR-OR1-AGAIN"}, COMPLIANCE
        ),
        ApiErrorId.ERR_OBLIGATION_INVALID_STATE.value,
    )
    validate_error(
        api.finalize_compliance_report(report["id"], {}, COMPLIANCE),
        ApiErrorId.ERR_REPORT_INVALID_STATE.value,
    )

    obligation = read_obligation(obligation_id)
    assert obligation["state"] == "REPORTED"
    assert obligation["report_reference"] == "CBR-OR1"

    stored_report = read_report(report["id"])
    assert stored_report["state"] == "FINALIZED"
    assert stored_report["total_liability_cents"] == 12_000
    assert stored_report["payer_liability_cents"] == 12_000
    assert stored_report["medicare_at_risk_cents"] == 0

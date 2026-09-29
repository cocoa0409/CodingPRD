"""Multi-hop lifecycle walks and the cascades they fire.

Three families of behaviour live here, all of them about a resource driven
through more than one hop and about what those hops reach:

* the loan's cyclic collections dimension (CURRENT -> GRACE -> DELINQUENT ->
  CURRENT) under the servicing sweep and a cure payment,
* the trade-in's grade / dispute / regrade loop and its two-dispute ceiling,
* the branching underwriting decision, plus the two exhaustive cascades - the
  default declaration and the program cancellation.

Every amount is an integer count of cents. The reference financed model is
"Handset B" (retail 89,900, monthly premium 999) on a 24-month term with no down
payment: principal_cents is 89,900, the base principal component is 3,746 (the
twenty-fourth installment carries the 3,742 residual), amount_due_cents is 4,745
per installment (4,741 on the last), premium_total_cents is 23,976 and the
opening obligation_balance_cents is 113,876.
"""
from test_helpers import (
    ApiErrorId,
    CLOCK_ORIGIN,
    LATE_FEE_CENTS,
    MODEL_A,
    TECHNICIAN_USER_ID,
    TECHNICIAN_USER_ID_2,
    UNDERWRITER_USER_ID,
    activate_device,
    advance_to_dpd,
    api_client,
    assert_allocation_splits_exactly,
    assert_carrier_account,
    assert_credit_application,
    assert_delinquency_event,
    assert_device_unit,
    assert_diagnostic_report,
    assert_installment,
    assert_iso_equals,
    assert_loan_ledger_invariants,
    assert_loan_matches_schedule,
    assert_payment_posting,
    assert_payoff_quote,
    assert_trade_in,
    at_midnight,
    cancellation_payload,
    decide_application,
    decision_payload,
    declare_trade_in,
    dispute_payload,
    enroll_customer,
    loan_device_unit,
    make_associate_headers,
    make_collections_headers,
    make_customer_headers,
    make_technician_headers,
    make_underwriter_headers,
    open_upgrade_request,
    originate_loan,
    payment_payload,
    plus_days,
    post_payment,
    price_quote,
    publish_model,
    publish_target_model,
    read_carrier_accounts,
    read_customer,
    read_delinquency_events,
    read_device_model,
    read_device_unit,
    read_diagnostic_reports,
    read_installment,
    read_installments,
    read_loan,
    read_payoff_quote,
    read_trade_in,
    read_upgrade_request,
    regrade_payload,
    register_carrier_account,
    run_sweep,
    set_clock,
    setup_active_loan,
    setup_defaulted_loan,
    setup_delinquent_loan,
    setup_loan_with_paid_installments,
    setup_paid_off_loan,
    setup_trade_in_disputed,
    setup_trade_in_graded,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)


def _events_of(events, event_type):
    return [row for row in events if row["event_type"] == event_type]


# =========================================================================
# Difficulty / non_linear_state_machine / loan_delinquency_cycle
# =========================================================================
def test_delinquency_cycle_walks_current_to_grace_to_delinquent_under_sweeps():
    """Two sweeps ten and eleven days past the first due date walk the loan
    CURRENT -> GRACE -> DELINQUENT, and the 500-cent fee lands only on the
    second hop.

    PRD 3.6: "From 1 through 10 days past due inclusive — the grace period — the
    loan is `GRACE`. From 11 days past due up to but not including 90 the loan is
    `DELINQUENT`."
    PRD 3.6: "Because the delinquency threshold sits at exactly one day past the
    end of grace, a fee is assessed at 11 days past due and never at 10."

    Design: Difficulty/non_linear_state_machine/loan_delinquency_cycle_current_grace_delinquent_current
    """
    ctx = setup_active_loan()
    loan_at_origination = ctx["loan"]
    assert loan_at_origination["delinquency_state"] == "CURRENT"
    assert loan_at_origination["days_past_due"] == 0
    assert loan_at_origination["outstanding_late_fee_cents"] == 0
    assert loan_at_origination["obligation_balance_cents"] == 113876
    assert loan_at_origination["version"] == 1

    # --- hop one: ten days past due is still inside the grace window ---------
    advance_to_dpd(ctx, 10)
    grace_sweep = ctx["sweep"]
    grace_loan = ctx["loan"]
    assert grace_sweep["processed_loan_count"] == 1
    assert grace_sweep["transitioned_loan_count"] == 1
    assert grace_sweep["defaulted_loan_count"] == 0
    assert grace_sweep["late_fees_assessed_cents"] == 0
    assert grace_loan["delinquency_state"] == "GRACE"
    assert grace_loan["days_past_due"] == 10
    assert grace_loan["outstanding_late_fee_cents"] == 0
    assert grace_loan["obligation_balance_cents"] == 113876
    assert grace_loan["protection_coverage_status"] == "ACTIVE"
    assert grace_loan["status"] == "ACTIVE"
    assert grace_loan["version"] == 2
    grace_first = read_installment(ctx["loan_id"], 1)
    assert grace_first["status"] == "PAST_DUE"
    assert grace_first["late_fee_assessed"] is False
    assert grace_first["late_fee_cents"] == 0

    # --- hop two: the eleventh day is delinquency, and the fee arrives -------
    advance_to_dpd(ctx, 11)
    delinquent_sweep = ctx["sweep"]
    delinquent_loan = ctx["loan"]
    assert delinquent_sweep["processed_loan_count"] == 1
    assert delinquent_sweep["transitioned_loan_count"] == 1
    assert delinquent_sweep["defaulted_loan_count"] == 0
    assert delinquent_sweep["late_fees_assessed_cents"] == LATE_FEE_CENTS
    assert delinquent_loan["delinquency_state"] == "DELINQUENT"
    assert delinquent_loan["days_past_due"] == 11
    assert delinquent_loan["outstanding_late_fee_cents"] == 500
    assert delinquent_loan["obligation_balance_cents"] == 114376
    assert delinquent_loan["protection_coverage_status"] == "ACTIVE"
    assert delinquent_loan["status"] == "ACTIVE"
    assert delinquent_loan["version"] == 3
    assert_loan_ledger_invariants(delinquent_loan)
    delinquent_first = read_installment(ctx["loan_id"], 1)
    assert delinquent_first["status"] == "PAST_DUE"
    assert delinquent_first["late_fee_assessed"] is True
    assert delinquent_first["late_fee_cents"] == 500
    assert delinquent_first["late_fee_paid_cents"] == 0

    # --- the audit trail records both label movements plus the one fee -------
    events = read_delinquency_events(ctx["loan_id"])
    for row in events:
        assert_delinquency_event(row)
    assert len(events) == 3
    assert sorted(row["event_type"] for row in events) == [
        "DELINQUENCY_ENTERED", "GRACE_ENTERED", "LATE_FEE_ASSESSED"]
    entered_grace = _events_of(events, "GRACE_ENTERED")[0]
    assert entered_grace["from_state"] == "CURRENT"
    assert entered_grace["to_state"] == "GRACE"
    assert entered_grace["days_past_due_at_event"] == 10
    assert entered_grace["amount_cents"] == 0
    entered_delinquent = _events_of(events, "DELINQUENCY_ENTERED")[0]
    assert entered_delinquent["from_state"] == "GRACE"
    assert entered_delinquent["to_state"] == "DELINQUENT"
    assert entered_delinquent["days_past_due_at_event"] == 11
    assert entered_delinquent["amount_cents"] == 0
    fee_event = _events_of(events, "LATE_FEE_ASSESSED")[0]
    assert fee_event["from_state"] is None
    assert fee_event["to_state"] is None
    assert fee_event["amount_cents"] == 500


def test_delinquency_cure_collects_the_assessed_fee_and_returns_the_loan_to_current():
    """A single 5,245-cent posting drains the fee bucket then the arrears bucket,
    closing installment 1 and completing the cycle back to CURRENT.

    PRD 3.5: "If, after allocation, no installment of the loan is in `PAST_DUE`
    or `PARTIALLY_PAID` with a `due_date` at or before the logical clock, the loan
    is cured: `days_past_due` is set to zero and `delinquency_state` returns to
    `CURRENT`."
    PRD 3.5: "The first bucket is assessed late fees: every installment of this
    loan whose `status` is `PAST_DUE` and whose `late_fee_assessed` is true, taken
    in ascending `installment_number`, each needing its `late_fee_cents` less its
    `late_fee_paid_cents`."

    Design: Difficulty/non_linear_state_machine/loan_delinquency_cycle_current_grace_delinquent_current
    """
    ctx = setup_active_loan()
    advance_to_dpd(ctx, 10)
    advance_to_dpd(ctx, 11)
    assert ctx["loan"]["delinquency_state"] == "DELINQUENT"
    assert ctx["loan"]["outstanding_late_fee_cents"] == 500

    posting = validate_success(api_client.create_payment(
        ctx["loan_id"], payment_payload(5245), ctx["customer_headers"]), 201)
    assert_payment_posting(posting)
    assert_allocation_splits_exactly(posting)
    assert posting["posting_type"] == "PAYMENT"
    assert posting["amount_cents"] == 5245
    assert posting["allocated_late_fee_cents"] == 500
    assert posting["allocated_principal_cents"] == 3746
    assert posting["allocated_premium_cents"] == 999
    assert posting["installments_satisfied_count"] == 1
    assert posting["overpayment_cents"] == 0
    assert posting["obligation_balance_after_cents"] == 109131

    cured = read_loan(ctx["loan_id"])
    assert cured["delinquency_state"] == "CURRENT"
    assert cured["days_past_due"] == 0
    assert cured["status"] == "ACTIVE"
    assert cured["paid_installment_count"] == 1
    assert cured["paid_principal_cents"] == 3746
    assert cured["paid_premium_cents"] == 999
    assert cured["outstanding_late_fee_cents"] == 0
    assert cured["obligation_balance_cents"] == 109131
    assert cured["protection_coverage_status"] == "ACTIVE"
    assert_loan_ledger_invariants(cured)
    # origination mints version 1; two sweeps changed the loan; the posting is
    # the fourth version-advancing operation.
    assert cured["version"] == 4

    installments = read_installments(ctx["loan_id"])
    assert_loan_matches_schedule(cured, installments)
    first = installments[0]
    assert first["status"] == "PAID"
    assert first["paid_amount_cents"] == 4745
    assert first["late_fee_assessed"] is True
    assert first["late_fee_cents"] == 500
    assert first["late_fee_paid_cents"] == 500
    assert installments[1]["status"] == "SCHEDULED"

    events = read_delinquency_events(ctx["loan_id"])
    assert len(events) == 4
    assert sorted(row["event_type"] for row in events) == [
        "CURED", "DELINQUENCY_ENTERED", "GRACE_ENTERED", "LATE_FEE_ASSESSED"]
    assert events[0]["event_type"] == "GRACE_ENTERED"
    assert events[-1]["event_type"] == "CURED"
    cure_event = events[-1]
    assert cure_event["from_state"] == "DELINQUENT"
    assert cure_event["to_state"] == "CURRENT"
    assert cure_event["days_past_due_at_event"] == 0
    assert cure_event["amount_cents"] == 0


def test_late_fee_is_assessed_only_once_per_installment_across_repeated_sweeps():
    """A second sweep one day deeper ages the loan further but charges nothing
    extra, because the installment's late_fee_assessed is already true.

    PRD 3.6: "Each installment can be charged at most once; the fee is not
    re-assessed after a reversal re-opens an installment."

    Design: Difficulty/non_linear_state_machine/loan_delinquency_cycle_current_grace_delinquent_current
    """
    ctx = setup_delinquent_loan()
    first_sweep = ctx["sweep"]
    assert first_sweep["late_fees_assessed_cents"] == 500
    assert ctx["loan"]["delinquency_state"] == "DELINQUENT"
    assert ctx["loan"]["days_past_due"] == 11
    assert ctx["loan"]["outstanding_late_fee_cents"] == 500
    assert ctx["loan"]["version"] == 2
    events_after_first = read_delinquency_events(ctx["loan_id"])
    assert len(events_after_first) == 2
    assert sorted(row["event_type"] for row in events_after_first) == [
        "DELINQUENCY_ENTERED", "LATE_FEE_ASSESSED"]
    # The grace label is not a prerequisite: the movement is CURRENT -> DELINQUENT.
    direct = _events_of(events_after_first, "DELINQUENCY_ENTERED")[0]
    assert direct["from_state"] == "CURRENT"
    assert direct["to_state"] == "DELINQUENT"

    advance_to_dpd(ctx, 12)
    second_sweep = ctx["sweep"]
    aged = ctx["loan"]
    assert second_sweep["processed_loan_count"] == 1
    assert second_sweep["late_fees_assessed_cents"] == 0
    assert second_sweep["transitioned_loan_count"] == 0
    assert second_sweep["defaulted_loan_count"] == 0
    assert aged["days_past_due"] == 12
    assert aged["delinquency_state"] == "DELINQUENT"
    assert aged["outstanding_late_fee_cents"] == 500
    assert aged["obligation_balance_cents"] == 114376
    # days_past_due changed, so the sweep still advances the loan's version.
    assert aged["version"] == 3
    still_one_fee = read_installment(ctx["loan_id"], 1)
    assert still_one_fee["late_fee_assessed"] is True
    assert still_one_fee["late_fee_cents"] == 500
    assert len(read_delinquency_events(ctx["loan_id"])) == 2


# =========================================================================
# Difficulty / non_linear_state_machine / trade_in_grade_dispute_regrade_cycle
# =========================================================================
def test_regrade_after_dispute_recomputes_the_credit_from_the_newest_report_only():
    """A SCRATCHED / 78-percent grading fixes the credit at 31,750; disputing it
    and regrading PRISTINE / 95 percent lifts it to the full 45,000 base, and the
    superseded report is left untouched.

    PRD 3.9: "A new `DiagnosticReport` is appended with `sequence_no` set to the
    trade-in's `latest_report_sequence_no` plus one, `report_type` `REGRADE`, and
    `technician_user_id` set to the acting `X-User-ID`; it supersedes the prior
    report, and from that moment the graded computation reads only this newest
    report — superseded reports are ignored entirely."
    PRD 3.9: "`credit_variance_cents` is then `credit_final_cents` less
    `credit_estimate_cents`, and it goes negative whenever grading came in below
    the customer's own declaration — which is the whole point of grading, since
    the declared condition is ignored entirely and an `EXCELLENT` declaration
    cannot lift a cracked-screen handset above `FAIR`."

    Design: Difficulty/non_linear_state_machine/trade_in_grade_dispute_regrade_cycle
    """
    ctx = setup_trade_in_graded(
        declared_condition="GOOD",
        measurements={"screen_grade": "SCRATCHED", "battery_health_pct": 78})
    trade_in = ctx["trade_in"]
    assert_trade_in(trade_in)
    # 45,000 base at the GOOD declaration multiplier of 8,500 bps.
    assert trade_in["credit_estimate_cents"] == 38250
    # 45,000 * 8,500 / 10,000 = 38,250 rounded first, then 2,500 + 4,000 removed.
    assert trade_in["status"] == "GRADED"
    assert trade_in["graded_condition"] == "GOOD"
    assert trade_in["diagnostic_result"] == "PASS"
    assert trade_in["credit_final_cents"] == 31750
    assert trade_in["credit_variance_cents"] == -6500
    assert trade_in["latest_report_sequence_no"] == 1
    assert trade_in["dispute_count"] == 0
    request_after_grading = read_upgrade_request(ctx["upgrade_request_id"])
    assert request_after_grading["status"] == "TRADE_IN_GRADED"
    assert request_after_grading["trade_in_credit_projection_cents"] == 31750

    # --- hop two: the customer disputes the bench's reading ------------------
    disputed = validate_success(api_client.dispute_trade_in(
        ctx["trade_in_id"], dispute_payload("Screen was intact at hand-over"),
        ctx["customer_headers"]))
    assert disputed["status"] == "DISPUTED"
    assert disputed["dispute_count"] == 1
    assert disputed["dispute_reason"] == "Screen was intact at hand-over"
    # The disputed grading figures survive the movement untouched.
    assert disputed["credit_final_cents"] == 31750
    assert disputed["latest_report_sequence_no"] == 1

    # --- hop three: a second technician regrades and the money is rebuilt -----
    regrade = validate_success(api_client.regrade_trade_in(
        ctx["trade_in_id"],
        regrade_payload(screen_grade="PRISTINE", battery_health_pct=95),
        make_technician_headers(TECHNICIAN_USER_ID_2)), 201)
    assert_diagnostic_report(regrade)
    assert regrade["sequence_no"] == 2
    assert regrade["report_type"] == "REGRADE"
    assert regrade["technician_user_id"] == TECHNICIAN_USER_ID_2
    assert regrade["override_reason"] == "Bench re-inspection after dispute"
    assert regrade["derived_condition"] == "EXCELLENT"
    assert regrade["diagnostic_result"] == "PASS"
    assert regrade["condition_multiplier_bps"] == 10000
    assert regrade["screen_deduction_cents"] == 0
    assert regrade["battery_deduction_cents"] == 0
    assert regrade["computed_credit_cents"] == 45000

    regraded = read_trade_in(ctx["trade_in_id"])
    assert regraded["status"] == "GRADED"
    assert regraded["graded_condition"] == "EXCELLENT"
    assert regraded["diagnostic_result"] == "PASS"
    assert regraded["credit_final_cents"] == 45000
    assert regraded["credit_variance_cents"] == 6750
    assert regraded["latest_report_sequence_no"] == 2
    assert regraded["dispute_count"] == 1
    assert regraded["credit_estimate_cents"] == 38250
    request_after_regrade = read_upgrade_request(ctx["upgrade_request_id"])
    assert request_after_regrade["trade_in_credit_projection_cents"] == 45000

    # --- the report chain: oldest first, and the superseded row is frozen ----
    rows, meta = validate_paginated(api_client.list_diagnostic_reports(
        ctx["trade_in_id"], make_technician_headers(TECHNICIAN_USER_ID_2),
        params={"limit": 10}))
    assert meta["total_count"] == 2
    assert [row["sequence_no"] for row in rows] == [1, 2]
    for row in rows:
        assert_diagnostic_report(row)
    initial = rows[0]
    assert initial["report_type"] == "INITIAL"
    assert initial["technician_user_id"] == TECHNICIAN_USER_ID
    assert initial["override_reason"] is None
    assert initial["screen_grade"] == "SCRATCHED"
    assert initial["battery_health_pct"] == 78
    assert initial["derived_condition"] == "GOOD"
    assert initial["condition_multiplier_bps"] == 8500
    assert initial["screen_deduction_cents"] == 2500
    assert initial["battery_deduction_cents"] == 4000
    assert initial["computed_credit_cents"] == 31750


def test_dispute_and_regrade_loop_runs_twice_then_the_ceiling_refuses_a_third():
    """Two full dispute / regrade turns leave dispute_count at 2 and a third
    dispute is refused outright.

    PRD 3.9: "A third dispute on the same trade-in — one raised when
    `dispute_count` has already reached 2 — is refused with
    `ERR_DISPUTE_LIMIT_REACHED`."
    PRD 3.9: "Because the dispute ceiling is two, the dispute-and-regrade loop can
    run at most twice; after the second regrade `dispute_count` stands at 2 and no
    further dispute is admissible."

    Design: Difficulty/non_linear_state_machine/trade_in_grade_dispute_regrade_cycle
    """
    ctx = setup_trade_in_disputed()
    assert ctx["trade_in"]["status"] == "DISPUTED"
    assert ctx["trade_in"]["dispute_count"] == 1

    # --- first regrade: u-tech-2 may override u-tech-1's initial report ------
    first_regrade = validate_success(api_client.regrade_trade_in(
        ctx["trade_in_id"], regrade_payload(),
        make_technician_headers(TECHNICIAN_USER_ID_2)), 201)
    assert first_regrade["sequence_no"] == 2
    assert first_regrade["technician_user_id"] == TECHNICIAN_USER_ID_2
    after_first_regrade = read_trade_in(ctx["trade_in_id"])
    assert after_first_regrade["status"] == "GRADED"
    assert after_first_regrade["dispute_count"] == 1
    assert after_first_regrade["latest_report_sequence_no"] == 2

    # --- second dispute takes the counter to the ceiling --------------------
    second_dispute = validate_success(api_client.dispute_trade_in(
        ctx["trade_in_id"], dispute_payload("Battery reading still looks wrong"),
        ctx["customer_headers"]))
    assert second_dispute["status"] == "DISPUTED"
    assert second_dispute["dispute_count"] == 2
    assert second_dispute["dispute_reason"] == "Battery reading still looks wrong"

    # --- second regrade: u-tech-1 differs from the newest report's technician -
    second_regrade = validate_success(api_client.regrade_trade_in(
        ctx["trade_in_id"], regrade_payload(),
        make_technician_headers(TECHNICIAN_USER_ID)), 201)
    assert second_regrade["sequence_no"] == 3
    assert second_regrade["report_type"] == "REGRADE"
    assert second_regrade["technician_user_id"] == TECHNICIAN_USER_ID
    after_second_regrade = read_trade_in(ctx["trade_in_id"])
    assert after_second_regrade["status"] == "GRADED"
    assert after_second_regrade["dispute_count"] == 2
    assert after_second_regrade["latest_report_sequence_no"] == 3

    # --- a third dispute is inadmissible even though the state would allow it -
    validate_error(api_client.dispute_trade_in(
        ctx["trade_in_id"], dispute_payload("One more look please"),
        ctx["customer_headers"]), ApiErrorId.ERR_DISPUTE_LIMIT_REACHED.value)

    unchanged = read_trade_in(ctx["trade_in_id"])
    assert unchanged["status"] == "GRADED"
    assert unchanged["dispute_count"] == 2
    assert unchanged["dispute_reason"] == "Battery reading still looks wrong"
    assert unchanged["latest_report_sequence_no"] == 3
    reports = read_diagnostic_reports(ctx["trade_in_id"])
    assert [row["sequence_no"] for row in reports] == [1, 2, 3]


# =========================================================================
# Difficulty / non_linear_state_machine / credit_application_branching
# =========================================================================
def test_prime_band_approves_the_whole_requested_principal_within_limit():
    """A PRIME decision on an 89,900-cent request lands inside the 250,000-cent
    limit, so the whole principal is approved with no conditional down payment.

    PRD 3.2: "When exposure is less than or equal to the credit limit, the
    application advances `SUBMITTED → APPROVED`:
    `conditional_down_payment_required_cents` is set to zero,
    `approved_principal_cents` is set to the full `requested_principal_cents`, and
    `decision_reason` records the token `WITHIN_LIMIT`."
    PRD 3.2: "The band resolves to a program credit limit — 250,000 cents for
    `PRIME`, 150,000 cents for `NEAR_PRIME`, and 80,000 cents for `SUBPRIME` — and
    that figure is written to the application's `credit_limit_cents`."

    Design: Difficulty/non_linear_state_machine/credit_application_branching_conditional_vs_approved
    """
    model = publish_model()
    customer = enroll_customer()

    submitted = submit_application(customer["id"], model["id"], requested_term_months=24)
    assert_credit_application(submitted)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["requested_principal_cents"] == 89900
    assert submitted["declared_down_payment_cents"] == 0
    assert submitted["credit_score_band"] is None
    assert submitted["decision_reason"] is None
    assert submitted["underwriter_user_id"] is None
    assert submitted["decided_at"] is None
    assert submitted["credit_limit_cents"] == 0
    assert submitted["exposure_at_decision_cents"] == 0
    assert submitted["approved_principal_cents"] == 0
    assert submitted["conditional_down_payment_required_cents"] == 0

    decided = validate_success(api_client.decide_credit_application(
        submitted["id"], decision_payload("PRIME"),
        make_underwriter_headers(UNDERWRITER_USER_ID)))
    assert_credit_application(decided)
    assert decided["status"] == "APPROVED"
    assert decided["credit_score_band"] == "PRIME"
    assert decided["credit_limit_cents"] == 250000
    # exposure is the customer's zero outstanding principal plus 89,900.
    assert decided["exposure_at_decision_cents"] == 89900
    assert decided["approved_principal_cents"] == 89900
    assert decided["conditional_down_payment_required_cents"] == 0
    assert decided["decision_reason"] == "WITHIN_LIMIT"
    assert decided["underwriter_user_id"] == UNDERWRITER_USER_ID
    assert_iso_equals(decided["decided_at"], CLOCK_ORIGIN, "decided_at")

    # The decision is written back onto the customer.
    after = read_customer(customer["id"])
    assert after["credit_score_band"] == "PRIME"
    assert after["credit_limit_cents"] == 250000
    assert after["status"] == "ACTIVE"
    assert after["outstanding_principal_cents"] == 0
    assert after["open_loan_count"] == 0


def test_subprime_band_takes_the_conditional_branch_and_governs_the_customer():
    """The same 89,900-cent request decided SUBPRIME clears the 80,000 limit but
    stays inside the 12,500-bps conditional ceiling of 100,000, so it lands
    CONDITIONAL_APPROVED owing 9,900 in cash — and that later decision governs the
    customer's headroom.

    PRD 3.2: "When exposure is above the credit limit but still less than or equal
    to the conditional ceiling, the application advances
    `SUBMITTED → CONDITIONAL_APPROVED`:
    `conditional_down_payment_required_cents` is set to exposure minus the credit
    limit — the cash the applicant must find to bring themselves back inside the
    limit — `approved_principal_cents` is set to `requested_principal_cents` less
    that required amount, and `decision_reason` records
    `CONDITIONAL_DOWN_PAYMENT_REQUIRED`."
    PRD 3.2: "A conditional ceiling is then formed by taking 12,500 basis points of
    the credit limit — that is, one and a quarter times it — with the result
    rounded half up to whole cents."

    Design: Difficulty/non_linear_state_machine/credit_application_branching_conditional_vs_approved
    """
    prime_model = publish_model()
    subprime_model = publish_model()
    customer = enroll_customer()
    customer_id = customer["id"]

    # --- the PRIME arm decides first, so the customer sits at 250,000 --------
    prime_application = submit_application(customer_id, prime_model["id"],
                                           requested_term_months=24)
    prime_decided = decide_application(prime_application["id"], "PRIME")
    assert prime_decided["status"] == "APPROVED"
    assert prime_decided["decision_reason"] == "WITHIN_LIMIT"
    mid = read_customer(customer_id)
    assert mid["credit_score_band"] == "PRIME"
    assert mid["credit_limit_cents"] == 250000

    # --- the SUBPRIME arm on the same applicant branches the other way -------
    subprime_application = submit_application(customer_id, subprime_model["id"],
                                              requested_term_months=24)
    assert subprime_application["requested_principal_cents"] == 89900

    decided = validate_success(api_client.decide_credit_application(
        subprime_application["id"], decision_payload("SUBPRIME"),
        make_underwriter_headers(UNDERWRITER_USER_ID)))
    assert_credit_application(decided)
    assert decided["status"] == "CONDITIONAL_APPROVED"
    assert decided["credit_score_band"] == "SUBPRIME"
    assert decided["credit_limit_cents"] == 80000
    assert decided["exposure_at_decision_cents"] == 89900
    # 89,900 exposure less the 80,000 limit; 80,000 * 12,500 / 10,000 = 100,000
    # is the conditional ceiling the exposure still fits inside.
    assert decided["conditional_down_payment_required_cents"] == 9900
    assert decided["approved_principal_cents"] == 80000
    assert decided["decision_reason"] == "CONDITIONAL_DOWN_PAYMENT_REQUIRED"
    assert decided["underwriter_user_id"] == UNDERWRITER_USER_ID
    assert_iso_equals(decided["decided_at"], CLOCK_ORIGIN, "decided_at")

    # The most recent decision always governs, so the customer drops to SUBPRIME.
    after = read_customer(customer_id)
    assert after["credit_score_band"] == "SUBPRIME"
    assert after["credit_limit_cents"] == 80000
    assert after["status"] == "ACTIVE"

    # The earlier APPROVED application is untouched by the later decision.
    still_approved = validate_success(api_client.get_credit_application(
        prime_application["id"], make_associate_headers()))
    assert still_approved["status"] == "APPROVED"
    assert still_approved["credit_score_band"] == "PRIME"
    assert still_approved["credit_limit_cents"] == 250000
    assert still_approved["approved_principal_cents"] == 89900


def test_exposure_above_the_conditional_ceiling_declines_the_application():
    """A 119,900-cent request decided SUBPRIME blows through the 100,000-cent
    conditional ceiling, so the third branch fires and nothing is approved.

    PRD 3.2: "When exposure exceeds the conditional ceiling, the application
    advances `SUBMITTED → DECLINED`: both
    `conditional_down_payment_required_cents` and `approved_principal_cents` are
    set to zero and `decision_reason` records
    `EXPOSURE_ABOVE_CONDITIONAL_BAND`."

    Design: Difficulty/non_linear_state_machine/credit_application_branching_conditional_vs_approved
    """
    expensive_model = publish_target_model()
    assert expensive_model["retail_price_cents"] == MODEL_A["retail_price_cents"]
    customer = enroll_customer()

    submitted = submit_application(customer["id"], expensive_model["id"],
                                   requested_term_months=24)
    assert submitted["requested_principal_cents"] == 119900

    decided = validate_success(api_client.decide_credit_application(
        submitted["id"], decision_payload("SUBPRIME"),
        make_underwriter_headers(UNDERWRITER_USER_ID)))
    assert decided["status"] == "DECLINED"
    assert decided["credit_score_band"] == "SUBPRIME"
    assert decided["credit_limit_cents"] == 80000
    assert decided["exposure_at_decision_cents"] == 119900
    assert decided["conditional_down_payment_required_cents"] == 0
    assert decided["approved_principal_cents"] == 0
    assert decided["decision_reason"] == "EXPOSURE_ABOVE_CONDITIONAL_BAND"
    assert decided["underwriter_user_id"] == UNDERWRITER_USER_ID
    assert_iso_equals(decided["decided_at"], CLOCK_ORIGIN, "decided_at")

    # Even a declined decision writes the band and limit back onto the customer.
    after = read_customer(customer["id"])
    assert after["credit_score_band"] == "SUBPRIME"
    assert after["credit_limit_cents"] == 80000


# =========================================================================
# Difficulty / transitive_cascade / default_declaration_cascade
# =========================================================================
def _setup_default_lock_cascade():
    """Compose the reach of a default: one borrower, two loans and everything the
    lock is supposed to knock over.

    No fixture builds this shape, so it is assembled here from Tier 0 wrappers.
    Loan Y (Handset G, 60,000 principal, 3,000 per installment) is paid 18
    installments deep and carries a live upgrade reservation on Handset A plus a
    declared trade-in. Loan X (Handset B) is originated 330 days later and left
    unpaid so that one sweep, 90 days after its first due date, declares it in
    default while loan Y is still perfectly CURRENT.
    """
    model_g = publish_model(retail_price_cents=60000,
                            monthly_protection_premium_cents=500,
                            trade_in_base_credit_cents=20000,
                            display_name="Handset G")
    model_b = publish_model()
    model_a = publish_target_model()
    customer = enroll_customer()
    customer_id = customer["id"]
    customer_headers = make_customer_headers(customer_id)

    # --- loan Y: the healthy sibling, 18 of 24 installments retired ----------
    application_y = submit_application(customer_id, model_g["id"], requested_term_months=24)
    application_y = decide_application(application_y["id"], "PRIME")
    loan_y = originate_loan(application_y["id"], down_payment_cents=0)
    device_y = loan_device_unit(loan_y["id"])
    carrier = register_carrier_account(customer_id)
    device_y = activate_device(device_y["id"], carrier["id"])
    posting_y = post_payment(loan_y["id"], 54000, customer_id=customer_id)
    assert posting_y["installments_satisfied_count"] == 18
    assert posting_y["overpayment_cents"] == 0

    # --- loan X: originated once loan Y's upgrade window has opened ----------
    set_clock(at_midnight(loan_y["upgrade_window_opens_at"]))
    application_x = submit_application(customer_id, model_b["id"], requested_term_months=24)
    application_x = decide_application(application_x["id"], "PRIME")
    loan_x = originate_loan(application_x["id"], down_payment_cents=0)
    first_due_x = read_installment(loan_x["id"], 1)["due_date"]

    # --- the reservation and the trade-in the lock will have to unwind -------
    # The window is staged to straddle the default date, so the sweep cannot
    # expire this request for FULFILLMENT_WINDOW_ELAPSED instead.
    window_start = at_midnight(plus_days(first_due_x, 88))
    upgrade_request = open_upgrade_request(loan_y["id"], model_a["id"], window_start,
                                          customer_id=customer_id)
    trade_in = declare_trade_in(upgrade_request["id"], device_y["id"], "GOOD",
                               customer_id=customer_id)

    # --- two live applications the lock must void, on top of two ORIGINATED --
    application_approved = submit_application(customer_id, model_a["id"],
                                             requested_term_months=24)
    application_approved = decide_application(application_approved["id"], "PRIME")
    application_submitted = submit_application(customer_id, model_a["id"],
                                              requested_term_months=24)

    loan_y_before = read_loan(loan_y["id"])
    model_a_before = read_device_model(model_a["id"])
    assert loan_y_before["upgrade_hold_flag"] is True
    assert loan_y_before["delinquency_state"] == "CURRENT"
    assert loan_y_before["paid_installment_count"] == 18
    # origination, the posting and the upgrade request each advanced the version.
    assert loan_y_before["version"] == 3
    assert model_a_before["reserved_slot_count"] == 1
    assert upgrade_request["status"] == "ELIGIBILITY_PASSED"
    assert application_approved["status"] == "APPROVED"
    assert application_submitted["status"] == "SUBMITTED"
    assert trade_in["status"] == "DECLARED"
    assert read_device_unit(device_y["id"])["possession_status"] == "RETURN_PENDING"

    # --- the trigger: one sweep at 90 days past loan X's first due date ------
    default_clock = plus_days(first_due_x, 90)
    set_clock(default_clock)
    sweep = run_sweep()

    return {
        "customer_id": customer_id,
        "customer_headers": customer_headers,
        "model_a": model_a,
        "carrier": carrier,
        "loan_x": loan_x,
        "loan_y": loan_y,
        "device_y": device_y,
        "upgrade_request": upgrade_request,
        "trade_in": trade_in,
        "application_x": application_x,
        "application_y": application_y,
        "application_approved": application_approved,
        "application_submitted": application_submitted,
        "sweep": sweep,
        "default_clock": default_clock,
    }


def test_default_declaration_suspends_coverage_and_locks_the_borrower():
    """Reaching 90 days past due suspends the protection cover, leaves the loan
    ACTIVE, locks the customer with reason DEFAULTED_LOAN and records the strike.

    PRD 3.6: "On the loan itself, `protection_coverage_status` moves from `ACTIVE`
    to `SUSPENDED` — the bundled device protection stops covering the handset while
    the account is in default — and a `DEFAULT_DECLARED` event is appended."
    PRD 3.6: "Then: **first**, because the loan reached `DEFAULT`, the borrower's
    `status` becomes `FINANCING_LOCKED` with `financing_lock_reason` set to
    `DEFAULTED_LOAN` and `financing_locked_at` stamped from the logical clock, the
    customer's `default_strike_count` is increased by one, and a
    `FINANCING_LOCK_APPLIED` event is appended."
    PRD 2.8: "A loan in `DEFAULT` is still `ACTIVE`; a loan that reached
    `PAID_OFF` keeps whatever `delinquency_state` label it last held, because only
    two operations ever write that field — posting money to the loan, and the
    servicing sweep."

    Design: Difficulty/transitive_cascade/default_declaration_cascade_customer_lock_apps_void_upgrade_expire
    """
    ctx = setup_defaulted_loan()
    sweep = ctx["sweep"]
    loan = ctx["loan"]
    assert sweep["processed_loan_count"] == 1
    assert sweep["transitioned_loan_count"] == 1
    assert sweep["defaulted_loan_count"] == 1
    # Installments 1, 2 and 3 are all past grace at 90 days past the first due date.
    assert sweep["late_fees_assessed_cents"] == 1500

    assert loan["delinquency_state"] == "DEFAULT"
    assert loan["days_past_due"] == 90
    assert loan["protection_coverage_status"] == "SUSPENDED"
    assert loan["status"] == "ACTIVE"
    assert loan["closure_reason"] is None
    assert loan["outstanding_late_fee_cents"] == 1500
    assert loan["obligation_balance_cents"] == 115376
    assert loan["paid_installment_count"] == 0
    assert_loan_ledger_invariants(loan)
    assert loan["version"] == 2

    # --- link one: the borrower is locked and the strike is permanent --------
    customer = read_customer(ctx["customer_id"])
    assert customer["status"] == "FINANCING_LOCKED"
    assert customer["financing_lock_reason"] == "DEFAULTED_LOAN"
    assert customer["default_strike_count"] == 1
    default_moment = read_installment(ctx["loan_id"], 1)["due_date"]
    assert_iso_equals(customer["financing_locked_at"],
                      plus_days(default_moment, 90), "financing_locked_at")
    assert customer["open_loan_count"] == 1
    assert customer["outstanding_principal_cents"] == 89900

    events = read_delinquency_events(ctx["loan_id"])
    for row in events:
        assert_delinquency_event(row)
    assert len(events) == 5
    declared = _events_of(events, "DEFAULT_DECLARED")
    assert len(declared) == 1
    assert declared[0]["from_state"] == "CURRENT"
    assert declared[0]["to_state"] == "DEFAULT"
    assert declared[0]["days_past_due_at_event"] == 90
    assert declared[0]["amount_cents"] == 0
    locked = _events_of(events, "FINANCING_LOCK_APPLIED")
    assert len(locked) == 1
    assert locked[0]["from_state"] is None
    assert locked[0]["to_state"] is None
    assert locked[0]["amount_cents"] == 0
    fees = _events_of(events, "LATE_FEE_ASSESSED")
    assert len(fees) == 3
    assert [row["amount_cents"] for row in fees] == [500, 500, 500]

    for number in (1, 2, 3):
        row = read_installment(ctx["loan_id"], number)
        assert row["status"] == "PAST_DUE"
        assert row["late_fee_assessed"] is True
        assert row["late_fee_cents"] == 500
    untouched = read_installment(ctx["loan_id"], 4)
    assert untouched["status"] == "SCHEDULED"
    assert untouched["late_fee_assessed"] is False
    assert untouched["late_fee_cents"] == 0


def test_default_lock_voids_live_applications_and_expires_the_sibling_reservation():
    """One loan's default reaches sideways: the borrower's live applications are
    voided, their upgrade request on a wholly CURRENT sibling loan expires, the
    target model's slot is released and the sibling's hold is cleared.

    PRD 3.6: "**Second**, because the customer became `FINANCING_LOCKED`, every
    credit application of that customer sitting in `SUBMITTED`, `APPROVED` or
    `CONDITIONAL_APPROVED` is moved to `VOIDED_BY_LOCK`."
    PRD 3.6: "**Third**, again because of the lock, every upgrade request of that
    customer sitting in `ELIGIBILITY_PASSED`, `TRADE_IN_DECLARED` or
    `TRADE_IN_GRADED` is moved to `EXPIRED` with `expiry_reason` set to
    `CUSTOMER_FINANCING_LOCKED`."
    PRD 3.6: "**Fourth**, because those upgrade requests left their reserving
    states, each target model's `reserved_slot_count` is recomputed downward and
    the `upgrade_hold_flag` on each upgraded-from loan is cleared."
    PRD 3.2: "When a customer becomes financing-locked, every one of that
    customer's applications sitting in `SUBMITTED`, `APPROVED` or
    `CONDITIONAL_APPROVED` is swept to `VOIDED_BY_LOCK`, with `decision_reason`
    overwritten to the token `CUSTOMER_FINANCING_LOCKED`."

    Design: Difficulty/transitive_cascade/default_declaration_cascade_customer_lock_apps_void_upgrade_expire
    """
    ctx = _setup_default_lock_cascade()
    sweep = ctx["sweep"]
    assert sweep["processed_loan_count"] == 2
    assert sweep["defaulted_loan_count"] == 1
    assert sweep["transitioned_loan_count"] == 1
    assert sweep["late_fees_assessed_cents"] == 1500

    defaulted = read_loan(ctx["loan_x"]["id"])
    assert defaulted["delinquency_state"] == "DEFAULT"
    assert defaulted["days_past_due"] == 90
    assert defaulted["status"] == "ACTIVE"
    assert defaulted["protection_coverage_status"] == "SUSPENDED"
    assert defaulted["outstanding_late_fee_cents"] == 1500
    assert defaulted["obligation_balance_cents"] == 115376
    assert defaulted["version"] == 2

    customer = read_customer(ctx["customer_id"])
    assert customer["status"] == "FINANCING_LOCKED"
    assert customer["financing_lock_reason"] == "DEFAULTED_LOAN"
    assert customer["default_strike_count"] == 1
    assert_iso_equals(customer["financing_locked_at"], ctx["default_clock"],
                      "financing_locked_at")

    # --- link two: both live applications are swept, the two ORIGINATED are not
    voided_approved = validate_success(api_client.get_credit_application(
        ctx["application_approved"]["id"], make_associate_headers()))
    assert voided_approved["status"] == "VOIDED_BY_LOCK"
    assert voided_approved["decision_reason"] == "CUSTOMER_FINANCING_LOCKED"
    voided_submitted = validate_success(api_client.get_credit_application(
        ctx["application_submitted"]["id"], make_associate_headers()))
    assert voided_submitted["status"] == "VOIDED_BY_LOCK"
    assert voided_submitted["decision_reason"] == "CUSTOMER_FINANCING_LOCKED"
    for originated in (ctx["application_x"], ctx["application_y"]):
        row = validate_success(api_client.get_credit_application(
            originated["id"], make_associate_headers()))
        assert row["status"] == "ORIGINATED"
        assert row["decision_reason"] == "WITHIN_LIMIT"

    # --- link three: the reservation on the healthy sibling loan expires ------
    expired = read_upgrade_request(ctx["upgrade_request"]["id"])
    assert expired["status"] == "EXPIRED"
    assert expired["expiry_reason"] == "CUSTOMER_FINANCING_LOCKED"
    assert expired["loan_id"] == ctx["loan_y"]["id"]
    assert expired["new_loan_id"] is None
    assert expired["completed_at"] is None

    # --- link four: the slot is released and the sibling's hold is cleared ----
    model_a = read_device_model(ctx["model_a"]["id"])
    assert model_a["reserved_slot_count"] == 0
    healthy = read_loan(ctx["loan_y"]["id"])
    assert healthy["upgrade_hold_flag"] is False
    # The sibling loan itself is untouched by its owner's default.
    assert healthy["status"] == "ACTIVE"
    assert healthy["delinquency_state"] == "CURRENT"
    assert healthy["days_past_due"] == 0
    assert healthy["paid_installment_count"] == 18
    assert healthy["outstanding_late_fee_cents"] == 0
    assert healthy["protection_coverage_status"] == "ACTIVE"
    assert healthy["obligation_balance_cents"] == 18000
    assert_loan_ledger_invariants(healthy)
    assert len(read_delinquency_events(ctx["loan_y"]["id"])) == 0


def test_default_lock_cancels_the_trade_in_and_hands_the_handset_back():
    """The fifth link runs the trade-in backwards: the declared trade-in is
    CANCELLED and the handset's possession returns to the customer while its
    independent activation dimension and its carrier line stay exactly as they
    were.

    PRD 3.6: "**Fifth**, because those upgrade requests expired, each of their
    trade-ins sitting in `DECLARED`, `RECEIVED`, `GRADED` or `DISPUTED` is moved to
    `CANCELLED` and the handset each referenced has its `possession_status`
    returned to `WITH_CUSTOMER`."

    Design: Difficulty/transitive_cascade/default_declaration_cascade_customer_lock_apps_void_upgrade_expire
    """
    ctx = _setup_default_lock_cascade()

    cancelled = read_trade_in(ctx["trade_in"]["id"])
    assert_trade_in(cancelled)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["upgrade_request_id"] == ctx["upgrade_request"]["id"]
    assert cancelled["device_unit_id"] == ctx["device_y"]["id"]
    # 20,000 base at the GOOD declaration multiplier; the estimate is not rewritten.
    assert cancelled["credit_estimate_cents"] == 17000
    assert cancelled["graded_condition"] is None
    assert cancelled["credit_final_cents"] is None
    assert cancelled["settled_at"] is None

    handset = read_device_unit(ctx["device_y"]["id"])
    assert handset["possession_status"] == "WITH_CUSTOMER"
    # The three DeviceUnit dimensions move independently: the cascade touches
    # possession only.
    assert handset["activation_status"] == "ACTIVATED"
    assert handset["unlock_status"] == "LOCKED"

    carrier_accounts = read_carrier_accounts(ctx["customer_id"])
    assert len(carrier_accounts) == 1
    assert carrier_accounts[0]["activation_state"] == "ACTIVATED"
    assert carrier_accounts[0]["active_device_imei"] == handset["imei"]


# =========================================================================
# Difficulty / transitive_cascade / program_cancellation_cascade
# =========================================================================
def test_program_cancellation_closes_the_loan_and_voids_the_rest_of_the_ladder():
    """Settling an EARLY_CANCELLATION quote to the cent on a loan 12 installments
    deep retires the loan, zeroes its fee, terminates the cover and voids the
    twelve installments that were still to come.

    PRD 3.7: "`premium_rebate_cents` is then 9,000 basis points of that, or 90
    percent, rounded half up to whole cents; the withheld 10 percent is the
    program's cancellation retention haircut."
    PRD 3.7: "`total_payoff_cents` is then `remaining_principal_cents` plus
    `outstanding_late_fee_cents` plus `admin_fee_cents`, less
    `premium_rebate_cents`."
    PRD 3.7: "Every installment still in `SCHEDULED`, `PAST_DUE` or
    `PARTIALLY_PAID` is driven to `VOIDED` with `void_reason` set to `LOAN_CLOSED`;
    where a voided installment carried an assessed `late_fee_cents`, that fee was
    already folded into the settled payoff total, which is precisely why the loan's
    `outstanding_late_fee_cents` can be zeroed rather than written off."

    Design: Difficulty/transitive_cascade/program_cancellation_cascade_loan_payoff_device_unlock_carrier_port_eligible
    """
    ctx = setup_loan_with_paid_installments(12, activate=True)
    loan_before = read_loan(ctx["loan_id"])
    assert loan_before["paid_installment_count"] == 12
    assert loan_before["paid_principal_cents"] == 44952
    assert loan_before["paid_premium_cents"] == 11988

    quote = price_quote(ctx["loan_id"], "EARLY_CANCELLATION",
                        customer_id=ctx["customer_id"])
    assert_payoff_quote(quote)
    assert quote["quote_type"] == "EARLY_CANCELLATION"
    assert quote["status"] == "ISSUED"
    assert quote["consumed_at"] is None
    assert quote["paid_installment_count_at_quote"] == 12
    # 89,900 principal less the 44,952 already retired.
    assert quote["remaining_principal_cents"] == 44948
    assert quote["outstanding_late_fee_cents"] == 0
    # 23,976 total premium less 11,988 already earned, straight-line.
    assert quote["unearned_premium_cents"] == 11988
    # 11,988 * 9,000 / 10,000 = 10,789.2, rounded half up.
    assert quote["premium_rebate_cents"] == 10789
    assert quote["admin_fee_cents"] == 2500
    assert quote["total_payoff_cents"] == 36659
    assert quote["past_due_amount_cents"] == 0
    assert_iso_equals(quote["issued_at"], CLOCK_ORIGIN, "issued_at")
    assert_iso_equals(quote["expires_at"], plus_days(CLOCK_ORIGIN, 7), "expires_at")

    closed = validate_success(api_client.cancel_loan(
        ctx["loan_id"], cancellation_payload(quote["id"], 36659),
        ctx["customer_headers"]))
    assert closed["status"] == "PAID_OFF"
    assert closed["closure_reason"] == "PROGRAM_CANCELLATION"
    assert closed["paid_principal_cents"] == 89900
    assert closed["paid_premium_cents"] == 11988
    assert closed["outstanding_late_fee_cents"] == 0
    assert closed["protection_coverage_status"] == "TERMINATED"
    assert closed["obligation_balance_cents"] == 11988
    assert closed["delinquency_state"] == "CURRENT"
    assert_loan_ledger_invariants(closed)
    # origination, the 12-installment posting, the quote and the cancellation.
    assert closed["version"] == 4

    installments = read_installments(ctx["loan_id"])
    assert installments[11]["status"] == "PAID"
    assert installments[11]["void_reason"] is None
    for row in installments[12:]:
        assert_installment(row)
        assert row["status"] == "VOIDED"
        assert row["void_reason"] == "LOAN_CLOSED"
    voided_rows, voided_meta = validate_paginated(api_client.list_installments(
        ctx["loan_id"], make_associate_headers(),
        params={"status": "VOIDED", "limit": 100}))
    assert voided_meta["total_count"] == 12
    assert len(voided_rows) == 12

    posting_rows, posting_meta = validate_paginated(api_client.list_payment_postings(
        make_collections_headers(),
        params={"loan_id": ctx["loan_id"], "posting_type": "PAYOFF"}))
    assert posting_meta["total_count"] == 1
    payoff = posting_rows[0]
    assert_payment_posting(payoff)
    assert payoff["posting_type"] == "PAYOFF"
    assert payoff["amount_cents"] == 36659
    assert payoff["loan_id"] == ctx["loan_id"]
    assert payoff["reverses_posting_id"] is None


def test_program_cancellation_unlocks_the_handset_and_frees_the_carrier_line():
    """Closing the loan drives the two-link handset cascade even on a loan with no
    PAID installments at all: the handset goes straight to UNLOCKED and the carrier
    line becomes PORT_ELIGIBLE.

    PRD 3.7: "Then two cascade links fire in order: because the loan left `ACTIVE`,
    its handset's `unlock_status` becomes `UNLOCKED`; and because that handset
    became `UNLOCKED`, its carrier account's `activation_state` becomes
    `PORT_ELIGIBLE`, freeing the customer to take their number elsewhere."
    PRD 3.4: "Paying off the debt earns the unlock regardless of how many
    installments were formally `PAID` or how long the carrier's policy window was,
    because the collateral relationship the lock protected no longer exists."
    PRD 3.7: "Finally the customer's `outstanding_principal_cents` and
    `open_loan_count` are recomputed, and the loan's `version` advances by 1."

    Design: Difficulty/transitive_cascade/program_cancellation_cascade_loan_payoff_device_unlock_carrier_port_eligible
    """
    ctx = setup_paid_off_loan(activate=True)
    quote = ctx["quote"]
    # 89,900 remaining principal, plus the 2,500 fee, less 90 percent of the
    # whole 23,976 premium: 23,976 * 9,000 / 10,000 = 21,578.4 -> 21,578.
    assert quote["remaining_principal_cents"] == 89900
    assert quote["unearned_premium_cents"] == 23976
    assert quote["premium_rebate_cents"] == 21578
    assert quote["total_payoff_cents"] == 70822
    assert quote["paid_installment_count_at_quote"] == 0

    loan = read_loan(ctx["loan_id"])
    assert loan["status"] == "PAID_OFF"
    assert loan["closure_reason"] == "PROGRAM_CANCELLATION"
    assert loan["paid_installment_count"] == 0
    assert loan["paid_principal_cents"] == 89900
    assert loan["outstanding_late_fee_cents"] == 0
    assert loan["protection_coverage_status"] == "TERMINATED"
    assert loan["obligation_balance_cents"] == 23976
    assert_loan_ledger_invariants(loan)
    # origination mints 1, pricing the quote is 2, cancelling is 3.
    assert loan["version"] == 3

    # --- link one: the handset was never unlock-eligible, and unlocks anyway --
    handset = read_device_unit(ctx["device_id"])
    assert_device_unit(handset)
    assert handset["unlock_status"] == "UNLOCKED"
    assert handset["unlock_requested_at"] is None
    assert_iso_equals(handset["unlocked_at"], CLOCK_ORIGIN, "unlocked_at")
    # The other two dimensions are untouched by the closure.
    assert handset["activation_status"] == "ACTIVATED"
    assert handset["possession_status"] == "WITH_CUSTOMER"

    # --- link two: the line may now be ported away ---------------------------
    carrier_accounts = read_carrier_accounts(ctx["customer_id"])
    assert len(carrier_accounts) == 1
    carrier = carrier_accounts[0]
    assert_carrier_account(carrier)
    assert carrier["activation_state"] == "PORT_ELIGIBLE"
    assert carrier["active_device_imei"] == handset["imei"]
    assert carrier["port_freeze_flag"] is False

    # --- the settled quote and the borrower's recomputed aggregates ----------
    consumed = read_payoff_quote(ctx["loan_id"], quote["id"])
    assert consumed["status"] == "CONSUMED"
    assert_iso_equals(consumed["consumed_at"], CLOCK_ORIGIN, "consumed_at")
    customer = read_customer(ctx["customer_id"])
    assert customer["outstanding_principal_cents"] == 0
    assert customer["open_loan_count"] == 0
    assert customer["status"] == "ACTIVE"
    assert customer["completed_upgrade_count"] == 0

    all_installments = read_installments(ctx["loan_id"])
    assert len(all_installments) == 24
    assert all(row["status"] == "VOIDED" for row in all_installments)
    assert all(row["void_reason"] == "LOAN_CLOSED" for row in all_installments)

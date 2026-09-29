"""Exact integer arithmetic, the allocation waterfall's bucket ordering, the
temporal boundaries of the unlock and fulfillment gates, and the read paths that
must reconcile with the ledger they summarise.

Every monetary figure asserted here is an integer count of cents. Timestamps are
compared through ``assert_iso_equals`` so a server rendering three fractional
digits and one rendering none are both accepted for the same instant.
"""
from test_helpers import (
    CLOCK_ORIGIN,
    CONDITION_MULTIPLIERS_BPS,
    CREDIT_LIMITS,
    LATE_FEE_CENTS,
    TECHNICIAN_USER_ID,
    TECHNICIAN_USER_ID_2,
    UNDERWRITER_USER_ID,
    UNLOCK_MIN_PAID_INSTALLMENTS,
    ApiErrorId,
    api_client,
    apply_bps,
    assert_allocation_splits_exactly,
    assert_carrier_account,
    assert_diagnostic_report,
    assert_installment,
    assert_iso_equals,
    assert_loan_ledger_invariants,
    assert_loan_matches_schedule,
    assert_payment_posting,
    assert_schedule_sums_to_principal,
    assert_trade_in,
    at_midnight,
    create_carrier_account_payload,
    decision_payload,
    diagnostic_report_payload,
    dispute_payload,
    enroll_customer,
    floor_div,
    make_admin_headers,
    make_associate_headers,
    make_collections_headers,
    make_customer_headers,
    make_technician_headers,
    make_underwriter_headers,
    payment_payload,
    plus_days,
    publish_model,
    publish_target_model,
    read_device_model,
    read_device_unit,
    read_installment,
    read_installments,
    read_loan,
    read_trade_in,
    read_upgrade_request,
    regrade_payload,
    round_half_up,
    set_clock,
    setup_active_loan,
    setup_loan_with_paid_installments,
    setup_trade_in_received,
    setup_unlock_eligible,
    setup_upgrade_ready,
    setup_upgrade_request,
    submit_application,
    trade_in_declaration_payload,
    upgrade_request_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# The reference 24-month loan on the 89,900-cent model with a 999-cent premium.
PRINCIPAL_CENTS = 89_900
BASE_PRINCIPAL_COMPONENT_CENTS = 3_746
LAST_PRINCIPAL_COMPONENT_CENTS = 3_742
INSTALLMENT_CENTS = 4_745
LAST_INSTALLMENT_CENTS = 4_741
PREMIUM_TOTAL_CENTS = 23_976
OBLIGATION_AT_ORIGINATION_CENTS = 113_876
TRADE_IN_BASE_CREDIT_CENTS = 45_000


def test_partially_paid_installment_is_excluded_from_the_eligibility_ratio():
    """Twelve fully PAID installments plus a 1,000-cent stub on the thirteenth yield
    an eligibility ratio of 5,000 bps, not 5,416: the PARTIALLY_PAID installment
    contributes nothing to `paid_installment_count`.

    PRD: "The `eligibility_ratio_bps` figure is the loan's `paid_installment_count`
    multiplied by 10,000 and then divided by the loan's `term_months` using
    truncating division, so the result is a basis-point measure of how much of the
    ladder has been retired."
    PRD: "Because the count admits only installments in `PAID`, a `PARTIALLY_PAID`
    installment contributes nothing however close to full it is, and late fees and
    overpayments are irrelevant to the ratio entirely."

    Design: Corner/calculations/partially_paid_installment_is_excluded_from_the_eligibility_ratio
    """
    ctx = setup_loan_with_paid_installments(12, activate=True)
    loan_id = ctx["loan_id"]
    customer_headers = make_customer_headers(ctx["customer_id"])

    # A 1,000-cent stub lands in the third bucket against installment 13.
    posting = validate_success(
        api_client.create_payment(loan_id, payment_payload(1_000), customer_headers), 201)
    assert_payment_posting(posting)
    assert posting["amount_cents"] == 1_000
    assert posting["allocated_late_fee_cents"] == 0
    assert posting["allocated_principal_cents"] == 789
    assert posting["allocated_premium_cents"] == 211
    assert posting["installments_satisfied_count"] == 0
    assert posting["overpayment_cents"] == 0
    assert_allocation_splits_exactly(posting)
    # 1000 * 3746 / 4745 = 789.46..., rounded half up to 789; the premium share is
    # the arithmetic complement.
    assert posting["allocated_principal_cents"] == round_half_up(
        1_000 * BASE_PRINCIPAL_COMPONENT_CENTS, INSTALLMENT_CENTS)

    twelfth = read_installment(loan_id, 12)
    assert twelfth["status"] == "PAID"
    assert twelfth["paid_amount_cents"] == INSTALLMENT_CENTS

    thirteenth = read_installment(loan_id, 13)
    assert_installment(thirteenth)
    assert thirteenth["status"] == "PARTIALLY_PAID"
    assert thirteenth["paid_amount_cents"] == 1_000
    assert thirteenth["paid_principal_cents"] == 789
    assert thirteenth["paid_premium_cents"] == 211
    assert thirteenth["paid_at"] is None

    loan = read_loan(loan_id)
    assert loan["paid_installment_count"] == 12
    assert loan["obligation_balance_cents"] == 55_936
    assert_loan_ledger_invariants(loan)
    assert_loan_matches_schedule(loan, read_installments(loan_id))

    # Open the upgrade window and ask for an upgrade: the ratio floors to 5,000 bps.
    window_start = at_midnight(loan["upgrade_window_opens_at"])
    set_clock(window_start)
    loan = read_loan(loan_id)
    assert loan["delinquency_state"] == "CURRENT"
    assert loan["days_past_due"] == 0

    request = validate_success(api_client.create_upgrade_request(
        upgrade_request_payload(loan_id, ctx["target_model"]["id"], window_start,
                                loan["version"]),
        customer_headers), 201)
    assert request["paid_installment_count_at_request"] == 12
    assert request["eligibility_ratio_bps"] == 5_000
    assert request["eligibility_ratio_bps"] == floor_div(12 * 10_000, 24)
    assert request["status"] == "ELIGIBILITY_PASSED"


def test_credit_limit_constants_are_applied_per_band():
    """The same 119,900-cent application is approved outright under PRIME and
    NEAR_PRIME but declined under SUBPRIME, purely because each band carries a
    different program credit limit constant.

    PRD: "The band resolves to a program credit limit — 250,000 cents for `PRIME`,
    150,000 cents for `NEAR_PRIME`, and 80,000 cents for `SUBPRIME` — and that figure
    is written to the application's `credit_limit_cents`."
    PRD: "In all three cases `underwriter_user_id` is set to the acting `X-User-ID`,
    `decided_at` is set to the logical clock, and the decision is written back onto
    the customer: the customer's own `credit_score_band` and `credit_limit_cents` are
    overwritten from this decision, so the most recent decision always governs the
    customer's headroom."

    Design: Corner/calculations/credit_limit_constants_are_applied_per_band
    """
    model = publish_target_model()
    assert model["retail_price_cents"] == 119_900

    expected = {
        "PRIME": ("APPROVED", 250_000, 119_900, 0, "WITHIN_LIMIT"),
        "NEAR_PRIME": ("APPROVED", 150_000, 119_900, 0, "WITHIN_LIMIT"),
        "SUBPRIME": ("DECLINED", 80_000, 0, 0, "EXPOSURE_ABOVE_CONDITIONAL_BAND"),
    }
    for band, (status, limit, approved, conditional, reason) in expected.items():
        customer = enroll_customer()
        application = submit_application(customer["id"], model["id"],
                                         requested_term_months=24,
                                         declared_down_payment_cents=0)
        assert application["requested_principal_cents"] == 119_900

        decided = validate_success(api_client.decide_credit_application(
            application["id"], decision_payload(band), make_underwriter_headers()))
        assert decided["status"] == status, band
        assert decided["credit_score_band"] == band
        assert decided["credit_limit_cents"] == limit, band
        assert decided["credit_limit_cents"] == CREDIT_LIMITS[band]
        assert decided["exposure_at_decision_cents"] == 119_900, band
        assert decided["approved_principal_cents"] == approved, band
        assert decided["conditional_down_payment_required_cents"] == conditional, band
        assert decided["decision_reason"] == reason, band
        assert decided["underwriter_user_id"] == UNDERWRITER_USER_ID
        assert_iso_equals(decided["decided_at"], CLOCK_ORIGIN, "decided_at")

        # The decision is written back onto the customer.
        stored = validate_success(
            api_client.get_customer(customer["id"], make_customer_headers(customer["id"])))
        assert stored["credit_score_band"] == band
        assert stored["credit_limit_cents"] == limit, band


def test_credit_decision_threshold_at_limit_at_ceiling_and_one_cent_above():
    """Under SUBPRIME's 80,000-cent limit, exposure of exactly 80,000 is APPROVED,
    exactly 100,000 (the conditional ceiling) is CONDITIONAL_APPROVED with a
    20,000-cent required down payment, and 100,001 — one cent above — is DECLINED.

    PRD: "A conditional ceiling is then formed by taking 12,500 basis points of the
    credit limit — that is, one and a quarter times it — with the result rounded half
    up to whole cents."
    PRD: "When exposure is above the credit limit but still less than or equal to the
    conditional ceiling, the application advances `SUBMITTED → CONDITIONAL_APPROVED`:
    `conditional_down_payment_required_cents` is set to exposure minus the credit
    limit — the cash the applicant must find to bring themselves back inside the
    limit — `approved_principal_cents` is set to `requested_principal_cents` less that
    required amount, and `decision_reason` records
    `CONDITIONAL_DOWN_PAYMENT_REQUIRED`."
    PRD: "When exposure exceeds the conditional ceiling, the application advances
    `SUBMITTED → DECLINED`: both `conditional_down_payment_required_cents` and
    `approved_principal_cents` are set to zero and `decision_reason` records
    `EXPOSURE_ABOVE_CONDITIONAL_BAND`."

    Design: Corner/calculations/credit_decision_threshold_at_limit_at_ceiling_and_one_cent_above
    """
    ceiling_cents = apply_bps(CREDIT_LIMITS["SUBPRIME"], 12_500)
    assert ceiling_cents == 100_000

    cases = [
        (80_000, "APPROVED", 80_000, 0, "WITHIN_LIMIT"),
        (100_000, "CONDITIONAL_APPROVED", 80_000, 20_000,
         "CONDITIONAL_DOWN_PAYMENT_REQUIRED"),
        (100_001, "DECLINED", 0, 0, "EXPOSURE_ABOVE_CONDITIONAL_BAND"),
    ]
    for price, status, approved, conditional, reason in cases:
        model = publish_model(retail_price_cents=price)
        customer = enroll_customer()
        application = submit_application(customer["id"], model["id"],
                                         requested_term_months=24,
                                         declared_down_payment_cents=0)
        assert application["requested_principal_cents"] == price

        decided = validate_success(api_client.decide_credit_application(
            application["id"], decision_payload("SUBPRIME"), make_underwriter_headers()))
        assert decided["status"] == status, price
        assert decided["credit_limit_cents"] == 80_000, price
        assert decided["exposure_at_decision_cents"] == price, price
        assert decided["approved_principal_cents"] == approved, price
        assert decided["conditional_down_payment_required_cents"] == conditional, price
        assert decided["decision_reason"] == reason, price

    rows, meta = validate_paginated(api_client.list_credit_applications(
        make_underwriter_headers(), params={"status": "CONDITIONAL_APPROVED"}))
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["requested_principal_cents"] == 100_000
    assert rows[0]["conditional_down_payment_required_cents"] == 20_000


def test_trade_in_battery_tier_boundaries_at_eighty_and_sixty():
    """Battery health of exactly 80, then 79, then 59 walks the three deduction
    tiers — 0, 4,000 and 8,000 cents — with the derived condition stepping
    EXCELLENT, GOOD, FAIR; the third dispute is then refused.

    PRD: "The battery implies `EXCELLENT` when `battery_health_pct` is 80 or above,
    `GOOD` when it is 60 or above but below 80, and `FAIR` when it is below 60."
    PRD: "`battery_deduction_cents` records the deduction the measured battery
    attracts — 0 cents at 80 percent health or above, 4,000 cents from 60 through 79
    percent, and 8,000 cents below 60 percent."
    PRD: "Then, and only then, `screen_deduction_cents` and `battery_deduction_cents`
    are subtracted from the rounded product; the deductions are flat cash amounts and
    are never scaled by the multiplier."
    PRD: "A third dispute on the same trade-in — one raised when `dispute_count` has
    already reached 2 — is refused with `ERR_DISPUTE_LIMIT_REACHED`."

    Design: Corner/calculations/trade_in_battery_tier_boundaries_at_eighty_and_sixty
    """
    ctx = setup_trade_in_received(declared_condition="EXCELLENT",
                                 technician_user_id=TECHNICIAN_USER_ID)
    trade_in_id = ctx["trade_in_id"]
    customer_headers = make_customer_headers(ctx["customer_id"])
    assert ctx["model"]["trade_in_base_credit_cents"] == TRADE_IN_BASE_CREDIT_CENTS
    assert ctx["trade_in"]["credit_estimate_cents"] == TRADE_IN_BASE_CREDIT_CENTS

    # Tier boundary 1: exactly 80 percent health -> EXCELLENT, zero deduction.
    first = validate_success(api_client.create_diagnostic_report(
        trade_in_id, diagnostic_report_payload(screen_grade="PRISTINE",
                                               battery_health_pct=80),
        make_technician_headers(TECHNICIAN_USER_ID)), 201)
    assert_diagnostic_report(first)
    assert first["sequence_no"] == 1
    assert first["report_type"] == "INITIAL"
    assert first["technician_user_id"] == TECHNICIAN_USER_ID
    assert first["derived_condition"] == "EXCELLENT"
    assert first["diagnostic_result"] == "PASS"
    assert first["condition_multiplier_bps"] == 10_000
    assert first["screen_deduction_cents"] == 0
    assert first["battery_deduction_cents"] == 0
    assert first["computed_credit_cents"] == 45_000

    graded = read_trade_in(trade_in_id)
    assert graded["status"] == "GRADED"
    assert graded["graded_condition"] == "EXCELLENT"
    assert graded["credit_final_cents"] == 45_000
    assert graded["credit_variance_cents"] == 0
    assert graded["latest_report_sequence_no"] == 1

    disputed = validate_success(api_client.dispute_trade_in(
        trade_in_id, dispute_payload("BATTERY_READING_DISPUTED"), customer_headers))
    assert disputed["status"] == "DISPUTED"
    assert disputed["dispute_count"] == 1

    # Tier boundary 2: 79 percent health -> GOOD, 4,000-cent flat deduction.
    second = validate_success(api_client.regrade_trade_in(
        trade_in_id, regrade_payload(screen_grade="PRISTINE", battery_health_pct=79,
                                     override_reason="Battery re-measured on the bench"),
        make_technician_headers(TECHNICIAN_USER_ID_2)), 201)
    assert_diagnostic_report(second)
    assert second["sequence_no"] == 2
    assert second["report_type"] == "REGRADE"
    assert second["technician_user_id"] == TECHNICIAN_USER_ID_2
    assert second["derived_condition"] == "GOOD"
    assert second["condition_multiplier_bps"] == 8_500
    assert second["battery_deduction_cents"] == 4_000
    assert second["screen_deduction_cents"] == 0
    assert second["computed_credit_cents"] == 34_250
    assert second["computed_credit_cents"] == apply_bps(45_000, 8_500) - 4_000

    graded = read_trade_in(trade_in_id)
    assert graded["status"] == "GRADED"
    assert graded["graded_condition"] == "GOOD"
    assert graded["credit_final_cents"] == 34_250
    assert graded["credit_variance_cents"] == -10_750
    assert graded["latest_report_sequence_no"] == 2

    disputed = validate_success(api_client.dispute_trade_in(
        trade_in_id, dispute_payload("BATTERY_READING_DISPUTED_AGAIN"), customer_headers))
    assert disputed["status"] == "DISPUTED"
    assert disputed["dispute_count"] == 2

    # Tier boundary 3: 59 percent health -> FAIR, 8,000-cent flat deduction.
    third = validate_success(api_client.regrade_trade_in(
        trade_in_id, regrade_payload(screen_grade="PRISTINE", battery_health_pct=59,
                                     override_reason="Third bench pass on the cell"),
        make_technician_headers(TECHNICIAN_USER_ID)), 201)
    assert third["sequence_no"] == 3
    assert third["report_type"] == "REGRADE"
    assert third["derived_condition"] == "FAIR"
    assert third["condition_multiplier_bps"] == 6_000
    assert third["battery_deduction_cents"] == 8_000
    assert third["computed_credit_cents"] == 19_000
    assert third["computed_credit_cents"] == apply_bps(45_000, 6_000) - 8_000

    graded = read_trade_in(trade_in_id)
    assert graded["graded_condition"] == "FAIR"
    assert graded["credit_final_cents"] == 19_000
    assert graded["credit_variance_cents"] == -26_000
    assert graded["latest_report_sequence_no"] == 3
    assert graded["dispute_count"] == 2

    # The dispute allowance is exhausted at two.
    validate_error(api_client.dispute_trade_in(
        trade_in_id, dispute_payload("BATTERY_READING_DISPUTED_ONCE_MORE"),
        customer_headers), ApiErrorId.ERR_DISPUTE_LIMIT_REACHED.value)
    unchanged = read_trade_in(trade_in_id)
    assert unchanged["status"] == "GRADED"
    assert unchanged["dispute_count"] == 2
    assert unchanged["dispute_reason"] == "BATTERY_READING_DISPUTED_AGAIN"

    rows, meta = validate_paginated(api_client.list_diagnostic_reports(
        trade_in_id, make_technician_headers(TECHNICIAN_USER_ID)))
    assert meta["total_count"] == 3
    assert [r["sequence_no"] for r in rows] == [1, 2, 3]
    rows, meta = validate_paginated(api_client.list_diagnostic_reports(
        trade_in_id, make_technician_headers(TECHNICIAN_USER_ID),
        params={"report_type": "REGRADE"}))
    assert meta["total_count"] == 2
    assert [r["battery_health_pct"] for r in rows] == [79, 59]

    assert read_device_unit(ctx["device_id"])["possession_status"] == "RETURNED"


def test_assessed_late_fee_bucket_fills_before_the_arrears_bucket():
    """A 5,245-cent payment on a loan carrying one assessed 500-cent fee and one
    4,745-cent past-due installment settles the fee first and the body second, in one
    pass, and cures the loan.

    PRD: "The first bucket is assessed late fees: every installment of this loan whose
    `status` is `PAST_DUE` and whose `late_fee_assessed` is true, taken in ascending
    `installment_number`, each needing its `late_fee_cents` less its
    `late_fee_paid_cents`."
    PRD: "The buckets are walked in that order and the installments within a bucket in
    ascending ordinal order; the same installment may legitimately be touched twice in
    one pass, once in the first bucket for its fee and once in the second for its
    body, because the fee is always collected before the amount it attaches to."
    PRD: "A first-bucket take is credited to the installment's `late_fee_paid_cents`
    and simultaneously subtracted from the loan's `outstanding_late_fee_cents`."
    PRD: "Because the delinquency threshold sits at exactly one day past the end of
    grace, a fee is assessed at 11 days past due and never at 10."

    Design: Corner/calculations/assessed_late_fee_bucket_fills_before_the_arrears_bucket
    """
    ctx = setup_active_loan()
    loan_id = ctx["loan_id"]
    eleven_days_past_due = plus_days(read_installment(loan_id, 1)["due_date"], 11)
    set_clock(eleven_days_past_due)

    sweep = validate_success(api_client.run_daily_servicing(make_collections_headers()))
    assert sweep["processed_loan_count"] == 1
    assert sweep["transitioned_loan_count"] == 1
    assert sweep["late_fees_assessed_cents"] == LATE_FEE_CENTS
    assert sweep["late_fees_assessed_cents"] == 500
    assert sweep["defaulted_loan_count"] == 0
    assert sweep["expired_upgrade_request_count"] == 0
    assert sweep["expired_quote_count"] == 0

    first = read_installment(loan_id, 1)
    assert first["status"] == "PAST_DUE"
    assert first["late_fee_assessed"] is True
    assert first["late_fee_cents"] == 500
    assert first["late_fee_paid_cents"] == 0
    second = read_installment(loan_id, 2)
    assert second["status"] == "SCHEDULED"
    assert second["late_fee_assessed"] is False
    assert second["late_fee_cents"] == 0

    loan = read_loan(loan_id)
    assert loan["delinquency_state"] == "DELINQUENT"
    assert loan["days_past_due"] == 11
    assert loan["outstanding_late_fee_cents"] == 500
    assert loan["obligation_balance_cents"] == 114_376
    assert loan["obligation_balance_cents"] == OBLIGATION_AT_ORIGINATION_CENTS + 500

    # 500 for the fee plus 4,745 for the installment body: exactly one pass.
    posting = validate_success(api_client.create_payment(
        loan_id, payment_payload(5_245), make_customer_headers(ctx["customer_id"])), 201)
    assert posting["allocated_late_fee_cents"] == 500
    assert posting["allocated_principal_cents"] == BASE_PRINCIPAL_COMPONENT_CENTS
    assert posting["allocated_premium_cents"] == 999
    assert posting["installments_satisfied_count"] == 1
    assert posting["overpayment_cents"] == 0
    assert posting["obligation_balance_after_cents"] == 109_131
    assert_allocation_splits_exactly(posting)
    assert_iso_equals(posting["posted_at"], eleven_days_past_due, "posted_at")

    settled = read_installment(loan_id, 1)
    assert settled["status"] == "PAID"
    assert settled["late_fee_paid_cents"] == 500
    assert settled["paid_amount_cents"] == INSTALLMENT_CENTS
    assert settled["paid_principal_cents"] == BASE_PRINCIPAL_COMPONENT_CENTS
    assert settled["paid_premium_cents"] == 999
    assert_iso_equals(settled["paid_at"], eleven_days_past_due, "paid_at")

    loan = read_loan(loan_id)
    assert loan["outstanding_late_fee_cents"] == 0
    assert loan["paid_installment_count"] == 1
    assert loan["obligation_balance_cents"] == 109_131
    assert loan["delinquency_state"] == "CURRENT"
    assert loan["days_past_due"] == 0
    assert_loan_ledger_invariants(loan)
    assert_loan_matches_schedule(loan, read_installments(loan_id))

    rows, meta = validate_paginated(api_client.list_delinquency_events(
        loan_id, make_collections_headers(), params={"event_type": "CURED"}))
    assert meta["total_count"] == 1
    assert rows[0]["from_state"] == "DELINQUENT"
    assert rows[0]["to_state"] == "CURRENT"


def test_overpayment_is_recorded_then_further_payment_has_nothing_to_allocate():
    """A 120,000-cent payment on a 113,876-cent obligation satisfies all 24
    installments and records a 6,124-cent overpayment; a further 1,000-cent payment
    then has nothing left to allocate against.

    PRD: "Whatever remains in the pool after the third bucket is exhausted becomes the
    posting's `overpayment_cents`: it is recorded on the posting and never
    automatically refunded."
    PRD: "Finally, a `PAYMENT` or `PAYOFF` arriving on a loan whose every installment
    is already `PAID` or `VOIDED` has nothing to allocate against and is refused with
    `ERR_NOTHING_TO_ALLOCATE`; at least one installment in `SCHEDULED`,
    `PARTIALLY_PAID` or `PAST_DUE` must exist."

    Design: Corner/calculations/overpayment_is_recorded_then_further_payment_has_nothing_to_allocate
    """
    ctx = setup_active_loan()
    loan_id = ctx["loan_id"]
    customer_headers = make_customer_headers(ctx["customer_id"])

    posting = validate_success(api_client.create_payment(
        loan_id, payment_payload(120_000), customer_headers), 201)
    assert posting["amount_cents"] == 120_000
    assert posting["allocated_late_fee_cents"] == 0
    assert posting["allocated_principal_cents"] == PRINCIPAL_CENTS
    assert posting["allocated_premium_cents"] == PREMIUM_TOTAL_CENTS
    assert posting["installments_satisfied_count"] == 24
    assert posting["overpayment_cents"] == 6_124
    assert posting["overpayment_cents"] == 120_000 - OBLIGATION_AT_ORIGINATION_CENTS
    assert posting["obligation_balance_after_cents"] == 0
    assert_allocation_splits_exactly(posting)

    loan = read_loan(loan_id)
    assert loan["obligation_balance_cents"] == 0
    assert loan["paid_installment_count"] == 24
    # A plain PAYMENT never closes a loan: only cancellation and upgrade completion do.
    assert loan["status"] == "ACTIVE"
    assert loan["closure_reason"] is None
    assert loan["delinquency_state"] == "CURRENT"
    assert loan["days_past_due"] == 0
    assert_loan_ledger_invariants(loan)

    rows, meta = validate_paginated(api_client.list_installments(
        loan_id, make_collections_headers(), params={"status": "PAID", "limit": 100}))
    assert meta["total_count"] == 24
    assert len(rows) == 24
    last = read_installment(loan_id, 24)
    assert last["status"] == "PAID"
    assert last["paid_amount_cents"] == LAST_INSTALLMENT_CENTS

    # Nothing is left in SCHEDULED, PARTIALLY_PAID or PAST_DUE.
    validate_error(api_client.create_payment(loan_id, payment_payload(1_000),
                                             customer_headers),
                   ApiErrorId.ERR_NOTHING_TO_ALLOCATE.value)
    rows, meta = validate_paginated(api_client.list_payment_postings(
        make_collections_headers(), params={"loan_id": loan_id}))
    assert meta["total_count"] == 1
    assert rows[0]["overpayment_cents"] == 6_124

    customer = validate_success(api_client.get_customer(ctx["customer_id"], customer_headers))
    assert customer["outstanding_principal_cents"] == 0
    assert customer["open_loan_count"] == 1


def test_unlock_request_passes_at_exactly_the_policy_day_boundary():
    """With the carrier's default 60-day policy and exactly 6 PAID installments, an
    unlock request lodged on the 60th day after activation is accepted, and a second
    call at the same instant completes the ladder to UNLOCKED.

    PRD: "The loan must have at least 6 installments in `status` `PAID` — the
    program's unlock payment threshold — measured by the loan's
    `paid_installment_count`; below that the request is refused with
    `ERR_UNLOCK_PAYMENT_THRESHOLD_NOT_MET`."
    PRD: "And the carrier's own waiting period must have run: the logical clock must
    have reached the handset's `activated_at` plus the carrier account's
    `unlock_policy_days` whole days, or the request is refused with
    `ERR_UNLOCK_POLICY_PERIOD_NOT_ELAPSED`."
    PRD: "The first accepted call advances `unlock_status` from `LOCKED` to
    `UNLOCK_REQUESTED` and stamps `unlock_requested_at` with the logical clock."
    PRD: "A second call, once the carrier's acknowledgement window has elapsed,
    completes the ladder by advancing `UNLOCK_REQUESTED → UNLOCKED`, stamping
    `unlocked_at` with the logical clock and pushing the carrier account
    `ACTIVATED → PORT_ELIGIBLE` so the line can be moved elsewhere."

    Design: Corner/validations/unlock_request_passes_at_exactly_the_policy_day_boundary
    """
    ctx = setup_unlock_eligible()
    loan_id = ctx["loan_id"]
    device_id = ctx["device_id"]
    customer_headers = make_customer_headers(ctx["customer_id"])

    assert ctx["carrier"]["unlock_policy_days"] == 60
    boundary = plus_days(ctx["device"]["activated_at"], 60)
    loan = read_loan(loan_id)
    assert loan["paid_installment_count"] == UNLOCK_MIN_PAID_INSTALLMENTS == 6
    assert loan["delinquency_state"] == "CURRENT"
    assert loan["obligation_balance_cents"] == 85_406
    assert_loan_ledger_invariants(loan)
    assert read_device_unit(device_id)["unlock_status"] == "LOCKED"

    requested = validate_success(
        api_client.request_device_unlock(device_id, customer_headers))
    assert requested["unlock_status"] == "UNLOCK_REQUESTED"
    assert_iso_equals(requested["unlock_requested_at"], boundary, "unlock_requested_at")
    assert requested["unlocked_at"] is None
    assert requested["activation_status"] == "ACTIVATED"
    assert requested["possession_status"] == "WITH_CUSTOMER"

    holding, _meta = validate_paginated(api_client.list_carrier_accounts(
        ctx["customer_id"], make_associate_headers()))
    assert [account["activation_state"] for account in holding] == ["ACTIVATED"]

    unlocked = validate_success(
        api_client.request_device_unlock(device_id, make_associate_headers()))
    assert unlocked["unlock_status"] == "UNLOCKED"
    assert_iso_equals(unlocked["unlocked_at"], boundary, "unlocked_at")
    assert_iso_equals(unlocked["unlock_requested_at"], boundary, "unlock_requested_at")
    assert unlocked["activation_status"] == "ACTIVATED"
    assert unlocked["possession_status"] == "WITH_CUSTOMER"

    freed, _meta = validate_paginated(api_client.list_carrier_accounts(
        ctx["customer_id"], make_associate_headers()))
    assert [account["activation_state"] for account in freed] == ["PORT_ELIGIBLE"]


def test_fulfillment_window_starting_in_the_past_is_refused_then_today_passes():
    """One day after the upgrade window opens, a fulfillment window dated yesterday is
    refused with no reservation taken, while a window dated today is accepted and
    closes exactly 7 days later.

    PRD: "`fulfillment_window_start` must be at or after the logical clock at creation
    and is expressed at `00:00:00.000Z`; a window that would open in the past is
    refused with `ERR_FULFILLMENT_WINDOW_IN_PAST` and HTTP status 422."
    PRD: "The candidate window is the half-open interval that begins at the supplied
    `fulfillment_window_start` and ends 7 days later; `fulfillment_window_end` on the
    request records that closing instant, and the window covers every instant from the
    start up to but not including the end."

    Design: Corner/validations/fulfillment_window_starting_in_the_past_is_refused_then_today_passes
    """
    ctx = setup_upgrade_ready(12)
    loan_id = ctx["loan_id"]
    target_model_id = ctx["target_model"]["id"]
    customer_headers = make_customer_headers(ctx["customer_id"])

    window_opens_at = at_midnight(ctx["loan"]["upgrade_window_opens_at"])
    assert_iso_equals(ctx["loan"]["upgrade_window_opens_at"],
                      plus_days(ctx["loan"]["origination_date"], 330),
                      "upgrade_window_opens_at")

    # Stand the clock one day past the opening so that yesterday is genuinely past.
    today = plus_days(window_opens_at, 1)
    set_clock(today)
    loan = read_loan(loan_id)
    version_before = loan["version"]

    validate_error(api_client.create_upgrade_request(
        upgrade_request_payload(loan_id, target_model_id, window_opens_at, version_before),
        customer_headers), ApiErrorId.ERR_FULFILLMENT_WINDOW_IN_PAST.value)

    # A refused request reserves nothing and holds nothing.
    assert read_device_model(target_model_id)["reserved_slot_count"] == 0
    untouched = read_loan(loan_id)
    assert untouched["upgrade_hold_flag"] is False
    assert untouched["version"] == version_before
    _rows, meta = validate_paginated(api_client.list_upgrade_requests(
        make_associate_headers(), params={"loan_id": loan_id}))
    assert meta["total_count"] == 0

    accepted = validate_success(api_client.create_upgrade_request(
        upgrade_request_payload(loan_id, target_model_id, today, version_before),
        customer_headers), 201)
    assert_iso_equals(accepted["fulfillment_window_start"], today,
                      "fulfillment_window_start")
    assert_iso_equals(accepted["fulfillment_window_end"], plus_days(today, 7),
                      "fulfillment_window_end")
    assert accepted["status"] == "ELIGIBILITY_PASSED"
    assert accepted["paid_installment_count_at_request"] == 12
    assert accepted["eligibility_ratio_bps"] == 5_000

    held = read_loan(loan_id)
    assert held["upgrade_hold_flag"] is True
    assert read_device_model(target_model_id)["reserved_slot_count"] == 1


def test_daily_run_counters_report_zero_work_and_then_one_loan():
    """The sweep on an empty portfolio reports all six counters at zero; after one
    freshly originated loan exists it reports exactly one loan examined and nothing
    else — no transition, no fee, no default, no expiry.

    PRD: "The sweep visits every loan whose `status` is `ACTIVE`, in ascending loan
    `created_at` order, and reports what it did: `processed_loan_count` for the loans
    it examined, `transitioned_loan_count` for those whose collections label moved,
    `late_fees_assessed_cents` for the total fee value it assessed,
    `defaulted_loan_count` for the loans it declared in default,
    `expired_upgrade_request_count` for the upgrade reservations it released, and
    `expired_quote_count` for the payoff quotes it retired."
    PRD: "Before any call moves it, the logical clock reads exactly
    `2026-08-01T00:00:00Z`; this fixed startup default never falls back to the host's
    real time."

    Design: Corner/endpoints/daily_run_counters_report_zero_work_and_then_one_loan
    """
    clock = set_clock(CLOCK_ORIGIN)
    assert_iso_equals(clock["current_utc"], CLOCK_ORIGIN, "current_utc")

    empty = validate_success(api_client.run_daily_servicing(make_admin_headers()))
    for counter in ("processed_loan_count", "transitioned_loan_count",
                    "late_fees_assessed_cents", "defaulted_loan_count",
                    "expired_upgrade_request_count", "expired_quote_count"):
        assert empty[counter] == 0, counter

    ctx = setup_active_loan(with_target_model=False, with_carrier_account=False)
    loan_id = ctx["loan_id"]

    one_loan = validate_success(api_client.run_daily_servicing(make_collections_headers()))
    assert one_loan["processed_loan_count"] == 1
    assert one_loan["transitioned_loan_count"] == 0
    assert one_loan["late_fees_assessed_cents"] == 0
    assert one_loan["defaulted_loan_count"] == 0
    assert one_loan["expired_upgrade_request_count"] == 0
    assert one_loan["expired_quote_count"] == 0

    loan = read_loan(loan_id)
    assert loan["status"] == "ACTIVE"
    assert loan["delinquency_state"] == "CURRENT"
    assert loan["days_past_due"] == 0
    assert loan["outstanding_late_fee_cents"] == 0

    _rows, meta = validate_paginated(api_client.list_installments(
        loan_id, make_collections_headers(), params={"status": "SCHEDULED", "limit": 100}))
    assert meta["total_count"] == 24

    _events, meta = validate_paginated(api_client.list_delinquency_events(
        loan_id, make_collections_headers()))
    assert meta["total_count"] == 0


def test_loan_read_reconciles_with_its_installment_schedule():
    """The loan's headline figures and its 24-row installment sub-collection agree to
    the cent, and the last installment carries the 3,742-cent residual.

    PRD: "`obligation_balance_cents`, the loan's headline outstanding figure, is
    defined generally as the unpaid principal (`principal_cents` less
    `paid_principal_cents`) plus the unpaid premium (`premium_total_cents` less
    `paid_premium_cents`) plus `outstanding_late_fee_cents`; at origination, with
    nothing paid and no fees, that reduces to `principal_cents` plus
    `premium_total_cents`."
    PRD: "For the last installment — and only the last — `principal_component_cents`
    is instead the loan's `principal_cents` less the base figure multiplied by one
    fewer than `term_months`; this residual guarantees that the principal components
    sum to `principal_cents` exactly, and it means the final installment's principal
    share may come out either smaller or larger than the base figure."
    PRD: "`premium_total_cents` is the monthly premium multiplied by `term_months`."

    Design: Corner/endpoints/loan_read_reconciles_with_its_installment_schedule
    """
    ctx = setup_active_loan()
    loan_id = ctx["loan_id"]

    loan = validate_success(api_client.get_loan(loan_id, make_collections_headers()))
    assert loan["term_months"] == 24
    assert loan["principal_cents"] == PRINCIPAL_CENTS
    assert loan["monthly_protection_premium_cents"] == 999
    assert loan["premium_total_cents"] == PREMIUM_TOTAL_CENTS
    assert loan["monthly_installment_cents"] == INSTALLMENT_CENTS
    assert loan["obligation_balance_cents"] == OBLIGATION_AT_ORIGINATION_CENTS
    assert loan["obligation_balance_cents"] == PRINCIPAL_CENTS + PREMIUM_TOTAL_CENTS
    assert_loan_ledger_invariants(loan)

    rows, meta = validate_paginated(api_client.list_installments(
        loan_id, make_collections_headers(), params={"limit": 100}))
    assert meta["total_count"] == 24
    assert meta["limit"] == 100
    assert meta["offset"] == 0
    assert meta["has_more"] is False
    assert len(rows) == 24

    schedule = sorted(rows, key=lambda row: row["installment_number"])
    assert [row["installment_number"] for row in schedule] == list(range(1, 25))
    assert sum(row["amount_due_cents"] for row in schedule) == OBLIGATION_AT_ORIGINATION_CENTS
    assert sum(row["principal_component_cents"] for row in schedule) == PRINCIPAL_CENTS
    assert sum(row["premium_component_cents"] for row in schedule) == PREMIUM_TOTAL_CENTS
    assert_schedule_sums_to_principal(schedule, loan)
    assert_loan_matches_schedule(loan, schedule)

    assert schedule[0]["principal_component_cents"] == BASE_PRINCIPAL_COMPONENT_CENTS
    assert schedule[0]["premium_component_cents"] == 999
    assert schedule[0]["amount_due_cents"] == INSTALLMENT_CENTS
    assert schedule[-1]["principal_component_cents"] == LAST_PRINCIPAL_COMPONENT_CENTS
    assert schedule[-1]["amount_due_cents"] == LAST_INSTALLMENT_CENTS
    assert schedule[-1]["principal_component_cents"] == (
        PRINCIPAL_CENTS - BASE_PRINCIPAL_COMPONENT_CENTS * 23)

    rows, meta = validate_paginated(api_client.list_loans(
        make_collections_headers(),
        params={"customer_id": ctx["customer_id"], "status": "ACTIVE"}))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == loan_id
    _rows, meta = validate_paginated(api_client.list_loans(
        make_collections_headers(),
        params={"customer_id": ctx["customer_id"], "delinquency_state": "DELINQUENT"}))
    assert meta["total_count"] == 0


def test_carrier_account_create_read_and_list_round_trip():
    """Two carrier accounts under one customer and a third under another: the
    sub-collection returns only the addressed customer's rows, the optional attributes
    take their declared defaults when omitted, and paging reports the truth.

    PRD: "Two optional attributes complete the record: `unlock_policy_days`, the
    carrier-specific minimum number of whole days that must elapse between a device's
    activation and an accepted unlock request, which must be zero or greater and
    defaults to 60 when omitted; and `port_freeze_flag`, which defaults to false and,
    while true, prevents any handset from being activated on the account."
    PRD: "A fresh account opens with `activation_state` `PENDING`, `activated_at` null,
    and `active_device_imei` null."
    PRD: "`limit` controls page size: it defaults to 10 when omitted, may not be
    smaller than 1, and may not be larger than 100."

    Design: Corner/endpoints/carrier_account_create_read_and_list_round_trip
    """
    customer_a = enroll_customer()
    customer_b = enroll_customer()
    headers_a = make_customer_headers(customer_a["id"])
    headers_b = make_customer_headers(customer_b["id"])

    first = validate_success(api_client.create_carrier_account(
        customer_a["id"],
        create_carrier_account_payload(carrier_code="ATT", unlock_policy_days=90,
                                       port_freeze_flag=True),
        headers_a), 201)
    assert_carrier_account(first)
    assert first["customer_id"] == customer_a["id"]
    assert first["carrier_code"] == "ATT"
    assert first["unlock_policy_days"] == 90
    assert first["port_freeze_flag"] is True
    assert first["activation_state"] == "PENDING"
    assert first["activated_at"] is None
    assert first["active_device_imei"] is None
    assert first["version"] == 1

    # Both optional attributes omitted: the declared defaults apply.
    second = validate_success(api_client.create_carrier_account(
        customer_a["id"], create_carrier_account_payload(carrier_code="TMOBILE"),
        make_associate_headers()), 201)
    assert second["unlock_policy_days"] == 60
    assert second["port_freeze_flag"] is False
    assert second["activation_state"] == "PENDING"

    other = validate_success(api_client.create_carrier_account(
        customer_b["id"], create_carrier_account_payload(carrier_code="VERIZON"),
        headers_b), 201)
    assert other["customer_id"] == customer_b["id"]

    rows, meta = validate_paginated(api_client.list_carrier_accounts(
        customer_a["id"], make_technician_headers()))
    assert meta["total_count"] == 2
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["has_more"] is False
    listed = {row["id"] for row in rows}
    assert listed == {first["id"], second["id"]}
    assert other["id"] not in listed
    for row in rows:
        assert row["customer_id"] == customer_a["id"]
        assert row["activation_state"] == "PENDING"
        assert row["active_device_imei"] is None

    page, meta = validate_paginated(api_client.list_carrier_accounts(
        customer_a["id"], headers_a, params={"limit": 1}))
    assert len(page) == 1
    assert meta["limit"] == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True

    rows_b, meta_b = validate_paginated(api_client.list_carrier_accounts(
        customer_b["id"], headers_b))
    assert meta_b["total_count"] == 1
    assert rows_b[0]["id"] == other["id"]


def test_trade_in_declaration_links_the_request_and_the_handset():
    """The declaration links the upgrade request to the returning handset and prices
    the estimate off the traded model's own base credit, not the target model's.

    PRD: "The estimate is the traded handset's model `trade_in_base_credit_cents`
    multiplied by the condition multiplier for the declared condition and divided by
    10,000, rounded half up to whole cents."
    PRD: "The new trade-in opens in `status` `DECLARED` with `graded_condition`,
    `credit_final_cents`, `diagnostic_result` and `dispute_reason` all null,
    `latest_report_sequence_no`, `credit_variance_cents` and `dispute_count` all zero,
    and `received_at`, `graded_at` and `settled_at` all null."
    PRD: "The declared handset moves `WITH_CUSTOMER → RETURN_PENDING`, the request
    advances `ELIGIBILITY_PASSED → TRADE_IN_DECLARED`, and the request's
    `trade_in_credit_projection_cents`, `projected_rollover_balance_cents`,
    `credit_shortfall_cents` and `funding_flag` are all refreshed."
    PRD: "Trade-ins may be listed and narrowed by `upgrade_request_id`, by
    `device_unit_id` and by `status`."

    Design: Corner/endpoints/trade_in_declaration_links_the_request_and_the_handset
    """
    ctx = setup_upgrade_request(12)
    upgrade_request_id = ctx["upgrade_request_id"]
    device_id = ctx["device_id"]
    assert ctx["model"]["trade_in_base_credit_cents"] == TRADE_IN_BASE_CREDIT_CENTS
    assert ctx["target_model"]["trade_in_base_credit_cents"] == 60_000

    trade_in = validate_success(api_client.declare_trade_in(
        upgrade_request_id, trade_in_declaration_payload(device_id, "GOOD"),
        make_customer_headers(ctx["customer_id"])), 201)
    assert_trade_in(trade_in)
    assert trade_in["upgrade_request_id"] == upgrade_request_id
    assert trade_in["device_unit_id"] == device_id
    assert trade_in["declared_condition"] == "GOOD"
    # 45,000 * 8,500 / 10,000 = 38,250 — the traded handset's base credit, not 51,000.
    assert trade_in["credit_estimate_cents"] == 38_250
    assert trade_in["credit_estimate_cents"] == apply_bps(
        TRADE_IN_BASE_CREDIT_CENTS, CONDITION_MULTIPLIERS_BPS["GOOD"])
    assert trade_in["credit_estimate_cents"] != apply_bps(
        60_000, CONDITION_MULTIPLIERS_BPS["GOOD"])
    assert trade_in["status"] == "DECLARED"
    assert trade_in["graded_condition"] is None
    assert trade_in["credit_final_cents"] is None
    assert trade_in["diagnostic_result"] is None
    assert trade_in["dispute_reason"] is None
    assert trade_in["latest_report_sequence_no"] == 0
    assert trade_in["credit_variance_cents"] == 0
    assert trade_in["dispute_count"] == 0
    assert trade_in["received_at"] is None
    assert trade_in["graded_at"] is None
    assert trade_in["settled_at"] is None

    assert read_upgrade_request(upgrade_request_id)["status"] == "TRADE_IN_DECLARED"
    assert read_device_unit(device_id)["possession_status"] == "RETURN_PENDING"

    for params in ({"upgrade_request_id": upgrade_request_id},
                   {"device_unit_id": device_id},
                   {"status": "DECLARED"}):
        rows, meta = validate_paginated(api_client.list_trade_ins(
            make_associate_headers(), params=params))
        assert meta["total_count"] == 1, params
        assert rows[0]["id"] == trade_in["id"], params

    _rows, meta = validate_paginated(api_client.list_trade_ins(
        make_associate_headers(), params={"status": "RECEIVED"}))
    assert meta["total_count"] == 0

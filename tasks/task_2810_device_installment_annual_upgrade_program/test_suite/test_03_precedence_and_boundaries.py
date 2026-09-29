"""Screening-ladder precedence and boundary precision.

Two families of proof live here.

The precedence tests each build a request that violates two rules at once and
assert the single error id the PRD's ordered screening ladder awards, then build
the control in which only the lower-priority rule is violated and assert that
the lower-priority error id is the one that surfaces. Without the control an
implementation that happens to check the rules in the opposite order, or that
only ever implements one of them, would pass.

The boundary tests walk the exact cent, the exact day and the exact installment
count at which a threshold flips, so an off-by-one in either direction is caught:
11 versus 12 PAID installments against the 5,000-basis-point upgrade gate,
89 versus 90 days past due against the DEFAULT declaration, a net rollover of
exactly 30,000 cents versus one cent above the carry-forward ceiling, and a
payoff quote priced over an empty past-due set on a loan with zero payments.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
    # constants
    DEFAULT_MIN_DPD,
    DELINQUENT_MIN_DPD,
    GRACE_PERIOD_DAYS,
    LATE_FEE_CENTS,
    MODEL_B_MONTHLY_INSTALLMENT_CENTS,
    MODEL_B_PREMIUM_TOTAL_CENTS,
    ROLLOVER_SHORTFALL_LIMIT_CENTS,
    UPGRADE_PAID_RATIO_BPS,
    at_midnight,
    plus_days,
    # factories
    completion_payload,
    create_loan_payload,
    next_imei,
    upgrade_request_payload,
    # fixtures
    advance_to_dpd,
    decide_application,
    declare_trade_in,
    enroll_customer,
    grade_trade_in,
    installment_total_cents,
    open_upgrade_request,
    post_payment,
    price_quote,
    publish_model,
    read_customer,
    read_delinquency_events,
    read_device_model,
    read_installments,
    read_loan,
    read_trade_in,
    read_upgrade_request,
    receive_trade_in,
    set_clock,
    setup_active_loan,
    setup_loan_with_paid_installments,
    setup_upgrade_ready,
    setup_upgrade_request,
    submit_application,
    # assertions
    assert_allocation_splits_exactly,
    assert_iso_equals,
    assert_loan_ledger_invariants,
    assert_loan_matches_schedule,
    assert_payoff_quote,
    assert_upgrade_request,
    # identities
    ASSOCIATE_USER_ID,
    make_associate_headers,
)

DUAL_ROLE_USER_ID = "u-dual-role-1"


# =========================================================================
# Difficulty/priority_pair_validation_conflict
#   delinquent_loan_beats_upgrade_threshold_on_upgrade_request
# Band 7 (state preconditions) outranks band 11 (fiscal rules).
# =========================================================================
def test_delinquent_loan_outranks_unmet_upgrade_threshold_on_upgrade_request():
    """A loan that is both in GRACE and short of the payment threshold reports
    ERR_LOAN_DELINQUENT, because the state band is screened before the fiscal band.

    PRD: "Validation is not a set of independent checks — it is a strict ladder,
    evaluated in ascending priority, and the **first** violation encountered is the
    one reported."
    PRD band 7: "the loan's `delinquency_state` must be `CURRENT` for both
    upgrade-request creation and unlock requests (`ERR_LOAN_DELINQUENT`, 409)"
    PRD band 11: "**Fiscal rules, evaluated last of all**, in this internal order:
    the upgrade payment threshold (`ERR_UPGRADE_THRESHOLD_NOT_MET`, 409, on
    upgrade-request creation)"
    PRD: "The loan's `delinquency_state` must be `CURRENT`; a loan in `GRACE`,
    `DELINQUENT` or `DEFAULT` is under the device financing lock and its upgrade is
    refused with `ERR_LOAN_DELINQUENT`."

    Design: Difficulty/priority_pair_validation_conflict/delinquent_loan_beats_upgrade_threshold_on_upgrade_request
    """
    ctx = setup_loan_with_paid_installments(10, activate=True)
    loan_id = ctx["loan_id"]
    target_model_id = ctx["target_model"]["id"]

    # Installment 11 falls due 2027-07-01; stand the clock exactly 10 days past it
    # and sweep, so the loan sits in GRACE with no fee yet assessed.
    advance_to_dpd(ctx, GRACE_PERIOD_DAYS, installment_number=11)
    loan = ctx["loan"]
    assert loan["delinquency_state"] == "GRACE", loan["delinquency_state"]
    assert loan["days_past_due"] == 10, loan["days_past_due"]
    assert loan["outstanding_late_fee_cents"] == 0, loan["outstanding_late_fee_cents"]
    assert loan["paid_installment_count"] == 10, loan["paid_installment_count"]
    assert loan["status"] == "ACTIVE", loan["status"]
    assert_iso_equals(loan["upgrade_window_opens_at"], "2027-06-27T00:00:00Z",
                      "upgrade_window_opens_at")

    # 10 of 24 paid is 4,166 bps, so the fiscal gate is violated too, and the
    # upgrade window opened 14 days ago so the temporal band is clean.
    window_start = plus_days(at_midnight(loan["upgrade_window_opens_at"]), 14)
    assert_iso_equals(window_start, "2027-07-11T00:00:00Z", "candidate window start")

    response = api_client.create_upgrade_request(
        upgrade_request_payload(loan_id, target_model_id, window_start, loan["version"]),
        ctx["customer_headers"])
    validate_error(response, ApiErrorId.ERR_LOAN_DELINQUENT.value)

    rows, meta = validate_paginated(
        api_client.list_upgrade_requests(make_associate_headers(), {"loan_id": loan_id}))
    assert meta["total_count"] == 0, meta["total_count"]
    assert rows == [], rows
    assert read_device_model(target_model_id)["reserved_slot_count"] == 0
    after = read_loan(loan_id)
    assert after["upgrade_hold_flag"] is False, after["upgrade_hold_flag"]
    assert after["version"] == loan["version"], (after["version"], loan["version"])


def test_unmet_upgrade_threshold_surfaces_once_the_loan_is_current():
    """The control for the pair above: with delinquency CURRENT and nothing else
    wrong, the same 10-of-24 loan reports the lower-priority ERR_UPGRADE_THRESHOLD_NOT_MET.

    PRD: "The `eligibility_ratio_bps` figure is the loan's `paid_installment_count`
    multiplied by 10,000 and then divided by the loan's `term_months` using truncating
    division, so the result is a basis-point measure of how much of the ladder has been
    retired."
    PRD: "That figure must be at least 5,000 basis points — half the schedule."
    PRD: "Validation is not a set of independent checks — it is a strict ladder,
    evaluated in ascending priority, and the **first** violation encountered is the
    one reported."

    Design: Difficulty/priority_pair_validation_conflict/delinquent_loan_beats_upgrade_threshold_on_upgrade_request
    """
    ctx = setup_upgrade_ready(paid_count=10)
    loan = ctx["loan"]
    loan_id = ctx["loan_id"]
    target_model_id = ctx["target_model"]["id"]

    assert loan["delinquency_state"] == "CURRENT", loan["delinquency_state"]
    assert loan["days_past_due"] == 0, loan["days_past_due"]
    assert loan["paid_installment_count"] == 10, loan["paid_installment_count"]
    assert 10 * 10_000 // loan["term_months"] == 4_166
    assert 4_166 < UPGRADE_PAID_RATIO_BPS

    response = api_client.create_upgrade_request(
        upgrade_request_payload(loan_id, target_model_id, ctx["window_start"],
                                loan["version"]),
        ctx["customer_headers"])
    validate_error(response, ApiErrorId.ERR_UPGRADE_THRESHOLD_NOT_MET.value)

    rows, meta = validate_paginated(
        api_client.list_upgrade_requests(make_associate_headers(), {"loan_id": loan_id}))
    assert meta["total_count"] == 0, meta["total_count"]
    assert rows == [], rows
    assert read_device_model(target_model_id)["reserved_slot_count"] == 0
    after = read_loan(loan_id)
    assert after["upgrade_hold_flag"] is False, after["upgrade_hold_flag"]
    assert after["delinquency_state"] == "CURRENT", after["delinquency_state"]


# =========================================================================
# Difficulty/priority_pair_validation_conflict
#   segregation_of_duties_beats_down_payment_insufficient_on_origination
# Band 8 (business safety) outranks band 11 (fiscal rules), and inside band 11
# the conditional down payment is screened before the customer credit limit.
# =========================================================================
def _subprime_conditional_application():
    """A SUBPRIME CONDITIONAL_APPROVED application whose decision was filed by
    DUAL_ROLE_USER_ID, so that the same identifier can later present itself as the
    originating RetailAssociate."""
    model = publish_model()
    customer = enroll_customer()
    application = submit_application(customer["id"], model["id"], requested_term_months=24)
    application = decide_application(application["id"], "SUBPRIME",
                                     underwriter_user_id=DUAL_ROLE_USER_ID)
    assert model["retail_price_cents"] == 89_900, model["retail_price_cents"]
    assert application["status"] == "CONDITIONAL_APPROVED", application["status"]
    assert application["credit_limit_cents"] == 80_000, application["credit_limit_cents"]
    assert application["exposure_at_decision_cents"] == 89_900
    assert application["conditional_down_payment_required_cents"] == 9_900
    assert application["approved_principal_cents"] == 80_000
    assert application["decision_reason"] == "CONDITIONAL_DOWN_PAYMENT_REQUIRED"
    assert application["underwriter_user_id"] == DUAL_ROLE_USER_ID
    return model, customer, application


def test_segregation_of_duties_outranks_insufficient_down_payment_on_origination():
    """One operator who decided the application and then originates it is refused
    with ERR_SEGREGATION_OF_DUTIES even though the tendered down payment is also
    one cent short and the resulting principal would also breach the credit limit.

    PRD: "Validation is not a set of independent checks — it is a strict ladder,
    evaluated in ascending priority, and the **first** violation encountered is the
    one reported."
    PRD band 8: "Segregation of duties is enforced next, yielding
    `ERR_SEGREGATION_OF_DUTIES` (403) on origination and on regrade; then the
    customer's financing posture is checked, yielding `ERR_CUSTOMER_FINANCING_LOCKED`
    (409) on application submission, on the underwriting decision, on origination and
    on upgrade-request creation."
    PRD: "The `CreditUnderwriter` who decided an application is recorded on it as
    `underwriter_user_id`, and the `RetailAssociate` who originates the loan from that
    application must present a different `X-User-ID`; if the two match, the request is
    refused with `ERR_SEGREGATION_OF_DUTIES` and HTTP status 403."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_down_payment_insufficient_on_origination
    """
    model, customer, application = _subprime_conditional_application()

    # 9,899 cents is one cent below the required 9,900, and it leaves a principal of
    # 80,001 cents against a credit limit of 80,000 — two fiscal breaches at once.
    response = api_client.create_loan(
        create_loan_payload(application["id"], imei=next_imei(), down_payment_cents=9_899),
        make_associate_headers(DUAL_ROLE_USER_ID))
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    rows, meta = validate_paginated(
        api_client.list_loans(make_associate_headers(), {"customer_id": customer["id"]}))
    assert meta["total_count"] == 0, meta["total_count"]
    assert rows == [], rows
    unchanged = validate_success(
        api_client.get_credit_application(application["id"], make_associate_headers()))
    assert unchanged["status"] == "CONDITIONAL_APPROVED", unchanged["status"]
    after_customer = read_customer(customer["id"])
    assert after_customer["open_loan_count"] == 0, after_customer["open_loan_count"]
    assert after_customer["outstanding_principal_cents"] == 0


def test_insufficient_down_payment_outranks_credit_limit_when_the_associate_differs():
    """The control: with the segregation-of-duties defect removed, the same one-cent
    shortfall reports ERR_DOWN_PAYMENT_INSUFFICIENT — the earlier fiscal check — and
    not ERR_CREDIT_LIMIT_EXCEEDED, which the same payload also violates.

    PRD: "When the application is `CONDITIONAL_APPROVED`, the collected
    `down_payment_cents` must be at least the application's
    `conditional_down_payment_required_cents`; a shortfall is refused with
    `ERR_DOWN_PAYMENT_INSUFFICIENT`."
    PRD: "Independently of that, the customer's `outstanding_principal_cents` plus the
    principal this loan would carry must be less than or equal to their
    `credit_limit_cents`, or the origination is refused with
    `ERR_CREDIT_LIMIT_EXCEEDED`"
    PRD band 11: "the conditional down payment (`ERR_DOWN_PAYMENT_INSUFFICIENT`, 422,
    on origination); the customer credit limit (`ERR_CREDIT_LIMIT_EXCEEDED`, 422, on
    origination)"

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_down_payment_insufficient_on_origination
    """
    model, customer, application = _subprime_conditional_application()

    response = api_client.create_loan(
        create_loan_payload(application["id"], imei=next_imei(), down_payment_cents=9_899),
        make_associate_headers(ASSOCIATE_USER_ID))
    validate_error(response, ApiErrorId.ERR_DOWN_PAYMENT_INSUFFICIENT.value)

    rows, meta = validate_paginated(
        api_client.list_loans(make_associate_headers(), {"customer_id": customer["id"]}))
    assert meta["total_count"] == 0, meta["total_count"]
    still_open = validate_success(
        api_client.get_credit_application(application["id"], make_associate_headers()))
    assert still_open["status"] == "CONDITIONAL_APPROVED", still_open["status"]


def test_origination_succeeds_at_exactly_the_conditional_down_payment():
    """One cent more — the exact `conditional_down_payment_required_cents` — clears
    both fiscal checks and books the loan, proving the two refusals above were caused
    by the boundary and not by anything else in the payload.

    PRD: "The financed `principal_cents` is therefore simply the model's
    `retail_price_cents` less the collected `down_payment_cents`."
    PRD: "`monthly_installment_cents` is the base monthly principal component (derived
    just below) plus the monthly premium, which is what the customer is told they will
    pay each month — with the caveat that the final installment may differ from it by
    the principal residual."
    PRD: "First a base principal component is derived: the loan's `principal_cents`
    divided by its `term_months`, rounded half up to whole cents."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_down_payment_insufficient_on_origination
    """
    model, customer, application = _subprime_conditional_application()

    loan = validate_success(api_client.create_loan(
        create_loan_payload(application["id"], imei=next_imei(), down_payment_cents=9_900),
        make_associate_headers(ASSOCIATE_USER_ID)), 201)

    assert loan["down_payment_cents"] == 9_900, loan["down_payment_cents"]
    assert loan["principal_cents"] == 80_000, loan["principal_cents"]
    assert loan["term_months"] == 24, loan["term_months"]
    assert loan["monthly_protection_premium_cents"] == 999
    assert loan["premium_total_cents"] == 23_976, loan["premium_total_cents"]
    assert loan["monthly_installment_cents"] == 4_332, loan["monthly_installment_cents"]
    assert loan["obligation_balance_cents"] == 103_976, loan["obligation_balance_cents"]
    assert loan["origination_fee_cents"] == 0
    assert loan["rolled_over_balance_cents"] == 0
    assert loan["predecessor_loan_id"] is None
    assert loan["status"] == "ACTIVE" and loan["delinquency_state"] == "CURRENT"
    assert loan["version"] == 1, loan["version"]
    assert_loan_ledger_invariants(loan)

    installments = read_installments(loan["id"])
    assert len(installments) == 24, len(installments)
    assert installments[0]["principal_component_cents"] == 3_333
    assert installments[0]["amount_due_cents"] == 4_332
    assert installments[23]["principal_component_cents"] == 3_341
    assert installments[23]["amount_due_cents"] == 4_340
    assert sum(row["principal_component_cents"] for row in installments) == 80_000

    originated = validate_success(
        api_client.get_credit_application(application["id"], make_associate_headers()))
    assert originated["status"] == "ORIGINATED", originated["status"]
    after_customer = read_customer(customer["id"])
    assert after_customer["outstanding_principal_cents"] == 80_000
    assert after_customer["open_loan_count"] == 1
    rows, meta = validate_paginated(
        api_client.list_loans(make_associate_headers(), {"customer_id": customer["id"]}))
    assert meta["total_count"] == 1, meta["total_count"]


# =========================================================================
# Difficulty/priority_pair_validation_conflict
#   upgrade_window_temporal_gate_beats_model_reservation_capacity
# Band 9 (temporal rules) outranks band 10 (structural business constraints).
# =========================================================================
def _twelve_paid_activated_loan(**kwargs):
    """An activated loan with exactly 12 of 24 installments PAID, booked at whatever
    the logical clock currently reads. One posting of 56,940 cents settles them."""
    ctx = setup_loan_with_paid_installments(12, activate=True, **kwargs)
    assert ctx["posting"]["amount_cents"] == 56_940, ctx["posting"]["amount_cents"]
    assert ctx["loan"]["paid_installment_count"] == 12, ctx["loan"]["paid_installment_count"]
    assert ctx["loan"]["delinquency_state"] == "CURRENT", ctx["loan"]["delinquency_state"]
    return ctx


def test_unopened_upgrade_window_outranks_exhausted_model_capacity():
    """A second borrower whose own upgrade window has not opened, aiming at a target
    model whose single reservation slot is already clashed out, reports
    ERR_UPGRADE_WINDOW_NOT_OPEN — the temporal band is screened before the structural one.

    PRD: "Validation is not a set of independent checks — it is a strict ladder,
    evaluated in ascending priority, and the **first** violation encountered is the
    one reported."
    PRD band 9: "**Temporal rules**, in this internal order: the upgrade window must
    have opened (`ERR_UPGRADE_WINDOW_NOT_OPEN`, 409, on upgrade-request creation)"
    PRD band 10: "**Structural business constraints**, in this internal order:
    target-model reservation capacity (`ERR_MODEL_CAPACITY_EXHAUSTED`, 409, on
    upgrade-request creation)"
    PRD: "The logical clock must have reached the loan's `upgrade_window_opens_at`,
    which sits 330 days after `origination_date`, or the request is refused with
    `ERR_UPGRADE_WINDOW_NOT_OPEN`."

    Design: Difficulty/priority_pair_validation_conflict/upgrade_window_temporal_gate_beats_model_reservation_capacity
    """
    ctx_a = _twelve_paid_activated_loan(
        target_model_overrides={"concurrent_reservation_capacity": 1})
    target_model_id = ctx_a["target_model"]["id"]
    window_open = at_midnight(ctx_a["loan"]["upgrade_window_opens_at"])
    assert_iso_equals(window_open, "2027-06-27T00:00:00Z", "loan A upgrade_window_opens_at")

    set_clock(window_open)
    request_a = open_upgrade_request(ctx_a["loan_id"], target_model_id, window_open,
                                     customer_id=ctx_a["customer_id"])
    assert request_a["status"] == "ELIGIBILITY_PASSED", request_a["status"]
    assert request_a["eligibility_ratio_bps"] == 5_000, request_a["eligibility_ratio_bps"]
    assert_iso_equals(request_a["fulfillment_window_end"], "2027-07-04T00:00:00Z",
                      "request A fulfillment_window_end")
    assert read_device_model(target_model_id)["reserved_slot_count"] == 1

    # Borrower B's loan is booked now, so its own window opens 330 days from today.
    ctx_b = _twelve_paid_activated_loan(with_target_model=False)
    loan_b = ctx_b["loan"]
    assert_iso_equals(loan_b["origination_date"], "2027-06-27T00:00:00Z",
                      "loan B origination_date")
    assert_iso_equals(loan_b["upgrade_window_opens_at"], "2028-05-22T00:00:00Z",
                      "loan B upgrade_window_opens_at")

    # 2027-06-30 sits inside request A's [2027-06-27, 2027-07-04) reservation, so the
    # single capacity slot is exhausted as well.
    clashing_start = plus_days(window_open, 3)
    assert_iso_equals(clashing_start, "2027-06-30T00:00:00Z", "candidate window start")
    response = api_client.create_upgrade_request(
        upgrade_request_payload(ctx_b["loan_id"], target_model_id, clashing_start,
                                loan_b["version"]),
        ctx_b["customer_headers"])
    validate_error(response, ApiErrorId.ERR_UPGRADE_WINDOW_NOT_OPEN.value)

    assert read_device_model(target_model_id)["reserved_slot_count"] == 1
    rows, meta = validate_paginated(api_client.list_upgrade_requests(
        make_associate_headers(), {"loan_id": ctx_b["loan_id"]}))
    assert meta["total_count"] == 0, meta["total_count"]
    assert rows == [], rows
    assert read_loan(ctx_b["loan_id"])["upgrade_hold_flag"] is False


def test_exhausted_model_capacity_surfaces_once_the_upgrade_window_is_open():
    """The control: a borrower whose upgrade window IS open, clashing with the only
    live reservation on the target model, reports the lower-priority
    ERR_MODEL_CAPACITY_EXHAUSTED.

    PRD: "If the number of clashing live reservations is greater than or equal to the
    model's `concurrent_reservation_capacity`, the request is refused with
    `ERR_MODEL_CAPACITY_EXHAUSTED`."
    PRD: "A live request clashes when the candidate's start falls strictly before that
    request's `fulfillment_window_end` **and** that request's
    `fulfillment_window_start` falls strictly before the candidate's end — so windows
    that merely touch, where one ends at the exact instant the other begins, do not
    overlap."

    Design: Difficulty/priority_pair_validation_conflict/upgrade_window_temporal_gate_beats_model_reservation_capacity
    """
    ctx_a = _twelve_paid_activated_loan(
        target_model_overrides={"concurrent_reservation_capacity": 1})
    target_model_id = ctx_a["target_model"]["id"]
    # Borrower C is booked at the same instant as borrower A, so both windows open
    # on 2027-06-27 and only the capacity rule can bite.
    ctx_c = _twelve_paid_activated_loan(with_target_model=False)

    window_open = at_midnight(ctx_a["loan"]["upgrade_window_opens_at"])
    assert_iso_equals(window_open, "2027-06-27T00:00:00Z", "loan A upgrade_window_opens_at")
    assert_iso_equals(ctx_c["loan"]["upgrade_window_opens_at"], "2027-06-27T00:00:00Z",
                      "loan C upgrade_window_opens_at")
    set_clock(window_open)

    open_upgrade_request(ctx_a["loan_id"], target_model_id, window_open,
                         customer_id=ctx_a["customer_id"])
    assert read_device_model(target_model_id)["reserved_slot_count"] == 1

    loan_c = read_loan(ctx_c["loan_id"])
    assert loan_c["paid_installment_count"] == 12, loan_c["paid_installment_count"]
    assert loan_c["delinquency_state"] == "CURRENT", loan_c["delinquency_state"]
    response = api_client.create_upgrade_request(
        upgrade_request_payload(ctx_c["loan_id"], target_model_id,
                                plus_days(window_open, 3), loan_c["version"]),
        ctx_c["customer_headers"])
    validate_error(response, ApiErrorId.ERR_MODEL_CAPACITY_EXHAUSTED.value)

    assert read_device_model(target_model_id)["reserved_slot_count"] == 1
    rows, meta = validate_paginated(api_client.list_upgrade_requests(
        make_associate_headers(), {"loan_id": ctx_c["loan_id"]}))
    assert meta["total_count"] == 0, meta["total_count"]
    assert read_loan(ctx_c["loan_id"])["upgrade_hold_flag"] is False


# =========================================================================
# Difficulty/boundary_precision_check
#   upgrade_paid_installment_count_exactly_twelve_vs_eleven
# =========================================================================
def _eleven_paid_with_a_partial_twelfth():
    """A posting one cent short of twelve installments: 11 land PAID and the twelfth
    stops in PARTIALLY_PAID, so it contributes nothing to `paid_installment_count`."""
    ctx = setup_active_loan(activate=True)
    amount = installment_total_cents(ctx["installments"], 12) - 1
    assert amount == 56_939, amount
    ctx["posting"] = post_payment(ctx["loan_id"], amount, customer_id=ctx["customer_id"])
    ctx["loan"] = read_loan(ctx["loan_id"])
    ctx["installments"] = read_installments(ctx["loan_id"])
    return ctx


def test_eleven_paid_installments_are_refused_by_the_upgrade_threshold():
    """4,583 basis points is one installment short of the gate: the twelfth
    installment is PARTIALLY_PAID at 4,744 of 4,745 cents and counts for nothing.

    PRD: "On a 24-month term the threshold is met by exactly 12 installments in
    `status` `PAID`, and missed by 11, which yields 4,583 basis points and is refused
    with `ERR_UPGRADE_THRESHOLD_NOT_MET`."
    PRD: "Because the count admits only installments in `PAID`, a `PARTIALLY_PAID`
    installment contributes nothing however close to full it is, and late fees and
    overpayments are irrelevant to the ratio entirely."
    PRD: "An installment in `SCHEDULED` that receives a take strictly greater than zero
    and strictly less than its remaining `amount_due_cents` advances
    `SCHEDULED → PARTIALLY_PAID`, its `paid_amount_cents`, `paid_principal_cents` and
    `paid_premium_cents` all rising pro rata."

    Design: Difficulty/boundary_precision_check/upgrade_paid_installment_count_exactly_twelve_vs_eleven
    """
    ctx = _eleven_paid_with_a_partial_twelfth()
    posting = ctx["posting"]
    assert posting["allocated_late_fee_cents"] == 0
    assert posting["allocated_principal_cents"] == 44_951, posting["allocated_principal_cents"]
    assert posting["allocated_premium_cents"] == 11_988, posting["allocated_premium_cents"]
    assert posting["installments_satisfied_count"] == 11, posting["installments_satisfied_count"]
    assert posting["overpayment_cents"] == 0, posting["overpayment_cents"]
    assert_allocation_splits_exactly(posting)

    installments = ctx["installments"]
    assert installments[10]["status"] == "PAID", installments[10]["status"]
    twelfth = installments[11]
    assert twelfth["status"] == "PARTIALLY_PAID", twelfth["status"]
    assert twelfth["paid_amount_cents"] == 4_744, twelfth["paid_amount_cents"]
    assert twelfth["paid_principal_cents"] == 3_745, twelfth["paid_principal_cents"]
    assert twelfth["paid_premium_cents"] == 999, twelfth["paid_premium_cents"]

    loan = ctx["loan"]
    assert loan["paid_installment_count"] == 11, loan["paid_installment_count"]
    assert loan["paid_principal_cents"] == 44_951, loan["paid_principal_cents"]
    assert loan["paid_premium_cents"] == 11_988, loan["paid_premium_cents"]
    assert_loan_matches_schedule(loan, installments)
    assert 11 * 10_000 // 24 == 4_583

    set_clock(at_midnight(loan["upgrade_window_opens_at"]))
    loan = read_loan(ctx["loan_id"])
    response = api_client.create_upgrade_request(
        upgrade_request_payload(ctx["loan_id"], ctx["target_model"]["id"],
                                at_midnight(loan["upgrade_window_opens_at"]),
                                loan["version"]),
        ctx["customer_headers"])
    validate_error(response, ApiErrorId.ERR_UPGRADE_THRESHOLD_NOT_MET.value)

    rows, meta = validate_paginated(api_client.list_upgrade_requests(
        make_associate_headers(), {"loan_id": ctx["loan_id"]}))
    assert meta["total_count"] == 0, meta["total_count"]
    assert read_device_model(ctx["target_model"]["id"])["reserved_slot_count"] == 0


def test_twelfth_installment_closed_by_one_cent_meets_the_upgrade_threshold_exactly():
    """One more cent drives the twelfth installment to PAID, lifting the ratio to
    exactly 5,000 basis points, and the same request is now accepted.

    PRD: "On a 24-month term the threshold is met by exactly 12 installments in
    `status` `PAID`, and missed by 11, which yields 4,583 basis points and is refused
    with `ERR_UPGRADE_THRESHOLD_NOT_MET`."
    PRD: "That figure must be at least 5,000 basis points — half the schedule."
    PRD: "The second bucket is arrears: every installment whose `status` is `PAST_DUE`
    or `PARTIALLY_PAID`, again in ascending `installment_number`, each needing its
    `amount_due_cents` less its `paid_amount_cents`."

    Design: Difficulty/boundary_precision_check/upgrade_paid_installment_count_exactly_twelve_vs_eleven
    """
    ctx = _eleven_paid_with_a_partial_twelfth()
    set_clock(at_midnight(ctx["loan"]["upgrade_window_opens_at"]))

    topup = post_payment(ctx["loan_id"], 1, customer_id=ctx["customer_id"])
    assert topup["amount_cents"] == 1, topup["amount_cents"]
    assert topup["allocated_principal_cents"] == 1, topup["allocated_principal_cents"]
    assert topup["allocated_premium_cents"] == 0, topup["allocated_premium_cents"]
    assert topup["allocated_late_fee_cents"] == 0
    assert topup["installments_satisfied_count"] == 1, topup["installments_satisfied_count"]
    assert topup["overpayment_cents"] == 0, topup["overpayment_cents"]

    installments = read_installments(ctx["loan_id"])
    twelfth = installments[11]
    assert twelfth["status"] == "PAID", twelfth["status"]
    assert twelfth["paid_amount_cents"] == 4_745, twelfth["paid_amount_cents"]

    loan = read_loan(ctx["loan_id"])
    assert loan["paid_installment_count"] == 12, loan["paid_installment_count"]
    assert loan["paid_principal_cents"] == 44_952, loan["paid_principal_cents"]
    assert loan["paid_premium_cents"] == 11_988, loan["paid_premium_cents"]
    assert loan["delinquency_state"] == "CURRENT", loan["delinquency_state"]
    assert_loan_matches_schedule(loan, installments)

    window_start = at_midnight(loan["upgrade_window_opens_at"])
    request = validate_success(api_client.create_upgrade_request(
        upgrade_request_payload(ctx["loan_id"], ctx["target_model"]["id"],
                                window_start, loan["version"]),
        ctx["customer_headers"]), 201)
    assert_upgrade_request(request)
    assert request["status"] == "ELIGIBILITY_PASSED", request["status"]
    assert request["eligibility_ratio_bps"] == UPGRADE_PAID_RATIO_BPS
    assert request["eligibility_ratio_bps"] == 5_000, request["eligibility_ratio_bps"]
    assert request["paid_installment_count_at_request"] == 12
    assert_iso_equals(request["fulfillment_window_start"], window_start,
                      "fulfillment_window_start")
    assert_iso_equals(request["fulfillment_window_end"], "2027-07-04T00:00:00Z",
                      "fulfillment_window_end")
    assert read_device_model(ctx["target_model"]["id"])["reserved_slot_count"] == 1
    assert read_loan(ctx["loan_id"])["upgrade_hold_flag"] is True


# =========================================================================
# Difficulty/boundary_precision_check
#   default_declared_at_dpd_ninety_not_eighty_nine
# =========================================================================
def test_loan_is_still_delinquent_at_eighty_nine_days_past_due():
    """One day below the threshold the loan is DELINQUENT, not DEFAULT: protection
    stays ACTIVE, the customer is untouched, and three installments have each been
    charged a single 500-cent fee.

    PRD: "From 11 days past due up to but not including 90 the loan is `DELINQUENT`.
    At 90 days past due or more the loan is `DEFAULT`."
    PRD: "Otherwise `days_past_due` is the largest whole-day difference between the
    logical clock's UTC calendar date and the UTC calendar date of any installment in
    that set — that is, the age of the *oldest* unsatisfied past-due installment."
    PRD: "If that figure is strictly greater than the 10-day grace period and the
    installment's `late_fee_assessed` is still false, the sweep sets
    `late_fee_assessed` to true, writes 500 into the installment's `late_fee_cents`,
    and adds 500 to the loan's `outstanding_late_fee_cents`."

    Design: Difficulty/boundary_precision_check/default_declared_at_dpd_ninety_not_eighty_nine
    """
    ctx = setup_active_loan()
    # Installment 1 falls due 2026-09-01; 89 days later is 2026-11-29, by which point
    # installments 1, 2 and 3 are all unsatisfied and all more than 10 days overdue.
    advance_to_dpd(ctx, DEFAULT_MIN_DPD - 1, installment_number=1)

    sweep = ctx["sweep"]
    assert sweep["processed_loan_count"] == 1, sweep["processed_loan_count"]
    assert sweep["transitioned_loan_count"] == 1, sweep["transitioned_loan_count"]
    assert sweep["defaulted_loan_count"] == 0, sweep["defaulted_loan_count"]
    assert sweep["late_fees_assessed_cents"] == 3 * LATE_FEE_CENTS, (
        sweep["late_fees_assessed_cents"])
    assert sweep["late_fees_assessed_cents"] == 1_500

    loan = ctx["loan"]
    assert loan["delinquency_state"] == "DELINQUENT", loan["delinquency_state"]
    assert loan["days_past_due"] == 89, loan["days_past_due"]
    assert loan["status"] == "ACTIVE", loan["status"]
    assert loan["protection_coverage_status"] == "ACTIVE", loan["protection_coverage_status"]
    assert loan["outstanding_late_fee_cents"] == 1_500, loan["outstanding_late_fee_cents"]
    assert loan["obligation_balance_cents"] == 115_376, loan["obligation_balance_cents"]
    assert_loan_ledger_invariants(loan)
    assert 89 >= DELINQUENT_MIN_DPD and 89 < DEFAULT_MIN_DPD

    installments = ctx["installments"]
    for index in range(3):
        row = installments[index]
        assert row["status"] == "PAST_DUE", (index + 1, row["status"])
        assert row["late_fee_assessed"] is True, index + 1
        assert row["late_fee_cents"] == 500, (index + 1, row["late_fee_cents"])
    assert installments[3]["status"] == "SCHEDULED", installments[3]["status"]
    assert installments[3]["late_fee_assessed"] is False
    assert installments[3]["late_fee_cents"] == 0

    customer = read_customer(ctx["customer_id"])
    assert customer["status"] == "ACTIVE", customer["status"]
    assert customer["financing_lock_reason"] is None, customer["financing_lock_reason"]
    assert customer["financing_locked_at"] is None, customer["financing_locked_at"]
    assert customer["default_strike_count"] == 0, customer["default_strike_count"]
    assert read_delinquency_events(
        ctx["loan_id"], params={"event_type": "DEFAULT_DECLARED"}) == []


def test_default_cascade_fires_at_exactly_ninety_days_past_due():
    """The ninetieth day flips the label to DEFAULT and fires the cascade — protection
    SUSPENDED, the borrower FINANCING_LOCKED on DEFAULTED_LOAN with one strike — while
    no installment is charged a second fee.

    PRD: "From 11 days past due up to but not including 90 the loan is `DELINQUENT`.
    At 90 days past due or more the loan is `DEFAULT`."
    PRD: "On the loan itself, `protection_coverage_status` moves from `ACTIVE` to
    `SUSPENDED` — the bundled device protection stops covering the handset while the
    account is in default — and a `DEFAULT_DECLARED` event is appended."
    PRD: "Then: **first**, because the loan reached `DEFAULT`, the borrower's `status`
    becomes `FINANCING_LOCKED` with `financing_lock_reason` set to `DEFAULTED_LOAN` and
    `financing_locked_at` stamped from the logical clock, the customer's
    `default_strike_count` is increased by one, and a `FINANCING_LOCK_APPLIED` event is
    appended."
    PRD: "Each installment can be charged at most once; the fee is not re-assessed
    after a reversal re-opens an installment."

    Design: Difficulty/boundary_precision_check/default_declared_at_dpd_ninety_not_eighty_nine
    """
    ctx = setup_active_loan()
    advance_to_dpd(ctx, DEFAULT_MIN_DPD - 1, installment_number=1)
    assert ctx["loan"]["delinquency_state"] == "DELINQUENT", ctx["loan"]["delinquency_state"]

    advance_to_dpd(ctx, DEFAULT_MIN_DPD, installment_number=1)
    sweep = ctx["sweep"]
    assert sweep["defaulted_loan_count"] == 1, sweep["defaulted_loan_count"]
    assert sweep["transitioned_loan_count"] == 1, sweep["transitioned_loan_count"]
    assert sweep["late_fees_assessed_cents"] == 0, sweep["late_fees_assessed_cents"]

    loan = ctx["loan"]
    assert loan["delinquency_state"] == "DEFAULT", loan["delinquency_state"]
    assert loan["days_past_due"] == 90, loan["days_past_due"]
    assert loan["status"] == "ACTIVE", loan["status"]
    assert loan["protection_coverage_status"] == "SUSPENDED", loan["protection_coverage_status"]
    assert loan["outstanding_late_fee_cents"] == 1_500, loan["outstanding_late_fee_cents"]
    assert loan["obligation_balance_cents"] == 115_376, loan["obligation_balance_cents"]
    assert_loan_ledger_invariants(loan)

    installments = ctx["installments"]
    for index in range(3):
        assert installments[index]["late_fee_cents"] == 500, index + 1
    assert installments[3]["status"] == "SCHEDULED", installments[3]["status"]
    assert installments[3]["late_fee_assessed"] is False

    customer = read_customer(ctx["customer_id"])
    assert customer["status"] == "FINANCING_LOCKED", customer["status"]
    assert customer["financing_lock_reason"] == "DEFAULTED_LOAN", customer["financing_lock_reason"]
    assert customer["default_strike_count"] == 1, customer["default_strike_count"]
    assert_iso_equals(customer["financing_locked_at"], "2026-11-30T00:00:00Z",
                      "financing_locked_at")

    events = read_delinquency_events(ctx["loan_id"], params={"event_type": "DEFAULT_DECLARED"})
    assert len(events) == 1, events
    assert events[0]["days_past_due_at_event"] == 90, events[0]["days_past_due_at_event"]
    assert events[0]["from_state"] == "DELINQUENT", events[0]["from_state"]
    assert events[0]["to_state"] == "DEFAULT", events[0]["to_state"]
    assert events[0]["amount_cents"] == 0, events[0]["amount_cents"]
    assert_iso_equals(events[0]["occurred_at"], "2026-11-30T00:00:00Z", "occurred_at")


# =========================================================================
# Difficulty/boundary_precision_check
#   rollover_net_shortfall_boundary_at_thirty_thousand_limit
# =========================================================================
def _rollover_with_a_five_thousand_fourteen_cent_shortfall():
    """A graded trade-in whose final credit leaves the request 5,014 cents above the
    30,000-cent carry-forward ceiling, so the boundary can be probed from either side.

    The UPGRADE_ROLLOVER quote is priced before the trade-in is declared, so every
    refresh of the funding projection has the same live rollover payoff to work from.
    """
    ctx = setup_upgrade_request(paid_count=12,
                                model_overrides={"trade_in_base_credit_cents": 12_000})
    assert ctx["model"]["trade_in_base_credit_cents"] == 12_000
    assert ctx["target_model"]["retail_price_cents"] == 119_900
    assert ctx["target_model"]["monthly_protection_premium_cents"] == 1_199

    quote = price_quote(ctx["loan_id"], "UPGRADE_ROLLOVER", customer_id=ctx["customer_id"])
    # remaining principal 89,900 - 44,952 = 44,948; rule-of-78 unearned premium
    # 23,976 * 12 * 13 / (24 * 25) = 6,234; admin fee 0 on a rollover.
    assert quote["quote_type"] == "UPGRADE_ROLLOVER", quote["quote_type"]
    assert quote["remaining_principal_cents"] == 44_948, quote["remaining_principal_cents"]
    assert quote["unearned_premium_cents"] == 6_234, quote["unearned_premium_cents"]
    assert quote["premium_rebate_cents"] == 6_234, quote["premium_rebate_cents"]
    assert quote["admin_fee_cents"] == 0, quote["admin_fee_cents"]
    assert quote["total_payoff_cents"] == 38_714, quote["total_payoff_cents"]
    ctx["quote"] = quote

    trade_in = declare_trade_in(ctx["upgrade_request_id"], ctx["device_id"], "GOOD",
                               customer_id=ctx["customer_id"])
    assert trade_in["credit_estimate_cents"] == 10_200, trade_in["credit_estimate_cents"]
    ctx["trade_in_id"] = trade_in["id"]
    receive_trade_in(ctx["trade_in_id"])
    ctx["report"] = grade_trade_in(ctx["trade_in_id"], screen_grade="SCRATCHED",
                                  battery_health_pct=78)
    ctx["trade_in"] = read_trade_in(ctx["trade_in_id"])
    ctx["upgrade_request"] = read_upgrade_request(ctx["upgrade_request_id"])
    ctx["loan"] = read_loan(ctx["loan_id"])
    return ctx


def test_rollover_one_cent_above_the_carry_forward_ceiling_is_refused():
    """A net rollover of 30,001 cents — one cent above the ceiling — is refused with
    ERR_ROLLOVER_SHORTFALL_EXCEEDS_LIMIT and nothing in the chain moves.

    PRD: "Where the net rollover exceeds the program's carry-forward ceiling of 30,000
    cents, completion is refused outright with `ERR_ROLLOVER_SHORTFALL_EXCEEDS_LIMIT`"
    PRD: "The gross rollover is the quote's `total_payoff_cents` less the trade-in's
    `credit_final_cents`, floored at zero."
    PRD: "The net rollover is the gross rollover less `additional_down_payment_cents`,
    floored at zero, so a down payment larger than the shortfall is simply absorbed and
    never turns into a credit."

    Design: Difficulty/boundary_precision_check/rollover_net_shortfall_boundary_at_thirty_thousand_limit
    """
    ctx = _rollover_with_a_five_thousand_fourteen_cent_shortfall()

    report = ctx["report"]
    assert report["diagnostic_result"] == "PASS", report["diagnostic_result"]
    assert report["derived_condition"] == "GOOD", report["derived_condition"]
    assert report["condition_multiplier_bps"] == 8_500
    assert report["screen_deduction_cents"] == 2_500
    assert report["battery_deduction_cents"] == 4_000
    assert report["computed_credit_cents"] == 3_700, report["computed_credit_cents"]

    trade_in = ctx["trade_in"]
    assert trade_in["status"] == "GRADED", trade_in["status"]
    assert trade_in["credit_final_cents"] == 3_700, trade_in["credit_final_cents"]
    assert trade_in["credit_variance_cents"] == -6_500, trade_in["credit_variance_cents"]

    request = ctx["upgrade_request"]
    assert_upgrade_request(request)
    assert request["status"] == "TRADE_IN_GRADED", request["status"]
    assert request["trade_in_credit_projection_cents"] == 3_700
    assert request["projected_rollover_balance_cents"] == 35_014, (
        request["projected_rollover_balance_cents"])
    assert request["credit_shortfall_cents"] == 5_014, request["credit_shortfall_cents"]
    assert request["funding_flag"] == "REQUIRES_DOWN_PAYMENT", request["funding_flag"]
    assert 35_014 - 5_013 == ROLLOVER_SHORTFALL_LIMIT_CENTS + 1

    response = api_client.complete_upgrade(
        ctx["upgrade_request_id"],
        completion_payload(ctx["quote"]["id"], target_imei=next_imei(),
                           additional_down_payment_cents=5_013),
        make_associate_headers())
    validate_error(response, ApiErrorId.ERR_ROLLOVER_SHORTFALL_EXCEEDS_LIMIT.value)

    assert read_upgrade_request(ctx["upgrade_request_id"])["status"] == "TRADE_IN_GRADED"
    assert read_trade_in(ctx["trade_in_id"])["status"] == "GRADED"
    still_active = read_loan(ctx["loan_id"])
    assert still_active["status"] == "ACTIVE", still_active["status"]
    assert still_active["closure_reason"] is None, still_active["closure_reason"]
    quotes = validate_paginated(api_client.list_loan_payoff_quotes(
        ctx["loan_id"], make_associate_headers(), {"quote_type": "UPGRADE_ROLLOVER"}))[0]
    assert [row["status"] for row in quotes] == ["ISSUED"], quotes
    rows, meta = validate_paginated(api_client.list_loans(
        make_associate_headers(), {"predecessor_loan_id": ctx["loan_id"]}))
    assert meta["total_count"] == 0, meta["total_count"]
    assert rows == [], rows


def test_rollover_exactly_on_the_carry_forward_ceiling_completes():
    """One cent more of down payment lands the net rollover on exactly 30,000 cents —
    which does not exceed the ceiling — and the successor loan is minted carrying it.

    PRD: "Where the net rollover exceeds the program's carry-forward ceiling of 30,000
    cents, completion is refused outright with `ERR_ROLLOVER_SHORTFALL_EXCEEDS_LIMIT`"
    PRD: "The pre-fee base is then the target model's `retail_price_cents`, plus the net
    rollover, minus the excess credit — the new handset's sticker price, carrying forward
    whatever the old loan still owed and giving back whatever the trade-in over-covered."
    PRD: "The origination fee for the successor loan is tiered off that pre-fee base and
    nothing else: `origination_fee_cents` is 0 when the pre-fee base is below 60,000
    cents, 1,500 cents when it is below 100,000 cents, and 2,500 cents otherwise."
    PRD: "The successor loan's `principal_cents` is the pre-fee base plus that fee, and
    its `rolled_over_balance_cents` records the net rollover so the carried-forward debt
    stays visible on the new agreement."

    Design: Difficulty/boundary_precision_check/rollover_net_shortfall_boundary_at_thirty_thousand_limit
    """
    ctx = _rollover_with_a_five_thousand_fourteen_cent_shortfall()
    assert 35_014 - 5_014 == ROLLOVER_SHORTFALL_LIMIT_CENTS

    new_loan = validate_success(api_client.complete_upgrade(
        ctx["upgrade_request_id"],
        completion_payload(ctx["quote"]["id"], target_imei=next_imei(),
                           additional_down_payment_cents=5_014),
        make_associate_headers()), 201)

    # pre-fee base 119,900 + 30,000 - 0 = 149,900 -> fee tier 2,500 -> principal 152,400
    assert new_loan["rolled_over_balance_cents"] == 30_000, new_loan["rolled_over_balance_cents"]
    assert new_loan["origination_fee_cents"] == 2_500, new_loan["origination_fee_cents"]
    assert new_loan["principal_cents"] == 152_400, new_loan["principal_cents"]
    assert new_loan["term_months"] == 24, new_loan["term_months"]
    assert new_loan["monthly_protection_premium_cents"] == 1_199
    assert new_loan["premium_total_cents"] == 28_776, new_loan["premium_total_cents"]
    assert new_loan["monthly_installment_cents"] == 7_549, new_loan["monthly_installment_cents"]
    assert new_loan["obligation_balance_cents"] == 181_176, new_loan["obligation_balance_cents"]
    assert new_loan["predecessor_loan_id"] == ctx["loan_id"], new_loan["predecessor_loan_id"]
    assert new_loan["device_model_id"] == ctx["target_model"]["id"]
    assert new_loan["status"] == "ACTIVE" and new_loan["delinquency_state"] == "CURRENT"
    assert_loan_ledger_invariants(new_loan)

    new_installments = read_installments(new_loan["id"])
    assert len(new_installments) == 24, len(new_installments)
    assert new_installments[0]["principal_component_cents"] == 6_350
    assert new_installments[23]["principal_component_cents"] == 6_350
    assert new_installments[0]["amount_due_cents"] == 7_549
    assert sum(row["principal_component_cents"] for row in new_installments) == 152_400

    request = read_upgrade_request(ctx["upgrade_request_id"])
    assert request["status"] == "COMPLETED", request["status"]
    assert request["additional_down_payment_cents"] == 5_014
    assert request["new_loan_id"] == new_loan["id"], request["new_loan_id"]
    assert request["payoff_quote_id"] == ctx["quote"]["id"]

    predecessor = read_loan(ctx["loan_id"])
    assert predecessor["status"] == "ROLLED_OVER", predecessor["status"]
    assert predecessor["closure_reason"] == "UPGRADE_ROLLOVER", predecessor["closure_reason"]
    assert read_trade_in(ctx["trade_in_id"])["status"] == "SETTLED"
    rows, meta = validate_paginated(api_client.list_loans(
        make_associate_headers(), {"predecessor_loan_id": ctx["loan_id"]}))
    assert meta["total_count"] == 1, meta["total_count"]
    assert rows[0]["id"] == new_loan["id"], rows[0]["id"]


# =========================================================================
# Difficulty/boundary_precision_check
#   payoff_quote_on_zero_payments_empty_past_due_set
# =========================================================================
def test_early_cancellation_quote_degenerates_cleanly_on_zero_payments():
    """Priced against a loan with no payment and no sweep, every summed field
    collapses to its empty-set value while the pro-rata rebate still bites.

    PRD: "`past_due_amount_cents` is the sum, over the loan's installments whose
    `status` is `PAST_DUE` or `PARTIALLY_PAID` and whose `due_date` is at or before the
    logical clock, of each one's `amount_due_cents` less its `paid_amount_cents` — and
    this figure is **disclosure only**."
    PRD: "`unearned_premium_cents` is the total premium less the loan's
    `paid_premium_cents` — a straight-line unexpired figure."
    PRD: "`premium_rebate_cents` is then 9,000 basis points of that, or 90 percent,
    rounded half up to whole cents; the withheld 10 percent is the program's
    cancellation retention haircut."
    PRD: "`total_payoff_cents` is then `remaining_principal_cents` plus
    `outstanding_late_fee_cents` plus `admin_fee_cents`, less `premium_rebate_cents`."
    PRD: "`issued_at` is stamped from the logical clock, and `expires_at` is set 7 days
    later, with validity treated as the half-open interval beginning at `issued_at` and
    ending immediately before `expires_at`."

    Design: Difficulty/boundary_precision_check/payoff_quote_on_zero_payments_empty_past_due_set
    """
    ctx = setup_active_loan()
    assert ctx["loan"]["version"] == 1, ctx["loan"]["version"]
    assert ctx["loan"]["paid_installment_count"] == 0

    quote = price_quote(ctx["loan_id"], "EARLY_CANCELLATION", customer_id=ctx["customer_id"])
    assert_payoff_quote(quote)
    assert quote["quote_type"] == "EARLY_CANCELLATION", quote["quote_type"]
    assert quote["status"] == "ISSUED", quote["status"]
    assert quote["consumed_at"] is None, quote["consumed_at"]
    assert quote["remaining_principal_cents"] == 89_900, quote["remaining_principal_cents"]
    assert quote["outstanding_late_fee_cents"] == 0, quote["outstanding_late_fee_cents"]
    assert quote["past_due_amount_cents"] == 0, quote["past_due_amount_cents"]
    assert quote["paid_installment_count_at_quote"] == 0
    assert quote["unearned_premium_cents"] == MODEL_B_PREMIUM_TOTAL_CENTS
    assert quote["unearned_premium_cents"] == 23_976, quote["unearned_premium_cents"]
    assert quote["premium_rebate_cents"] == 21_578, quote["premium_rebate_cents"]
    assert quote["admin_fee_cents"] == 2_500, quote["admin_fee_cents"]
    assert quote["total_payoff_cents"] == 70_822, quote["total_payoff_cents"]
    assert 89_900 + 0 + 2_500 - 21_578 == 70_822
    assert_iso_equals(quote["issued_at"], "2026-08-01T00:00:00Z", "issued_at")
    assert_iso_equals(quote["expires_at"], "2026-08-08T00:00:00Z", "expires_at")
    assert_iso_equals(quote["expires_at"], plus_days(quote["issued_at"], 7), "expires_at")

    loan = read_loan(ctx["loan_id"])
    assert loan["version"] == 2, loan["version"]
    assert loan["status"] == "ACTIVE", loan["status"]
    assert loan["delinquency_state"] == "CURRENT", loan["delinquency_state"]
    assert loan["days_past_due"] == 0, loan["days_past_due"]
    assert loan["paid_installment_count"] == 0
    assert loan["obligation_balance_cents"] == 113_876, loan["obligation_balance_cents"]


def test_past_due_amount_is_disclosed_but_never_added_to_the_payoff_total():
    """The just-outside case for the empty past-due set: one aged installment makes
    `past_due_amount_cents` non-zero, yet the total moves only by the late fee.

    PRD: "It tells the customer how much of the settlement is arrears rather than future
    obligation, and it is deliberately *not* added into the total, because the body of
    those arrears already sits inside `remaining_principal_cents`; only the late fee sits
    outside it."
    PRD: "`total_payoff_cents` is then `remaining_principal_cents` plus
    `outstanding_late_fee_cents` plus `admin_fee_cents`, less `premium_rebate_cents`."
    PRD: "`admin_fee_cents` is 2,500 cents on an `EARLY_CANCELLATION` quote and zero on
    an `UPGRADE_ROLLOVER` quote — leaving the program costs an administration charge,
    upgrading within it does not."

    Design: Difficulty/boundary_precision_check/payoff_quote_on_zero_payments_empty_past_due_set
    """
    ctx = setup_active_loan()
    advance_to_dpd(ctx, DELINQUENT_MIN_DPD, installment_number=1)
    assert ctx["loan"]["delinquency_state"] == "DELINQUENT", ctx["loan"]["delinquency_state"]
    assert ctx["loan"]["days_past_due"] == 11, ctx["loan"]["days_past_due"]
    assert ctx["loan"]["outstanding_late_fee_cents"] == 500
    assert ctx["installments"][0]["status"] == "PAST_DUE", ctx["installments"][0]["status"]
    assert ctx["installments"][1]["status"] == "SCHEDULED", ctx["installments"][1]["status"]

    quote = price_quote(ctx["loan_id"], "EARLY_CANCELLATION", customer_id=ctx["customer_id"])
    assert quote["past_due_amount_cents"] == MODEL_B_MONTHLY_INSTALLMENT_CENTS
    assert quote["past_due_amount_cents"] == 4_745, quote["past_due_amount_cents"]
    assert quote["remaining_principal_cents"] == 89_900, quote["remaining_principal_cents"]
    assert quote["outstanding_late_fee_cents"] == 500, quote["outstanding_late_fee_cents"]
    assert quote["paid_installment_count_at_quote"] == 0
    assert quote["unearned_premium_cents"] == 23_976, quote["unearned_premium_cents"]
    assert quote["premium_rebate_cents"] == 21_578, quote["premium_rebate_cents"]
    assert quote["admin_fee_cents"] == 2_500, quote["admin_fee_cents"]
    assert quote["total_payoff_cents"] == 71_322, quote["total_payoff_cents"]
    assert 89_900 + 500 + 2_500 - 21_578 == 71_322
    # The arrears body is disclosed only: adding it would have produced 76,067.
    assert quote["total_payoff_cents"] != 71_322 + 4_745

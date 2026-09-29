"""Cross-entity state gates, temporal-overlap semantics and compensating invariants.

Three families of behaviour are proved here, all against a live API and an empty
database whose logical clock starts at 2026-08-01T00:00:00Z:

* **Cross-entity gates** — an operation on one entity is refused because a *second*
  entity is in the wrong state, and the identical call succeeds once only that
  second entity is corrected. Both directions assert the exact `error_id`.
* **Temporal overlap** — the fulfillment window is the half-open interval
  ``[start, start + 7 days)``, so windows that merely touch at an endpoint do not
  clash, and `reserved_slot_count` is not the capacity test. Payoff-quote validity
  is the half-open interval ``[issued_at, expires_at)``.
* **Compensating invariants** — the full ledger position is captured before the
  compensating event and byte-for-byte restoration is asserted afterwards, with
  zero drift in any cents field and no residue in any counter.
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
    FULFILLMENT_WINDOW_DAYS,
    GRACE_PERIOD_DAYS,
    MODEL_B_LOAN_PRINCIPAL_CENTS,
    MODEL_B_MONTHLY_INSTALLMENT_CENTS,
    MODEL_B_OBLIGATION_BALANCE_CENTS,
    MODEL_B_PREMIUM_TOTAL_CENTS,
    UNLOCK_MIN_PAID_INSTALLMENTS,
    QUOTE_VALIDITY_DAYS,
    UPGRADE_PAID_RATIO_BPS,
    at_midnight,
    plus_days,
    # factories
    cancellation_payload,
    create_credit_application_payload,
    upgrade_request_payload,
    # fixtures
    activate_device,
    advance_to_dpd,
    decide_application,
    declare_trade_in,
    enroll_customer,
    installment_total_cents,
    loan_device_unit,
    open_upgrade_request,
    originate_loan,
    post_payment,
    post_reversal,
    price_quote,
    publish_model,
    publish_target_model,
    read_carrier_accounts,
    read_customer,
    read_device_model,
    read_device_unit,
    read_installment,
    read_installments,
    read_loan,
    read_trade_in,
    read_upgrade_request,
    register_carrier_account,
    run_sweep,
    set_clock,
    setup_active_loan,
    setup_loan_with_paid_installments,
    setup_trade_in_declared,
    setup_upgrade_ready,
    submit_application,
    # assertions
    assert_allocation_splits_exactly,
    assert_iso_equals,
    assert_ledger_positions_equal,
    assert_loan_ledger_invariants,
    assert_loan_matches_schedule,
    assert_upgrade_request,
    assert_version_advanced_by,
    # identities
    make_associate_headers,
    make_collections_headers,
    make_customer_headers,
)

PAID_HALF_COUNT = 12
CURED_LATE_FEE_TOTAL_CENTS = 1500
EARLY_CANCELLATION_TOTAL_AT_HALF_TERM_CENTS = 36659


def _carrier_account(customer_id, carrier_account_id):
    """Re-read one carrier account through its customer's sub-collection."""
    for row in read_carrier_accounts(customer_id):
        if row["id"] == carrier_account_id:
            return row
    raise AssertionError(f"carrier account {carrier_account_id} vanished")


def _two_borrowers_sharing_one_target_model(capacity):
    """Publish ONE financed model and ONE target model of the given capacity, then
    walk two independent borrowers to `PAID_HALF_COUNT` paid installments each.

    The stock composite fixtures publish a fresh target model per call, so a test
    that needs two customers competing for the *same* reservation pool has to build
    the chain here. Both loans originate at the untouched clock 2026-08-01, so they
    share an `upgrade_window_opens_at`; the clock is moved to it only after every
    payment has landed, which keeps both schedules clean of arrears.
    """
    model = publish_model()
    target_model = publish_target_model(concurrent_reservation_capacity=capacity)
    borrowers = []
    for _ in range(2):
        customer = enroll_customer()
        customer_id = customer["id"]
        application = submit_application(customer_id, model["id"], requested_term_months=24)
        application = decide_application(application["id"], "PRIME")
        loan = originate_loan(application["id"])
        device = loan_device_unit(loan["id"])
        carrier = register_carrier_account(customer_id)
        device = activate_device(device["id"], carrier["id"])
        installments = read_installments(loan["id"])
        post_payment(loan["id"], installment_total_cents(installments, PAID_HALF_COUNT),
                     customer_id=customer_id)
        borrowers.append({
            "customer_id": customer_id,
            "customer_headers": make_customer_headers(customer_id),
            "loan_id": loan["id"],
            "device_id": device["id"],
        })
    window_start = at_midnight(read_loan(borrowers[0]["loan_id"])["upgrade_window_opens_at"])
    set_clock(window_start)
    return model, target_model, borrowers, window_start


# =========================================================================
# cross_entity_state_dependency / upgrade_request_requires_device_unit_activated
# =========================================================================
def test_upgrade_request_refused_until_the_loans_handset_is_activated():
    """An upgrade request is refused solely because a third entity — the handset the
    payload never names — is UNACTIVATED, and the identical call succeeds once only
    that handset moves.

    PRD: "And the loan's handset must be `ACTIVATED`, since an unactivated handset
    has no carrier relationship to transfer — `ERR_DEVICE_NOT_ACTIVATED`."

    Design: Difficulty/cross_entity_state_dependency/upgrade_request_requires_device_unit_activated
    """
    ctx = setup_upgrade_ready(paid_count=PAID_HALF_COUNT, activate=False)
    loan_before = read_loan(ctx["loan_id"])
    device_before = read_device_unit(ctx["device_id"])

    assert device_before["activation_status"] == "UNACTIVATED"
    assert device_before["unlock_status"] == "LOCKED"
    assert device_before["possession_status"] == "WITH_CUSTOMER"
    assert device_before.get("carrier_account_id") is None
    assert loan_before["paid_installment_count"] == PAID_HALF_COUNT
    assert loan_before["delinquency_state"] == "CURRENT"
    assert loan_before["status"] == "ACTIVE"

    refused = api_client.create_upgrade_request(
        upgrade_request_payload(ctx["loan_id"], ctx["target_model"]["id"],
                                ctx["window_start"], loan_before["version"]),
        ctx["customer_headers"])
    validate_error(refused, ApiErrorId.ERR_DEVICE_NOT_ACTIVATED.value)

    device = activate_device(ctx["device_id"], ctx["carrier"]["id"])
    assert device["activation_status"] == "ACTIVATED"
    assert_iso_equals(device["activated_at"], ctx["window_start"], "DeviceUnit.activated_at")
    carrier = _carrier_account(ctx["customer_id"], ctx["carrier"]["id"])
    assert carrier["activation_state"] == "ACTIVATED"
    assert carrier["active_device_imei"] == device["imei"]

    loan_after_activation = read_loan(ctx["loan_id"])
    assert loan_after_activation["version"] == loan_before["version"], (
        "activating a handset is not one of the six operations that advance a loan's version")

    accepted = api_client.create_upgrade_request(
        upgrade_request_payload(ctx["loan_id"], ctx["target_model"]["id"],
                                ctx["window_start"], loan_after_activation["version"]),
        ctx["customer_headers"])
    request = validate_success(accepted, expected_status=201)
    assert_upgrade_request(request)
    assert request["status"] == "ELIGIBILITY_PASSED"
    assert request["customer_id"] == ctx["customer_id"]
    assert request["eligibility_ratio_bps"] == UPGRADE_PAID_RATIO_BPS
    assert request["paid_installment_count_at_request"] == PAID_HALF_COUNT
    assert read_device_model(ctx["target_model"]["id"])["reserved_slot_count"] == 1
    assert read_loan(ctx["loan_id"])["upgrade_hold_flag"] is True


def test_upgrade_request_refused_for_unactivated_handset_reserves_nothing():
    """The refused upgrade request writes nothing anywhere: no reservation is taken on
    the target model, no hold lands on the loan, and no request row is minted.

    PRD: "On acceptance the target model's `reserved_slot_count` is increased by one,
    and it is decreased by one whenever a reservation is released — on completion, on
    expiry, or on supersession."

    Design: Difficulty/cross_entity_state_dependency/upgrade_request_requires_device_unit_activated
    """
    ctx = setup_upgrade_ready(paid_count=PAID_HALF_COUNT, activate=False)
    loan_before = read_loan(ctx["loan_id"])
    target_before = read_device_model(ctx["target_model"]["id"])
    assert target_before["reserved_slot_count"] == 0
    assert target_before["concurrent_reservation_capacity"] >= 1
    assert loan_before["upgrade_hold_flag"] is False

    refused = api_client.create_upgrade_request(
        upgrade_request_payload(ctx["loan_id"], ctx["target_model"]["id"],
                                ctx["window_start"], loan_before["version"]),
        ctx["customer_headers"])
    validate_error(refused, ApiErrorId.ERR_DEVICE_NOT_ACTIVATED.value)

    target_after = read_device_model(ctx["target_model"]["id"])
    loan_after = read_loan(ctx["loan_id"])
    assert target_after["reserved_slot_count"] == 0
    assert loan_after["upgrade_hold_flag"] is False
    assert loan_after["version"] == loan_before["version"]
    assert_ledger_positions_equal(loan_before, loan_after)

    rows, meta = validate_paginated(api_client.list_upgrade_requests(
        make_associate_headers(), params={"loan_id": ctx["loan_id"]}))
    assert meta["total_count"] == 0
    assert rows == []


# =========================================================================
# cross_entity_state_dependency /
#   unlock_request_requires_loan_paid_count_and_delinquency_state
# =========================================================================
def _activated_loan_standing_at_its_unlock_policy_window(paid_count):
    """An ACTIVATED handset whose loan has `paid_count` installments PAID, with the
    clock standing exactly at `activated_at` + the carrier's `unlock_policy_days`, so
    the carrier waiting period is satisfied and cannot mask the loan-side gates."""
    ctx = setup_loan_with_paid_installments(paid_count, activate=True)
    policy_days = int(ctx["carrier"]["unlock_policy_days"])
    assert policy_days == 60, "unlock_policy_days defaults to 60 when omitted"
    set_clock(plus_days(ctx["device"]["activated_at"], policy_days))
    ctx["device"] = read_device_unit(ctx["device_id"])
    ctx["loan"] = read_loan(ctx["loan_id"])
    return ctx


def test_unlock_refused_below_payment_threshold_then_admitted_at_six_paid_installments():
    """The handset's unlock dimension is gated by a field of its PARENT loan: the same
    empty-bodied call is refused at 5 PAID installments and accepted at 6.

    PRD: "The loan must have at least 6 installments in `status` `PAID` — the program's
    unlock payment threshold — measured by the loan's `paid_installment_count`; below
    that the request is refused with `ERR_UNLOCK_PAYMENT_THRESHOLD_NOT_MET`."

    Design: Difficulty/cross_entity_state_dependency/unlock_request_requires_loan_paid_count_and_delinquency_state
    """
    ctx = _activated_loan_standing_at_its_unlock_policy_window(UNLOCK_MIN_PAID_INSTALLMENTS - 1)
    unlock_clock = plus_days(ctx["device"]["activated_at"], 60)

    assert ctx["loan"]["paid_installment_count"] == UNLOCK_MIN_PAID_INSTALLMENTS - 1
    assert ctx["loan"]["delinquency_state"] == "CURRENT"
    assert ctx["device"]["activation_status"] == "ACTIVATED"
    assert ctx["device"]["unlock_status"] == "LOCKED"

    refused = api_client.request_device_unlock(ctx["device_id"], ctx["customer_headers"])
    validate_error(refused, ApiErrorId.ERR_UNLOCK_PAYMENT_THRESHOLD_NOT_MET.value)
    still_locked = read_device_unit(ctx["device_id"])
    assert still_locked["unlock_status"] == "LOCKED"
    assert still_locked.get("unlock_requested_at") is None

    post_payment(ctx["loan_id"], MODEL_B_MONTHLY_INSTALLMENT_CENTS,
                 customer_id=ctx["customer_id"])
    assert read_loan(ctx["loan_id"])["paid_installment_count"] == UNLOCK_MIN_PAID_INSTALLMENTS

    accepted = api_client.request_device_unlock(ctx["device_id"], ctx["customer_headers"])
    device = validate_success(accepted)
    assert device["unlock_status"] == "UNLOCK_REQUESTED"
    assert_iso_equals(device["unlock_requested_at"], unlock_clock,
                      "DeviceUnit.unlock_requested_at")
    assert device.get("unlocked_at") is None
    carrier = _carrier_account(ctx["customer_id"], ctx["carrier"]["id"])
    assert carrier["activation_state"] == "ACTIVATED", (
        "only UNLOCKED releases the carrier account to PORT_ELIGIBLE")


def test_second_unlock_step_refused_while_loan_is_in_grace_then_admitted_after_cure():
    """The second leg of the unlock ladder carries no delinquency precondition of its
    own, yet a loan aged into GRACE still refuses it — and curing the arrears re-opens
    the very same call, which then also releases the carrier account.

    PRD: "The loan's `delinquency_state` must be `CURRENT`; a loan sitting in `GRACE`,
    `DELINQUENT` or `DEFAULT` is under the device financing lock and its unlock request
    is refused with `ERR_LOAN_DELINQUENT`."

    Design: Difficulty/cross_entity_state_dependency/unlock_request_requires_loan_paid_count_and_delinquency_state
    """
    ctx = _activated_loan_standing_at_its_unlock_policy_window(UNLOCK_MIN_PAID_INSTALLMENTS)
    first = validate_success(
        api_client.request_device_unlock(ctx["device_id"], ctx["customer_headers"]))
    assert first["unlock_status"] == "UNLOCK_REQUESTED"

    next_due = read_installment(ctx["loan_id"], UNLOCK_MIN_PAID_INSTALLMENTS + 1)["due_date"]
    grace_clock = plus_days(next_due, GRACE_PERIOD_DAYS)
    advance_to_dpd(ctx, GRACE_PERIOD_DAYS, installment_number=UNLOCK_MIN_PAID_INSTALLMENTS + 1)
    aged = read_loan(ctx["loan_id"])
    assert aged["delinquency_state"] == "GRACE"
    assert aged["days_past_due"] == GRACE_PERIOD_DAYS
    assert aged["outstanding_late_fee_cents"] == 0, (
        "a fee is assessed at 11 days past due and never at 10")

    refused = api_client.request_device_unlock(ctx["device_id"], ctx["customer_headers"])
    validate_error(refused, ApiErrorId.ERR_LOAN_DELINQUENT.value)
    held = read_device_unit(ctx["device_id"])
    assert held["unlock_status"] == "UNLOCK_REQUESTED"
    assert held.get("unlocked_at") is None

    post_payment(ctx["loan_id"], MODEL_B_MONTHLY_INSTALLMENT_CENTS,
                 customer_id=ctx["customer_id"])
    cured = read_loan(ctx["loan_id"])
    assert cured["delinquency_state"] == "CURRENT"
    assert cured["days_past_due"] == 0
    assert cured["paid_installment_count"] == UNLOCK_MIN_PAID_INSTALLMENTS + 1
    assert cured["paid_principal_cents"] == 26222
    assert cured["paid_premium_cents"] == 6993
    assert cured["obligation_balance_cents"] == 80661
    assert_loan_ledger_invariants(cured)

    device = validate_success(
        api_client.request_device_unlock(ctx["device_id"], ctx["customer_headers"]))
    assert device["unlock_status"] == "UNLOCKED"
    assert_iso_equals(device["unlocked_at"], grace_clock, "DeviceUnit.unlocked_at")
    assert device["activation_status"] == "ACTIVATED"
    assert device["possession_status"] == "WITH_CUSTOMER"
    carrier = _carrier_account(ctx["customer_id"], ctx["carrier"]["id"])
    assert carrier["activation_state"] == "PORT_ELIGIBLE"
    assert read_loan(ctx["loan_id"])["status"] == "ACTIVE", (
        "unlocking never closes the loan")


# =========================================================================
# cross_entity_state_dependency /
#   credit_application_blocked_by_customer_financing_lock
# =========================================================================
def _defaulted_loan_with_financing_locked_customer():
    """An ACTIVE loan aged in two sweeps to 90 days past due, so its borrower carries
    the DEFAULTED_LOAN financing lock and three assessed late fees."""
    ctx = setup_active_loan()
    advance_to_dpd(ctx, DELINQUENT_MIN_DPD)
    advance_to_dpd(ctx, DEFAULT_MIN_DPD)
    ctx["customer"] = read_customer(ctx["customer_id"])
    return ctx


def test_credit_application_refused_while_customer_is_financing_locked_then_admitted():
    """Whether a brand-new credit application may be submitted depends on a state
    dimension of a SECOND entity — the applicant Customer, whose lock is only ever
    written by a cascade out of a loan — proved in both directions in one run.

    PRD: "While a customer is `FINANCING_LOCKED`, four operations are refused outright
    with `ERR_CUSTOMER_FINANCING_LOCKED`: submitting a new credit application, filing an
    underwriting decision on an existing one, originating a loan, and opening an upgrade
    request."

    Design: Difficulty/cross_entity_state_dependency/credit_application_blocked_by_customer_financing_lock
    """
    ctx = _defaulted_loan_with_financing_locked_customer()
    loan = read_loan(ctx["loan_id"])
    assert loan["delinquency_state"] == "DEFAULT"
    assert loan["days_past_due"] == DEFAULT_MIN_DPD
    assert loan["outstanding_late_fee_cents"] == CURED_LATE_FEE_TOTAL_CENTS
    assert loan["protection_coverage_status"] == "SUSPENDED"
    assert ctx["customer"]["status"] == "FINANCING_LOCKED"
    assert ctx["customer"]["financing_lock_reason"] == "DEFAULTED_LOAN"
    assert ctx["customer"]["default_strike_count"] == 1

    payload = create_credit_application_payload(
        ctx["customer_id"], ctx["target_model"]["id"],
        requested_term_months=24, declared_down_payment_cents=0)
    refused = api_client.create_credit_application(payload, make_associate_headers())
    validate_error(refused, ApiErrorId.ERR_CUSTOMER_FINANCING_LOCKED.value)

    _, meta = validate_paginated(api_client.list_credit_applications(
        make_associate_headers(), params={"customer_id": ctx["customer_id"]}))
    assert meta["total_count"] == 1, "the refused submission created nothing"

    post_payment(ctx["loan_id"], 15735)
    released = read_customer(ctx["customer_id"])
    assert released["status"] == "ACTIVE"
    assert released["financing_lock_reason"] is None
    assert released["financing_locked_at"] is None

    accepted = api_client.create_credit_application(payload, make_associate_headers())
    application = validate_success(accepted, expected_status=201)
    assert application["status"] == "SUBMITTED"
    assert application["requested_principal_cents"] == 119900
    assert application["credit_score_band"] is None
    assert application["decision_reason"] is None


def test_curing_the_default_releases_the_lock_without_decrementing_the_strike_count():
    """The compensating cure restores the loan's collections dimension and the customer's
    financing posture exactly, allocating late fees before arrears — while leaving the
    permanently non-decrementing strike counter untouched.

    PRD: "The customer's `default_strike_count` is emphatically **not** decremented by a
    cure — the strike is permanent."

    Design: Difficulty/cross_entity_state_dependency/credit_application_blocked_by_customer_financing_lock
    """
    ctx = _defaulted_loan_with_financing_locked_customer()
    assert ctx["customer"]["default_strike_count"] == 1

    posting = post_payment(ctx["loan_id"], 15735)
    assert posting["posting_type"] == "PAYMENT"
    assert posting["allocated_late_fee_cents"] == CURED_LATE_FEE_TOTAL_CENTS
    assert posting["allocated_principal_cents"] == 11238
    assert posting["allocated_premium_cents"] == 2997
    assert posting["installments_satisfied_count"] == 3
    assert posting["overpayment_cents"] == 0
    assert posting["obligation_balance_after_cents"] == 99641
    assert_allocation_splits_exactly(posting)

    loan = read_loan(ctx["loan_id"])
    assert loan["delinquency_state"] == "CURRENT"
    assert loan["days_past_due"] == 0
    assert loan["outstanding_late_fee_cents"] == 0
    assert loan["protection_coverage_status"] == "ACTIVE"
    assert loan["obligation_balance_cents"] == 99641
    assert_loan_ledger_invariants(loan)
    assert_loan_matches_schedule(loan, read_installments(ctx["loan_id"]))

    customer = read_customer(ctx["customer_id"])
    assert customer["status"] == "ACTIVE"
    assert customer["default_strike_count"] == 1

    _, meta = validate_paginated(api_client.list_delinquency_events(
        ctx["loan_id"], make_collections_headers(),
        params={"event_type": "FINANCING_LOCK_RELEASED", "limit": 100}))
    assert meta["total_count"] == 1


# =========================================================================
# resource_temporal_overlap /
#   model_reservation_capacity_over_overlapping_fulfillment_windows
# =========================================================================
def test_overlapping_fulfillment_window_is_refused_on_a_capacity_one_target_model():
    """Aggregate capacity is measured against the live reservations whose windows
    genuinely intersect the candidate: a second borrower starting one day before the
    incumbent's window closes clashes and is refused, leaking nothing.

    PRD: "If the number of clashing live reservations is greater than or equal to the
    model's `concurrent_reservation_capacity`, the request is refused with
    `ERR_MODEL_CAPACITY_EXHAUSTED`."

    Design: Difficulty/resource_temporal_overlap/model_reservation_capacity_over_overlapping_fulfillment_windows
    """
    _model, target_model, borrowers, window_start = _two_borrowers_sharing_one_target_model(1)
    borrower_a, borrower_b = borrowers
    window_end = plus_days(window_start, FULFILLMENT_WINDOW_DAYS)

    incumbent = open_upgrade_request(borrower_a["loan_id"], target_model["id"], window_start,
                                     customer_id=borrower_a["customer_id"])
    assert_iso_equals(incumbent["fulfillment_window_start"], window_start,
                      "UpgradeRequest.fulfillment_window_start")
    assert_iso_equals(incumbent["fulfillment_window_end"], window_end,
                      "UpgradeRequest.fulfillment_window_end")
    assert read_device_model(target_model["id"])["reserved_slot_count"] == 1

    loan_b_before = read_loan(borrower_b["loan_id"])
    clashing_start = plus_days(window_start, FULFILLMENT_WINDOW_DAYS - 1)

    refused = api_client.create_upgrade_request(
        upgrade_request_payload(borrower_b["loan_id"], target_model["id"], clashing_start,
                                loan_b_before["version"]),
        borrower_b["customer_headers"])
    validate_error(refused, ApiErrorId.ERR_MODEL_CAPACITY_EXHAUSTED.value)

    assert read_device_model(target_model["id"])["reserved_slot_count"] == 1
    loan_b_after = read_loan(borrower_b["loan_id"])
    assert loan_b_after["upgrade_hold_flag"] is False
    assert loan_b_after["version"] == loan_b_before["version"]
    assert read_upgrade_request(incumbent["id"])["status"] == "ELIGIBILITY_PASSED"

    rows, meta = validate_paginated(api_client.list_upgrade_requests(
        make_associate_headers(), params={"loan_id": borrower_b["loan_id"]}))
    assert meta["total_count"] == 0
    assert rows == []


def test_touching_fulfillment_windows_do_not_clash_and_leave_two_live_reservations():
    """The clash test is strictly-before in both directions, so a candidate starting at
    the exact instant the incumbent's window ends is admitted — leaving
    `reserved_slot_count` at 2 on a model whose capacity is only 1.

    PRD: "Two live requests whose windows merely touch leave `reserved_slot_count` at 2
    while each candidate's clash count is still 1."

    Design: Difficulty/resource_temporal_overlap/model_reservation_capacity_over_overlapping_fulfillment_windows
    """
    _model, target_model, borrowers, window_start = _two_borrowers_sharing_one_target_model(1)
    borrower_a, borrower_b = borrowers
    touching_start = plus_days(window_start, FULFILLMENT_WINDOW_DAYS)
    touching_end = plus_days(touching_start, FULFILLMENT_WINDOW_DAYS)

    incumbent = open_upgrade_request(borrower_a["loan_id"], target_model["id"], window_start,
                                     customer_id=borrower_a["customer_id"])
    assert_iso_equals(incumbent["fulfillment_window_end"], touching_start,
                      "the incumbent closes at the instant the candidate opens")

    loan_b_before = read_loan(borrower_b["loan_id"])
    accepted = api_client.create_upgrade_request(
        upgrade_request_payload(borrower_b["loan_id"], target_model["id"], touching_start,
                                loan_b_before["version"]),
        borrower_b["customer_headers"])
    candidate = validate_success(accepted, expected_status=201)
    assert_upgrade_request(candidate)
    assert_iso_equals(candidate["fulfillment_window_start"], touching_start,
                      "UpgradeRequest.fulfillment_window_start")
    assert_iso_equals(candidate["fulfillment_window_end"], touching_end,
                      "UpgradeRequest.fulfillment_window_end")
    assert candidate["status"] == "ELIGIBILITY_PASSED"
    assert candidate["eligibility_ratio_bps"] == UPGRADE_PAID_RATIO_BPS

    target_after = read_device_model(target_model["id"])
    assert target_after["concurrent_reservation_capacity"] == 1
    assert target_after["reserved_slot_count"] == 2, (
        "reserved_slot_count counts live reservations, not the clash population")

    assert read_upgrade_request(incumbent["id"])["status"] == "ELIGIBILITY_PASSED", (
        "the incumbent sits on a different loan, so nothing is superseded")
    assert read_loan(borrower_a["loan_id"])["upgrade_hold_flag"] is True
    assert read_loan(borrower_b["loan_id"])["upgrade_hold_flag"] is True


# =========================================================================
# resource_temporal_overlap / payoff_quote_validity_window_single_occupancy_half_open
# =========================================================================
def _loan_quotes(loan_id, params=None):
    query = {"limit": 100}
    if params:
        query.update(params)
    return validate_paginated(api_client.list_loan_payoff_quotes(
        loan_id, make_associate_headers(), params=query))


def _loan_quote(loan_id, quote_id):
    rows, _meta = _loan_quotes(loan_id)
    for row in rows:
        if row["id"] == quote_id:
            return row
    raise AssertionError(f"payoff quote {quote_id} is not reachable from loan {loan_id}")


def _half_paid_loan_with_two_quotes():
    """A half-retired loan carrying two EARLY_CANCELLATION quotes: the first issued at
    the origin clock, the second three days later, which supersedes it."""
    ctx = setup_loan_with_paid_installments(PAID_HALF_COUNT, activate=True)
    ctx["q1"] = price_quote(ctx["loan_id"], "EARLY_CANCELLATION",
                            customer_id=ctx["customer_id"])
    set_clock(plus_days(ctx["q1"]["issued_at"], 3))
    ctx["q2"] = price_quote(ctx["loan_id"], "EARLY_CANCELLATION",
                            customer_id=ctx["customer_id"])
    return ctx


def test_a_freshly_priced_quote_supersedes_the_prior_one_which_can_no_longer_be_settled():
    """Single occupancy per (loan, quote_type): issuing a second quote drives the first
    to SUPERSEDED even though its own validity still has days to run, and the superseded
    quote can no longer be settled at its stale price.

    PRD: "A quote opens with `status` `ISSUED` and `consumed_at` null, and only one
    `ISSUED` quote of a given `quote_type` may occupy a loan at a time: pricing a fresh
    quote of the same `quote_type` moves the prior one to `SUPERSEDED`, and a loan
    reaching a terminal `status` supersedes any `ISSUED` quote left standing on it."

    Design: Difficulty/resource_temporal_overlap/payoff_quote_validity_window_single_occupancy_half_open
    """
    ctx = setup_loan_with_paid_installments(PAID_HALF_COUNT, activate=True)
    loan_before_pricing = read_loan(ctx["loan_id"])

    q1 = price_quote(ctx["loan_id"], "EARLY_CANCELLATION", customer_id=ctx["customer_id"])
    assert q1["status"] == "ISSUED"
    assert q1["consumed_at"] is None
    assert q1["remaining_principal_cents"] == 44948
    assert q1["unearned_premium_cents"] == 11988
    assert q1["premium_rebate_cents"] == 10789
    assert q1["admin_fee_cents"] == 2500
    assert q1["total_payoff_cents"] == EARLY_CANCELLATION_TOTAL_AT_HALF_TERM_CENTS
    assert_iso_equals(q1["expires_at"], plus_days(q1["issued_at"], QUOTE_VALIDITY_DAYS),
                      "PayoffQuote.expires_at")
    assert_version_advanced_by(loan_before_pricing, read_loan(ctx["loan_id"]), 1)

    set_clock(plus_days(q1["issued_at"], 3))
    q2 = price_quote(ctx["loan_id"], "EARLY_CANCELLATION", customer_id=ctx["customer_id"])
    assert q2["status"] == "ISSUED"
    assert q2["total_payoff_cents"] == EARLY_CANCELLATION_TOTAL_AT_HALF_TERM_CENTS
    assert _loan_quote(ctx["loan_id"], q1["id"])["status"] == "SUPERSEDED"

    _rows, meta = _loan_quotes(ctx["loan_id"], {"status": "ISSUED"})
    assert meta["total_count"] == 1

    refused = api_client.cancel_loan(
        ctx["loan_id"],
        cancellation_payload(q1["id"], EARLY_CANCELLATION_TOTAL_AT_HALF_TERM_CENTS),
        ctx["customer_headers"])
    validate_error(refused, ApiErrorId.ERR_PAYOFF_QUOTE_NOT_ISSUED.value)

    loan = read_loan(ctx["loan_id"])
    assert loan["status"] == "ACTIVE"
    assert loan["closure_reason"] is None


def test_payoff_quote_cannot_be_settled_at_the_instant_it_expires():
    """Validity is the half-open interval ``[issued_at, expires_at)``, so a settlement
    attempt at exactly `expires_at` is already outside the window and refused.

    PRD: "The named quote must belong to the addressed loan
    (`ERR_CROSS_REFERENCE_MISMATCH`), must be of `quote_type` `EARLY_CANCELLATION`
    (`ERR_PAYOFF_QUOTE_TYPE_MISMATCH`), must still be `ISSUED` rather than `CONSUMED`,
    `EXPIRED` or `SUPERSEDED` (`ERR_PAYOFF_QUOTE_NOT_ISSUED`), and must be unexpired,
    meaning the logical clock has not yet reached its `expires_at`
    (`ERR_PAYOFF_QUOTE_EXPIRED`)."

    Design: Difficulty/resource_temporal_overlap/payoff_quote_validity_window_single_occupancy_half_open
    """
    ctx = _half_paid_loan_with_two_quotes()
    q2 = ctx["q2"]
    assert_iso_equals(q2["expires_at"], plus_days(q2["issued_at"], QUOTE_VALIDITY_DAYS),
                      "PayoffQuote.expires_at")

    set_clock(q2["expires_at"])
    refused = api_client.cancel_loan(
        ctx["loan_id"],
        cancellation_payload(q2["id"], EARLY_CANCELLATION_TOTAL_AT_HALF_TERM_CENTS),
        ctx["customer_headers"])
    validate_error(refused, ApiErrorId.ERR_PAYOFF_QUOTE_EXPIRED.value)

    loan = read_loan(ctx["loan_id"])
    assert loan["status"] == "ACTIVE"
    assert loan["closure_reason"] is None
    assert loan["paid_installment_count"] == PAID_HALF_COUNT
    assert _loan_quote(ctx["loan_id"], q2["id"])["status"] == "ISSUED", (
        "only the servicing sweep retires an ISSUED quote; a refusal writes nothing")


def test_quote_issued_at_the_expiry_instant_is_immediately_settleable():
    """The same instant that puts the predecessor outside its window is a legal issue
    instant for a fresh quote, and that fresh quote is settleable at that very instant —
    the lower bound of the half-open interval is inclusive.

    PRD: "`issued_at` is stamped from the logical clock, and `expires_at` is set 7 days
    later, with validity treated as the half-open interval beginning at `issued_at` and
    ending immediately before `expires_at`."

    Design: Difficulty/resource_temporal_overlap/payoff_quote_validity_window_single_occupancy_half_open
    """
    ctx = _half_paid_loan_with_two_quotes()
    expiry_instant = ctx["q2"]["expires_at"]
    set_clock(expiry_instant)

    q3 = price_quote(ctx["loan_id"], "EARLY_CANCELLATION", customer_id=ctx["customer_id"])
    assert_iso_equals(q3["issued_at"], expiry_instant, "PayoffQuote.issued_at")
    assert_iso_equals(q3["expires_at"], plus_days(expiry_instant, QUOTE_VALIDITY_DAYS),
                      "PayoffQuote.expires_at")
    assert q3["total_payoff_cents"] == EARLY_CANCELLATION_TOTAL_AT_HALF_TERM_CENTS
    assert _loan_quote(ctx["loan_id"], ctx["q2"]["id"])["status"] == "SUPERSEDED"

    settled = validate_success(api_client.cancel_loan(
        ctx["loan_id"],
        cancellation_payload(q3["id"], EARLY_CANCELLATION_TOTAL_AT_HALF_TERM_CENTS),
        ctx["customer_headers"]))
    assert settled["status"] == "PAID_OFF"
    assert settled["closure_reason"] == "PROGRAM_CANCELLATION"
    assert settled["outstanding_late_fee_cents"] == 0
    assert settled["paid_principal_cents"] == MODEL_B_LOAN_PRINCIPAL_CENTS
    assert settled["protection_coverage_status"] == "TERMINATED"

    consumed = _loan_quote(ctx["loan_id"], q3["id"])
    assert consumed["status"] == "CONSUMED"
    assert_iso_equals(consumed["consumed_at"], expiry_instant, "PayoffQuote.consumed_at")

    device = read_device_unit(ctx["device_id"])
    assert device["unlock_status"] == "UNLOCKED"
    assert _carrier_account(ctx["customer_id"], ctx["carrier"]["id"])["activation_state"] == (
        "PORT_ELIGIBLE")

    rows, meta = _loan_quotes(ctx["loan_id"])
    assert meta["total_count"] == 3
    assert sorted(row["status"] for row in rows) == ["CONSUMED", "SUPERSEDED", "SUPERSEDED"]


# =========================================================================
# compensating_invariant / payment_reversal_restores_loan_obligation_balance
# =========================================================================
def _loan_with_one_half_term_payment():
    """A pristine 24-month loan plus a single PAYMENT that closes installments 1-12.

    The clock is never moved, so every due date stays in the future and no sweep ever
    runs: the only thing that has touched the ledger is the payment being reversed.
    """
    ctx = setup_active_loan()
    ctx["baseline"] = read_loan(ctx["loan_id"])
    ctx["amount"] = installment_total_cents(ctx["installments"], PAID_HALF_COUNT)
    ctx["payment"] = post_payment(ctx["loan_id"], ctx["amount"],
                                  customer_id=ctx["customer_id"])
    ctx["loan"] = read_loan(ctx["loan_id"])
    return ctx


def test_reversal_restores_the_exact_pre_payment_ledger_position_with_zero_drift():
    """The conserved quantity is money: the reversal must subtract the stored
    per-installment allocations, landing all three terms of the loan-level identity back
    on their pre-posting values rather than merely re-deriving the total.

    PRD: "The governing invariant is exact: the loan's post-reversal ledger must equal its
    ledger immediately before the target posting was applied, with zero drift in any cents
    field."

    Design: Difficulty/compensating_invariant/payment_reversal_restores_loan_obligation_balance
    """
    ctx = _loan_with_one_half_term_payment()
    baseline, payment, funded = ctx["baseline"], ctx["payment"], ctx["loan"]
    whole = MODEL_B_LOAN_PRINCIPAL_CENTS + MODEL_B_PREMIUM_TOTAL_CENTS

    assert ctx["amount"] == 56940
    assert baseline["obligation_balance_cents"] == MODEL_B_OBLIGATION_BALANCE_CENTS == whole
    assert baseline["paid_principal_cents"] == 0
    assert baseline["paid_premium_cents"] == 0

    assert payment["allocated_principal_cents"] == 44952
    assert payment["allocated_premium_cents"] == 11988
    assert payment["allocated_late_fee_cents"] == 0
    assert payment["installments_satisfied_count"] == PAID_HALF_COUNT
    assert payment["overpayment_cents"] == 0
    assert payment["obligation_balance_after_cents"] == 56936
    assert_allocation_splits_exactly(payment)

    assert funded["obligation_balance_cents"] == 56936
    assert funded["paid_principal_cents"] == 44952
    assert funded["paid_premium_cents"] == 11988
    assert funded["paid_installment_count"] == PAID_HALF_COUNT
    assert (funded["obligation_balance_cents"] + funded["paid_principal_cents"]
            + funded["paid_premium_cents"]) == whole

    reversal = post_reversal(ctx["loan_id"], ctx["amount"], payment["id"])
    assert reversal["posting_type"] == "REVERSAL"
    assert reversal["reverses_posting_id"] == payment["id"]
    assert reversal["amount_cents"] == ctx["amount"]
    assert reversal["allocated_principal_cents"] == 44952
    assert reversal["allocated_premium_cents"] == 11988
    assert reversal["allocated_late_fee_cents"] == 0
    assert reversal["installments_satisfied_count"] == 0
    assert reversal["overpayment_cents"] == 0
    assert reversal["obligation_balance_after_cents"] == MODEL_B_OBLIGATION_BALANCE_CENTS

    restored = read_loan(ctx["loan_id"])
    assert restored["paid_principal_cents"] == 0
    assert restored["paid_premium_cents"] == 0
    assert restored["paid_installment_count"] == 0
    assert restored["outstanding_late_fee_cents"] == 0
    assert restored["obligation_balance_cents"] == MODEL_B_OBLIGATION_BALANCE_CENTS
    assert (restored["obligation_balance_cents"] + restored["paid_principal_cents"]
            + restored["paid_premium_cents"]) == whole
    assert restored["status"] == "ACTIVE"
    assert_ledger_positions_equal(baseline, restored)
    assert_loan_ledger_invariants(restored)
    assert_version_advanced_by(funded, restored, 1)

    customer = read_customer(ctx["customer_id"])
    assert customer["outstanding_principal_cents"] == MODEL_B_LOAN_PRINCIPAL_CENTS
    assert customer["open_loan_count"] == 1


def test_reversed_paid_installments_with_future_due_dates_retreat_to_scheduled():
    """The installment-level movement the PRD makes reversal-only: every PAID installment
    whose due date is still in the future is driven back to SCHEDULED with all three paid
    figures zeroed and `paid_at` cleared, leaving no residue anywhere in the ladder.

    PRD: "When a reversal removes the entire allocation against a `PAID` installment whose
    `due_date` still lies in the future relative to the logical clock, the installment
    retreats `PAID → SCHEDULED`: all three paid figures are zeroed, `paid_at` is cleared,
    and `paid_installment_count` is decremented."

    Design: Difficulty/compensating_invariant/payment_reversal_restores_loan_obligation_balance
    """
    ctx = _loan_with_one_half_term_payment()
    funded_ladder = read_installments(ctx["loan_id"])
    assert [row["status"] for row in funded_ladder[:PAID_HALF_COUNT]] == (
        ["PAID"] * PAID_HALF_COUNT)

    post_reversal(ctx["loan_id"], ctx["amount"], ctx["payment"]["id"])

    for number in (1, PAID_HALF_COUNT):
        installment = read_installment(ctx["loan_id"], number)
        assert installment["status"] == "SCHEDULED"
        assert installment["paid_amount_cents"] == 0
        assert installment["paid_principal_cents"] == 0
        assert installment["paid_premium_cents"] == 0
        assert installment.get("paid_at") is None
        assert installment["late_fee_assessed"] is False
        assert installment["late_fee_cents"] == 0

    _rows, meta = validate_paginated(api_client.list_installments(
        ctx["loan_id"], make_associate_headers(),
        params={"status": "SCHEDULED", "limit": 100}))
    assert meta["total_count"] == 24

    loan = read_loan(ctx["loan_id"])
    assert_loan_matches_schedule(loan, read_installments(ctx["loan_id"]))


def test_second_reversal_of_the_same_posting_is_refused_and_gives_nothing_back_twice():
    """Conservation in the other direction: money may not be handed back twice, and the
    refused second reversal leaves both the ledger and the posting stream untouched.

    PRD: "a reversal aimed at a reversal, or a second reversal of the same target, is
    refused with `ERR_POSTING_ALREADY_REVERSED`."

    Design: Difficulty/compensating_invariant/payment_reversal_restores_loan_obligation_balance
    """
    ctx = _loan_with_one_half_term_payment()
    post_reversal(ctx["loan_id"], ctx["amount"], ctx["payment"]["id"])
    restored = read_loan(ctx["loan_id"])

    refused = api_client.create_payment(
        ctx["loan_id"],
        {"posting_type": "REVERSAL", "amount_cents": ctx["amount"],
         "reverses_posting_id": ctx["payment"]["id"]},
        make_collections_headers())
    validate_error(refused, ApiErrorId.ERR_POSTING_ALREADY_REVERSED.value)

    unchanged = read_loan(ctx["loan_id"])
    assert unchanged["obligation_balance_cents"] == MODEL_B_OBLIGATION_BALANCE_CENTS
    assert unchanged["version"] == restored["version"]
    assert_ledger_positions_equal(restored, unchanged)

    _all_rows, all_meta = validate_paginated(api_client.list_payment_postings(
        make_collections_headers(), params={"loan_id": ctx["loan_id"], "limit": 100}))
    assert all_meta["total_count"] == 2

    _rev_rows, rev_meta = validate_paginated(api_client.list_payment_postings(
        make_collections_headers(),
        params={"reverses_posting_id": ctx["payment"]["id"], "limit": 100}))
    assert rev_meta["total_count"] == 1


# =========================================================================
# compensating_invariant /
#   upgrade_window_expiry_restores_model_reserved_slot_count_and_loan_hold
# =========================================================================
def _declared_trade_in_on_a_capacity_one_target():
    """A TRADE_IN_DECLARED reservation standing on a capacity-1 target model, with the
    clock moved to exactly the reservation window's closing instant. No receipt is ever
    recorded, so the handset is still only RETURN_PENDING when the window elapses."""
    ctx = setup_trade_in_declared(
        paid_count=PAID_HALF_COUNT,
        target_model_overrides={"concurrent_reservation_capacity": 1})
    ctx["target_model"] = read_device_model(ctx["target_model"]["id"])
    set_clock(ctx["window_end"])
    return ctx


def test_expired_upgrade_window_hands_back_the_slot_the_hold_and_the_handset():
    """The conserved quantity here is resource occupancy, not money: when the reservation
    dies of old age the model's `reserved_slot_count`, the loan's `upgrade_hold_flag`, the
    trade-in and the handset's possession dimension are all handed back with no residue.

    PRD: "From `TRADE_IN_DECLARED` it does the same and additionally moves the declared
    trade-in to `CANCELLED` and returns the referenced handset's `possession_status` to
    `WITH_CUSTOMER`."

    Design: Difficulty/compensating_invariant/upgrade_window_expiry_restores_model_reserved_slot_count_and_loan_hold
    """
    ctx = _declared_trade_in_on_a_capacity_one_target()
    assert ctx["target_model"]["concurrent_reservation_capacity"] == 1
    assert ctx["target_model"]["reserved_slot_count"] == 1
    assert read_loan(ctx["loan_id"])["upgrade_hold_flag"] is True
    assert read_upgrade_request(ctx["upgrade_request_id"])["status"] == "TRADE_IN_DECLARED"
    assert read_trade_in(ctx["trade_in_id"])["status"] == "DECLARED"
    assert read_device_unit(ctx["device_id"])["possession_status"] == "RETURN_PENDING"

    report = run_sweep()
    assert report["expired_upgrade_request_count"] == 1
    assert report["expired_quote_count"] == 0
    assert report["defaulted_loan_count"] == 0
    assert report["late_fees_assessed_cents"] == 0
    assert report["processed_loan_count"] == 1
    assert report["transitioned_loan_count"] == 0

    request = read_upgrade_request(ctx["upgrade_request_id"])
    assert request["status"] == "EXPIRED"
    assert request["expiry_reason"] == "FULFILLMENT_WINDOW_ELAPSED"

    assert read_device_model(ctx["target_model"]["id"])["reserved_slot_count"] == 0, (
        "the slot is handed back, not leaked"
    )
    loan = read_loan(ctx["loan_id"])
    assert loan["upgrade_hold_flag"] is False
    assert loan["status"] == "ACTIVE"
    assert loan["delinquency_state"] == "CURRENT"
    assert loan["days_past_due"] == 0
    assert loan["paid_installment_count"] == PAID_HALF_COUNT

    assert read_trade_in(ctx["trade_in_id"])["status"] == "CANCELLED"
    device = read_device_unit(ctx["device_id"])
    assert device["possession_status"] == "WITH_CUSTOMER"
    assert device.get("returned_at") is None
    assert device["activation_status"] == "ACTIVATED", (
        "only the possession dimension was rolled back"
    )
    assert device["unlock_status"] == "LOCKED"


def test_the_same_loan_can_reserve_the_touching_window_after_its_reservation_expires():
    """Conservation is proved constructively rather than by reading a counter: the very
    same loan re-reserves the immediately following window on a capacity-1 model and
    re-declares the identical handset, which a leaked slot or a leaked possession status
    would both make impossible.

    PRD: "Compensating cascades — the release of a model reservation when an upgrade
    request expires, the restoration of a credit band when a failed diagnostic is
    overturned, the unwinding of a payment allocation by a reversal — must restore the
    exact pre-event position, with zero drift in any cents field and no residue in any
    counter."

    Design: Difficulty/compensating_invariant/upgrade_window_expiry_restores_model_reserved_slot_count_and_loan_hold
    """
    ctx = _declared_trade_in_on_a_capacity_one_target()
    run_sweep()

    next_start = ctx["window_end"]
    next_end = plus_days(next_start, FULFILLMENT_WINDOW_DAYS)
    request = open_upgrade_request(ctx["loan_id"], ctx["target_model"]["id"], next_start,
                                  customer_id=ctx["customer_id"])
    assert_upgrade_request(request)
    assert_iso_equals(request["fulfillment_window_start"], next_start,
                      "UpgradeRequest.fulfillment_window_start")
    assert_iso_equals(request["fulfillment_window_end"], next_end,
                      "UpgradeRequest.fulfillment_window_end")
    assert request["status"] == "ELIGIBILITY_PASSED"
    assert request["eligibility_ratio_bps"] == UPGRADE_PAID_RATIO_BPS
    assert request["paid_installment_count_at_request"] == PAID_HALF_COUNT

    trade_in = declare_trade_in(request["id"], ctx["device_id"], "GOOD",
                               customer_id=ctx["customer_id"])
    assert trade_in["status"] == "DECLARED"
    assert trade_in["declared_condition"] == "GOOD"
    assert trade_in["credit_estimate_cents"] == 38250

    assert read_upgrade_request(request["id"])["status"] == "TRADE_IN_DECLARED"
    assert read_device_model(ctx["target_model"]["id"])["reserved_slot_count"] == 1
    assert read_loan(ctx["loan_id"])["upgrade_hold_flag"] is True
    assert read_device_unit(ctx["device_id"])["possession_status"] == "RETURN_PENDING"

    rows, meta = validate_paginated(api_client.list_upgrade_requests(
        make_associate_headers(), params={"loan_id": ctx["loan_id"], "limit": 100}))
    assert meta["total_count"] == 2
    assert sorted(row["status"] for row in rows) == ["EXPIRED", "TRADE_IN_DECLARED"]

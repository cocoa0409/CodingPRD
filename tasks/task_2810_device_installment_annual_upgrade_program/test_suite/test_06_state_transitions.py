"""State-machine transitions: declared initial states, legal moves, exact refusals.

Every test in this module is a corner-design instance from the `state_machines`
section of SCAFFOLD_CORNER_DESIGN.yaml. The shape under test is always the same:
a transition either happens with all of its declared side effects riding along,
or it is refused with one specific error id and leaves every observable field of
every touched entity exactly where it was.

Money is always an integer count of cents; timestamps are compared through
`assert_iso_equals` so a server rendering `...T00:00:00Z` and one rendering
`...T00:00:00.000Z` are both accepted for the same instant.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
    # constants
    CREDIT_LIMITS,
    MODEL_B_LOAN_PRINCIPAL_CENTS,
    MODEL_B_MONTHLY_INSTALLMENT_CENTS,
    MODEL_B_OBLIGATION_BALANCE_CENTS,
    MODEL_B_PREMIUM_TOTAL_CENTS,
    plus_days,
    # factories
    activation_payload,
    completion_payload,
    create_loan_payload,
    decision_payload,
    diagnostic_report_payload,
    payment_payload,
    payoff_quote_payload,
    trade_in_declaration_payload,
    upgrade_request_payload,
    # fixtures
    enroll_customer,
    price_quote,
    publish_model,
    read_carrier_accounts,
    read_customer,
    read_device_model,
    read_device_unit,
    read_installments,
    read_loan,
    read_payoff_quote,
    read_trade_in,
    read_upgrade_request,
    register_carrier_account,
    set_clock,
    setup_active_loan,
    setup_paid_off_loan,
    setup_trade_in_declared,
    setup_trade_in_received,
    setup_upgrade_ready,
    setup_upgrade_request,
    submit_application,
    # test users
    make_associate_headers,
    make_collections_headers,
    make_customer_headers,
    make_technician_headers,
    make_underwriter_headers,
    # assertions
    assert_allocation_splits_exactly,
    assert_carrier_account,
    assert_credit_application,
    assert_device_unit,
    assert_diagnostic_report,
    assert_installment,
    assert_iso_equals,
    assert_loan,
    assert_loan_ledger_invariants,
    assert_loan_matches_schedule,
    assert_payment_posting,
    assert_payoff_quote,
    assert_schedule_sums_to_principal,
    assert_trade_in,
    assert_upgrade_request,
    assert_version_advanced_by,
)

# The startup logical clock, and the day the 24-month Handset B loan originated
# 2026-08-01 reaches its 330-day upgrade window.
ORIGIN = "2026-08-01T00:00:00Z"
WINDOW_OPEN = "2027-06-27T00:00:00Z"
WINDOW_CLOSE = "2027-07-04T00:00:00Z"


def test_newly_created_entities_start_in_their_declared_initial_states():
    """Seven state machines each open on their declared initial state and nowhere else.

    PRD: "At submission the application snapshots `requested_principal_cents` as the model's `retail_price_cents` less `declared_down_payment_cents`, and opens with `status` `SUBMITTED`."
    PRD: "Everything else on the new loan starts from a clean position: `paid_principal_cents`, `paid_premium_cents`, `outstanding_late_fee_cents` and `paid_installment_count` are all zero; `status` is `ACTIVE` and `closure_reason` null; `delinquency_state` is `CURRENT` with `days_past_due` zero; `protection_coverage_status` is `ACTIVE`; and `upgrade_hold_flag` is false."
    PRD: "Each new installment opens in `status` `SCHEDULED` with `paid_principal_cents`, `paid_premium_cents`, `paid_amount_cents`, `late_fee_cents` and `late_fee_paid_cents` all zero, `late_fee_assessed` false, and `paid_at` and `void_reason` both null."
    PRD: "It opens `UNACTIVATED` in `activation_status`, `LOCKED` in `unlock_status`, and `WITH_CUSTOMER` in `possession_status`, with `carrier_account_id`, `activated_at`, `unlock_requested_at`, `unlocked_at` and `returned_at` all null."
    PRD: "A fresh account opens with `activation_state` `PENDING`, `activated_at` null, and `active_device_imei` null."
    PRD: "A quote opens with `status` `ISSUED` and `consumed_at` null, and only one `ISSUED` quote of a given `quote_type` may occupy a loan at a time: pricing a fresh quote of the same `quote_type` moves the prior one to `SUPERSEDED`, and a loan reaching a terminal `status` supersedes any `ISSUED` quote left standing on it."

    Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_states
    """
    model = publish_model()
    customer = enroll_customer()
    application = submit_application(customer["id"], model["id"],
                                     requested_term_months=24,
                                     declared_down_payment_cents=0)

    # --- CreditApplication opens SUBMITTED, before any decision is filed ----
    submitted = validate_success(api_client.get_credit_application(
        application["id"], make_associate_headers()))
    assert_credit_application(submitted)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["requested_principal_cents"] == MODEL_B_LOAN_PRINCIPAL_CENTS
    assert submitted["credit_score_band"] is None
    assert submitted["decision_reason"] is None
    assert submitted["underwriter_user_id"] is None
    assert submitted["decided_at"] is None

    validate_success(api_client.decide_credit_application(
        application["id"], decision_payload("PRIME"), make_underwriter_headers()))
    loan = validate_success(api_client.create_loan(
        create_loan_payload(application["id"], down_payment_cents=0),
        make_associate_headers()), 201)

    # --- InstallmentLoan opens ACTIVE / CURRENT with a clean ledger ---------
    assert_loan(loan)
    assert loan["status"] == "ACTIVE"
    assert loan["closure_reason"] is None
    assert loan["delinquency_state"] == "CURRENT"
    assert loan["days_past_due"] == 0
    assert loan["protection_coverage_status"] == "ACTIVE"
    assert loan["upgrade_hold_flag"] is False
    assert loan["paid_principal_cents"] == 0
    assert loan["paid_premium_cents"] == 0
    assert loan["paid_installment_count"] == 0
    assert loan["outstanding_late_fee_cents"] == 0
    assert loan["obligation_balance_cents"] == MODEL_B_OBLIGATION_BALANCE_CENTS
    assert_loan_ledger_invariants(loan)

    # --- all 24 Installments open SCHEDULED and untouched -------------------
    scheduled, meta = validate_paginated(api_client.list_installments(
        loan["id"], make_associate_headers(),
        params={"status": "SCHEDULED", "limit": 100}))
    assert meta["total_count"] == 24
    assert len(scheduled) == 24
    for row in scheduled:
        assert_installment(row)
        assert row["status"] == "SCHEDULED"
        assert row["paid_principal_cents"] == 0
        assert row["paid_premium_cents"] == 0
        assert row["paid_amount_cents"] == 0
        assert row["late_fee_cents"] == 0
        assert row["late_fee_paid_cents"] == 0
        assert row["late_fee_assessed"] is False
        assert row["paid_at"] is None
        assert row["void_reason"] is None
    assert_schedule_sums_to_principal(sorted(
        scheduled, key=lambda r: r["installment_number"]), loan)

    # --- the DeviceUnit opens on all three dimensions at once ---------------
    units, unit_meta = validate_paginated(api_client.list_device_units(
        make_associate_headers(), params={"loan_id": loan["id"]}))
    assert unit_meta["total_count"] == 1
    device = units[0]
    assert_device_unit(device)
    assert device["activation_status"] == "UNACTIVATED"
    assert device["unlock_status"] == "LOCKED"
    assert device["possession_status"] == "WITH_CUSTOMER"
    assert device["carrier_account_id"] is None
    assert device["activated_at"] is None
    assert device["unlock_requested_at"] is None
    assert device["unlocked_at"] is None
    assert device["returned_at"] is None

    # --- a freshly registered CarrierAccount opens PENDING ------------------
    carrier = register_carrier_account(customer["id"], carrier_code="ATT")
    assert_carrier_account(carrier)
    assert carrier["activation_state"] == "PENDING"
    assert carrier["activated_at"] is None
    assert carrier["active_device_imei"] is None

    # --- a freshly priced PayoffQuote opens ISSUED --------------------------
    quote = validate_success(api_client.create_payoff_quote(
        loan["id"], payoff_quote_payload("EARLY_CANCELLATION"),
        make_customer_headers(customer["id"])), 201)
    assert_payoff_quote(quote)
    assert quote["status"] == "ISSUED"
    assert quote["quote_type"] == "EARLY_CANCELLATION"
    assert quote["consumed_at"] is None
    assert quote["paid_installment_count_at_quote"] == 0
    assert_iso_equals(quote["issued_at"], ORIGIN, "PayoffQuote.issued_at")
    assert_iso_equals(quote["expires_at"], "2026-08-08T00:00:00Z",
                      "PayoffQuote.expires_at")


def _carrier_by_id(customer_id: str, carrier_account_id: str) -> dict:
    """One carrier account, read back through its owning customer's sub-collection
    (the PRD exposes no single-carrier-account read)."""
    for row in read_carrier_accounts(customer_id):
        if row["id"] == carrier_account_id:
            return row
    raise AssertionError(f"carrier account {carrier_account_id} is not listed")


def test_trade_in_receipt_returns_device_and_deactivates_the_line():
    """Receipt advances DECLARED -> RECEIVED and drags possession and activation with it.

    PRD: "On success the trade-in advances `DECLARED → RECEIVED` with `received_at` stamped from the logical clock, and the handset advances `RETURN_PENDING → RETURNED` with `returned_at` stamped — which in turn moves the handset's independent activation dimension `ACTIVATED → DEACTIVATED` and clears its `activated_at`, since a handset sitting on a bench is no longer holding a line."
    PRD: "The estimate is the traded handset's model `trade_in_base_credit_cents` multiplied by the condition multiplier for the declared condition and divided by 10,000, rounded half up to whole cents."

    Design: Corner/state_machines/trade_in_receipt_returns_device_and_deactivates_the_line
    """
    ctx = setup_trade_in_declared("GOOD")

    received = validate_success(api_client.receive_trade_in(
        ctx["trade_in_id"], make_technician_headers("u-tech-1")))
    assert_trade_in(received)
    assert received["status"] == "RECEIVED"
    assert_iso_equals(received["received_at"], WINDOW_OPEN, "TradeIn.received_at")
    assert received["graded_at"] is None
    assert received["settled_at"] is None
    # 45000 base credit * 8500 bps (GOOD) / 10000 = 38250
    assert received["credit_estimate_cents"] == 38250
    assert received["graded_condition"] is None
    assert received["diagnostic_result"] is None
    assert received["latest_report_sequence_no"] == 0

    device = read_device_unit(ctx["device_id"])
    assert_device_unit(device)
    assert device["possession_status"] == "RETURNED"
    assert_iso_equals(device["returned_at"], WINDOW_OPEN, "DeviceUnit.returned_at")
    # the possession move cascades into the activation dimension, and only there
    assert device["activation_status"] == "DEACTIVATED"
    assert device["activated_at"] is None
    assert device["unlock_status"] == "LOCKED"
    assert device["unlock_requested_at"] is None
    assert device["unlocked_at"] is None

    # grading has not run, so the request has not left TRADE_IN_DECLARED
    request = read_upgrade_request(ctx["upgrade_request_id"])
    assert request["status"] == "TRADE_IN_DECLARED"

    # a receipt does not release the carrier account
    carrier = _carrier_by_id(ctx["customer_id"], ctx["carrier"]["id"])
    assert carrier["activation_state"] == "ACTIVATED"
    assert carrier["active_device_imei"] == device["imei"]


def test_diagnostic_report_before_receipt_is_refused_as_invalid_trade_in_state():
    """Grading is reachable only from RECEIVED; a DECLARED trade-in writes no report.

    PRD: "The trade-in must be in `RECEIVED` (`ERR_TRADE_IN_INVALID_STATE`) and the fulfillment window must not have elapsed."

    Design: Corner/state_machines/grading_requires_a_received_trade_in_and_receipt_is_not_repeatable
    """
    ctx = setup_trade_in_declared("GOOD")

    validate_error(api_client.create_diagnostic_report(
        ctx["trade_in_id"],
        diagnostic_report_payload(screen_grade="PRISTINE", battery_health_pct=85,
                                  water_damage_flag=False, functional_pass=True),
        make_technician_headers("u-tech-1")),
        ApiErrorId.ERR_TRADE_IN_INVALID_STATE.value)

    rows, meta = validate_paginated(api_client.list_diagnostic_reports(
        ctx["trade_in_id"], make_technician_headers()))
    assert meta["total_count"] == 0
    assert rows == []

    trade_in = read_trade_in(ctx["trade_in_id"])
    assert_trade_in(trade_in)
    assert trade_in["status"] == "DECLARED"
    assert trade_in["latest_report_sequence_no"] == 0
    assert trade_in["received_at"] is None
    assert trade_in["graded_at"] is None

    device = read_device_unit(ctx["device_id"])
    assert device["possession_status"] == "RETURN_PENDING"
    assert device["returned_at"] is None


def test_receipt_is_not_repeatable_on_an_already_received_trade_in():
    """A second receipt is refused and received_at keeps the value the first one stamped.

    PRD: "The trade-in must be in `DECLARED` (`ERR_TRADE_IN_INVALID_STATE`), its owning request must be in `TRADE_IN_DECLARED`, and the fulfillment window must not have elapsed."

    Design: Corner/state_machines/grading_requires_a_received_trade_in_and_receipt_is_not_repeatable
    """
    ctx = setup_trade_in_declared("GOOD")

    first = validate_success(api_client.receive_trade_in(
        ctx["trade_in_id"], make_technician_headers("u-tech-1")))
    assert first["status"] == "RECEIVED"
    assert_iso_equals(first["received_at"], WINDOW_OPEN, "TradeIn.received_at")

    validate_error(api_client.receive_trade_in(
        ctx["trade_in_id"], make_technician_headers("u-tech-2")),
        ApiErrorId.ERR_TRADE_IN_INVALID_STATE.value)

    again = read_trade_in(ctx["trade_in_id"])
    assert again["status"] == "RECEIVED"
    assert_iso_equals(again["received_at"], WINDOW_OPEN, "TradeIn.received_at")
    assert again["version"] == first["version"], (
        "a refused receipt must not advance the trade-in's version")

    device = read_device_unit(ctx["device_id"])
    assert device["possession_status"] == "RETURNED"
    assert device["activation_status"] == "DEACTIVATED"


def test_second_activation_of_the_same_handset_is_refused():
    """Activation is not retry-idempotent: the second call refuses and re-stamps nothing.

    PRD: "The handset must be `UNACTIVATED` in `activation_status` and `WITH_CUSTOMER` in `possession_status`; a handset already on a network, or one that has been surrendered for trade-in, is refused with `ERR_DEVICE_ALREADY_ACTIVATED`."

    Design: Corner/state_machines/second_activation_of_the_same_handset_is_refused
    """
    ctx = setup_active_loan(activate=True, carrier_overrides={"carrier_code": "ATT"})
    first_carrier = ctx["carrier"]
    second_carrier = register_carrier_account(ctx["customer_id"], carrier_code="TMOBILE")
    assert second_carrier["activation_state"] == "PENDING"

    # the clock moves on, so a re-stamped activated_at would be visibly different
    set_clock("2026-08-05T00:00:00Z")

    validate_error(api_client.activate_device_unit(
        ctx["device_id"], activation_payload(second_carrier["id"]),
        make_technician_headers("u-tech-1")),
        ApiErrorId.ERR_DEVICE_ALREADY_ACTIVATED.value)

    device = read_device_unit(ctx["device_id"])
    assert_device_unit(device)
    assert device["activation_status"] == "ACTIVATED"
    assert device["carrier_account_id"] == first_carrier["id"]
    assert_iso_equals(device["activated_at"], ORIGIN, "DeviceUnit.activated_at")
    assert device["possession_status"] == "WITH_CUSTOMER"
    assert device["unlock_status"] == "LOCKED"

    held = _carrier_by_id(ctx["customer_id"], first_carrier["id"])
    assert held["activation_state"] == "ACTIVATED"
    assert held["active_device_imei"] == device["imei"]

    untouched = _carrier_by_id(ctx["customer_id"], second_carrier["id"])
    assert_carrier_account(untouched)
    assert untouched["activation_state"] == "PENDING"
    assert untouched["active_device_imei"] is None


def test_upgrade_request_creation_reserves_a_slot_and_holds_the_loan():
    """Accepting a request reserves a target slot, holds the loan and freezes the ratio.

    PRD: "On acceptance the target model's `reserved_slot_count` is increased by one, and it is decreased by one whenever a reservation is released — on completion, on expiry, or on supersession."
    PRD: "Accepting the request also sets the loan's `upgrade_hold_flag` to true — the flag stands true for as long as a non-terminal upgrade request reserves that loan's handset for return — and advances the loan's `version` by 1."
    PRD: "The `eligibility_ratio_bps` figure is the loan's `paid_installment_count` multiplied by 10,000 and then divided by the loan's `term_months` using truncating division, so the result is a basis-point measure of how much of the ladder has been retired."
    PRD: "The candidate window is the half-open interval that begins at the supplied `fulfillment_window_start` and ends 7 days later; `fulfillment_window_end` on the request records that closing instant, and the window covers every instant from the start up to but not including the end."

    Design: Corner/state_machines/upgrade_request_creation_reserves_a_slot_and_holds_the_loan
    """
    ctx = setup_upgrade_ready(paid_count=12)
    loan_before = read_loan(ctx["loan_id"])
    assert loan_before["paid_installment_count"] == 12
    assert loan_before["upgrade_hold_flag"] is False
    target_before = read_device_model(ctx["target_model"]["id"])
    assert target_before["reserved_slot_count"] == 0

    request = validate_success(api_client.create_upgrade_request(
        upgrade_request_payload(ctx["loan_id"], ctx["target_model"]["id"],
                                WINDOW_OPEN, loan_before["version"]),
        make_customer_headers(ctx["customer_id"])), 201)

    assert_upgrade_request(request)
    assert request["status"] == "ELIGIBILITY_PASSED"
    assert request["loan_id"] == ctx["loan_id"]
    assert request["customer_id"] == ctx["customer_id"]
    assert request["target_device_model_id"] == ctx["target_model"]["id"]
    assert request["new_loan_id"] is None
    assert request["payoff_quote_id"] is None
    assert request["completed_at"] is None
    assert request["expiry_reason"] is None
    assert_iso_equals(request["fulfillment_window_start"], WINDOW_OPEN,
                      "UpgradeRequest.fulfillment_window_start")
    assert_iso_equals(request["fulfillment_window_end"], WINDOW_CLOSE,
                      "UpgradeRequest.fulfillment_window_end")
    assert_iso_equals(request["fulfillment_window_end"], plus_days(WINDOW_OPEN, 7),
                      "UpgradeRequest.fulfillment_window_end")
    # 12 paid of a 24-month ladder, truncating: 12 * 10000 // 24 == 5000
    assert request["paid_installment_count_at_request"] == 12
    assert request["eligibility_ratio_bps"] == 5000

    target_after = read_device_model(ctx["target_model"]["id"])
    assert target_after["reserved_slot_count"] == 1
    financed_after = read_device_model(ctx["model"]["id"])
    assert financed_after["reserved_slot_count"] == 0, (
        "only the target model reserves a slot")

    loan_after = read_loan(ctx["loan_id"])
    assert loan_after["upgrade_hold_flag"] is True
    assert_version_advanced_by(loan_before, loan_after, 1)

    rows, meta = validate_paginated(api_client.list_upgrade_requests(
        make_associate_headers(),
        params={"loan_id": ctx["loan_id"], "status": "ELIGIBILITY_PASSED"}))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == request["id"]


def test_completion_before_grading_is_refused_as_not_completable():
    """COMPLETED is reachable only from TRADE_IN_GRADED, however valid the quote is.

    PRD: "The upgrade request must be in `TRADE_IN_GRADED`, or completion is refused with `ERR_UPGRADE_REQUEST_NOT_COMPLETABLE`; the predecessor loan must still be `ACTIVE`; the quote must be `ISSUED`, must belong to that same loan, must carry `quote_type` `UPGRADE_ROLLOVER` rather than `FULL_PAYOFF`, and must not have passed its `expires_at`; the trade-in must be sitting in `GRADED` and not in an open dispute; and the logical clock must still be before the request's `fulfillment_window_end`."
    PRD: "`total_payoff_cents` is then `remaining_principal_cents` plus `outstanding_late_fee_cents` plus `admin_fee_cents`, less `premium_rebate_cents`."

    Design: Corner/state_machines/completion_before_grading_is_refused_as_not_completable
    """
    ctx = setup_upgrade_request(paid_count=12)
    assert ctx["upgrade_request"]["status"] == "ELIGIBILITY_PASSED"

    quote = price_quote(ctx["loan_id"], "UPGRADE_ROLLOVER",
                        customer_id=ctx["customer_id"])
    assert_payoff_quote(quote)
    assert quote["quote_type"] == "UPGRADE_ROLLOVER"
    assert quote["status"] == "ISSUED"
    assert quote["paid_installment_count_at_quote"] == 12
    # 44948 remaining principal + 0 late fee + 0 admin fee - 6234 rule-of-78 rebate
    assert quote["remaining_principal_cents"] == 44948
    assert quote["admin_fee_cents"] == 0
    assert quote["premium_rebate_cents"] == 6234
    assert quote["total_payoff_cents"] == 38714

    validate_error(api_client.complete_upgrade(
        ctx["upgrade_request_id"], completion_payload(quote["id"]),
        make_associate_headers("u-assoc-2")),
        ApiErrorId.ERR_UPGRADE_REQUEST_NOT_COMPLETABLE.value)

    request = read_upgrade_request(ctx["upgrade_request_id"])
    assert request["status"] == "ELIGIBILITY_PASSED"
    assert request["new_loan_id"] is None
    assert request["payoff_quote_id"] is None
    assert request["completed_at"] is None

    unconsumed = read_payoff_quote(ctx["loan_id"], quote["id"])
    assert unconsumed["status"] == "ISSUED"
    assert unconsumed["consumed_at"] is None

    loan = read_loan(ctx["loan_id"])
    assert loan["status"] == "ACTIVE"
    assert loan["closure_reason"] is None

    successors, successor_meta = validate_paginated(api_client.list_loans(
        make_associate_headers(), params={"predecessor_loan_id": ctx["loan_id"]}))
    assert successor_meta["total_count"] == 0, "no successor loan may be minted"
    assert successors == []

    units, unit_meta = validate_paginated(api_client.list_device_units(
        make_associate_headers(), params={"loan_id": ctx["loan_id"]}))
    assert unit_meta["total_count"] == 1


def test_deciding_an_already_decided_application_is_refused():
    """A second decision on an APPROVED application refuses and rewrites no band.

    PRD: "A decision may only be filed against an application still in `SUBMITTED`; filing one against an application that has already been decided, voided or originated is refused with `ERR_APPLICATION_NOT_DECIDABLE`."
    PRD: "In all three cases `underwriter_user_id` is set to the acting `X-User-ID`, `decided_at` is set to the logical clock, and the decision is written back onto the customer: the customer's own `credit_score_band` and `credit_limit_cents` are overwritten from this decision, so the most recent decision always governs the customer's headroom."
    PRD: "The band resolves to a program credit limit — 250,000 cents for `PRIME`, 150,000 cents for `NEAR_PRIME`, and 80,000 cents for `SUBPRIME` — and that figure is written to the application's `credit_limit_cents`."

    Design: Corner/state_machines/deciding_an_already_decided_application_is_refused
    """
    model = publish_model()
    customer = enroll_customer()
    application = submit_application(customer["id"], model["id"],
                                     requested_term_months=24,
                                     declared_down_payment_cents=0)

    decided = validate_success(api_client.decide_credit_application(
        application["id"], decision_payload("PRIME"), make_underwriter_headers()))
    assert_credit_application(decided)
    assert decided["status"] == "APPROVED"
    assert decided["credit_score_band"] == "PRIME"
    assert decided["credit_limit_cents"] == CREDIT_LIMITS["PRIME"]
    assert_iso_equals(decided["decided_at"], ORIGIN, "CreditApplication.decided_at")

    validate_error(api_client.decide_credit_application(
        application["id"], decision_payload("SUBPRIME"), make_underwriter_headers()),
        ApiErrorId.ERR_APPLICATION_NOT_DECIDABLE.value)

    retried = validate_success(api_client.get_credit_application(
        application["id"], make_associate_headers()))
    assert retried["status"] == "APPROVED"
    assert retried["credit_score_band"] == "PRIME"
    assert retried["credit_limit_cents"] == CREDIT_LIMITS["PRIME"] == 250000
    assert_iso_equals(retried["decided_at"], ORIGIN, "CreditApplication.decided_at")
    assert retried["version"] == decided["version"], (
        "a refused decision must not advance the application's version")

    holder = read_customer(customer["id"])
    assert holder["credit_score_band"] == "PRIME"
    assert holder["credit_limit_cents"] == 250000


def test_deciding_an_originated_application_is_refused():
    """Origination closes the decision door for good: ORIGINATED is not decidable either.

    PRD: "A decision may only be filed against an application still in `SUBMITTED`; filing one against an application that has already been decided, voided or originated is refused with `ERR_APPLICATION_NOT_DECIDABLE`."

    Design: Corner/state_machines/deciding_an_already_decided_application_is_refused
    """
    model = publish_model()
    customer = enroll_customer()
    application = submit_application(customer["id"], model["id"],
                                     requested_term_months=24,
                                     declared_down_payment_cents=0)
    validate_success(api_client.decide_credit_application(
        application["id"], decision_payload("PRIME"), make_underwriter_headers()))

    # the originating associate must differ from the application's underwriter
    loan = validate_success(api_client.create_loan(
        create_loan_payload(application["id"], down_payment_cents=0),
        make_associate_headers("u-assoc-1")), 201)
    assert loan["status"] == "ACTIVE"

    originated = validate_success(api_client.get_credit_application(
        application["id"], make_associate_headers()))
    assert originated["status"] == "ORIGINATED"

    validate_error(api_client.decide_credit_application(
        application["id"], decision_payload("NEAR_PRIME"), make_underwriter_headers()),
        ApiErrorId.ERR_APPLICATION_NOT_DECIDABLE.value)

    after = validate_success(api_client.get_credit_application(
        application["id"], make_associate_headers()))
    assert after["status"] == "ORIGINATED"
    assert after["credit_score_band"] == "PRIME"
    assert after["credit_limit_cents"] == 250000

    holder = read_customer(customer["id"])
    assert holder["credit_score_band"] == "PRIME"
    assert holder["credit_limit_cents"] == 250000


def test_paid_off_loan_accepts_no_further_payment_or_quote():
    """PAID_OFF is terminal: neither money nor a new quote is admitted afterwards.

    PRD: "Before any allocation runs, the loan must be `ACTIVE` (`ERR_LOAN_NOT_ACTIVE`)."
    PRD: "A quote may only be priced against a loan whose `status` is `ACTIVE`, and an `UPGRADE_ROLLOVER` quote additionally requires that the loan already carry a live upgrade request, meaning one whose `status` is `ELIGIBILITY_PASSED`, `TRADE_IN_DECLARED` or `TRADE_IN_GRADED`."
    PRD: "On success the loan advances `ACTIVE → PAID_OFF` with `closure_reason` set to `PROGRAM_CANCELLATION`, and a chain of effects follows."
    PRD: "Every installment still in `SCHEDULED`, `PAST_DUE` or `PARTIALLY_PAID` is driven to `VOIDED` with `void_reason` set to `LOAN_CLOSED`; where a voided installment carried an assessed `late_fee_cents`, that fee was already folded into the settled payoff total, which is precisely why the loan's `outstanding_late_fee_cents` can be zeroed rather than written off."

    Design: Corner/state_machines/paid_off_loan_accepts_no_further_payment_or_quote
    """
    ctx = setup_paid_off_loan()
    loan_id = ctx["loan_id"]

    # 89900 principal + 2500 admin fee - 21578 (90% of the whole 23976 premium)
    quote = ctx["quote"]
    assert quote["remaining_principal_cents"] == MODEL_B_LOAN_PRINCIPAL_CENTS == 89900
    assert quote["outstanding_late_fee_cents"] == 0
    assert quote["unearned_premium_cents"] == MODEL_B_PREMIUM_TOTAL_CENTS == 23976
    assert quote["premium_rebate_cents"] == 21578
    assert quote["admin_fee_cents"] == 2500
    assert quote["total_payoff_cents"] == 70822

    loan = ctx["loan"]
    assert loan["status"] == "PAID_OFF"
    assert loan["closure_reason"] == "PROGRAM_CANCELLATION"
    assert loan["protection_coverage_status"] == "TERMINATED"
    assert loan["outstanding_late_fee_cents"] == 0

    validate_error(api_client.create_payment(
        loan_id, payment_payload(1000), make_customer_headers(ctx["customer_id"])),
        ApiErrorId.ERR_LOAN_NOT_ACTIVE.value)
    validate_error(api_client.create_payoff_quote(
        loan_id, payoff_quote_payload("EARLY_CANCELLATION"), make_associate_headers()),
        ApiErrorId.ERR_LOAN_NOT_ACTIVE.value)

    postings, posting_meta = validate_paginated(api_client.list_payment_postings(
        make_associate_headers(), params={"loan_id": loan_id}))
    assert posting_meta["total_count"] == 1, "the refused payment created nothing"
    assert postings[0]["posting_type"] == "PAYOFF"
    assert postings[0]["amount_cents"] == 70822

    quotes, quote_meta = validate_paginated(api_client.list_loan_payoff_quotes(
        loan_id, make_associate_headers()))
    assert quote_meta["total_count"] == 1, "the refused quote request created nothing"

    consumed = read_payoff_quote(loan_id, quote["id"])
    assert consumed["status"] == "CONSUMED"
    assert_iso_equals(consumed["consumed_at"], ORIGIN, "PayoffQuote.consumed_at")

    voided, voided_meta = validate_paginated(api_client.list_installments(
        loan_id, make_associate_headers(),
        params={"status": "VOIDED", "limit": 100}))
    assert voided_meta["total_count"] == 24
    for row in voided:
        assert row["status"] == "VOIDED"
        assert row["void_reason"] == "LOAN_CLOSED"


def test_device_unit_three_dimensions_advance_independently():
    """Possession moves to RETURN_PENDING while activation and unlock stand still.

    PRD: "A handset can be `DEACTIVATED` and `UNLOCKED` and `RETURNED` all at once, and a movement in one dimension never implies a movement in another unless this document says so explicitly."
    PRD: "The declared handset moves `WITH_CUSTOMER → RETURN_PENDING`, the request advances `ELIGIBILITY_PASSED → TRADE_IN_DECLARED`, and the request's `trade_in_credit_projection_cents`, `projected_rollover_balance_cents`, `credit_shortfall_cents` and `funding_flag` are all refreshed."
    PRD: "The new trade-in opens in `status` `DECLARED` with `graded_condition`, `credit_final_cents`, `diagnostic_result` and `dispute_reason` all null, `latest_report_sequence_no`, `credit_variance_cents` and `dispute_count` all zero, and `received_at`, `graded_at` and `settled_at` all null."
    PRD: "The estimate is the traded handset's model `trade_in_base_credit_cents` multiplied by the condition multiplier for the declared condition and divided by 10,000, rounded half up to whole cents."

    Design: Corner/state_machines/device_unit_three_dimensions_advance_independently
    """
    ctx = setup_upgrade_request(paid_count=12)
    customer_headers = make_customer_headers(ctx["customer_id"])

    before = validate_success(api_client.get_device_unit(ctx["device_id"], customer_headers))
    assert_device_unit(before)
    assert before["activation_status"] == "ACTIVATED"
    assert before["unlock_status"] == "LOCKED"
    assert before["possession_status"] == "WITH_CUSTOMER"
    assert_iso_equals(before["activated_at"], ORIGIN, "DeviceUnit.activated_at")

    trade_in = validate_success(api_client.declare_trade_in(
        ctx["upgrade_request_id"],
        trade_in_declaration_payload(ctx["device_id"], "EXCELLENT"),
        customer_headers), 201)
    assert_trade_in(trade_in)
    assert trade_in["status"] == "DECLARED"
    assert trade_in["declared_condition"] == "EXCELLENT"
    # 45000 base credit * 10000 bps (EXCELLENT) / 10000 = 45000
    assert trade_in["credit_estimate_cents"] == 45000
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

    after = read_device_unit(ctx["device_id"])
    # possession moved, and nothing else did
    assert after["possession_status"] == "RETURN_PENDING"
    assert after["returned_at"] is None
    assert after["activation_status"] == "ACTIVATED"
    assert_iso_equals(after["activated_at"], ORIGIN, "DeviceUnit.activated_at")
    assert after["unlock_status"] == "LOCKED"
    assert after["unlock_requested_at"] is None
    assert after["unlocked_at"] is None
    assert after["carrier_account_id"] == ctx["carrier"]["id"]

    carrier = _carrier_by_id(ctx["customer_id"], ctx["carrier"]["id"])
    assert carrier["activation_state"] == "ACTIVATED"

    request = read_upgrade_request(ctx["upgrade_request_id"])
    assert request["status"] == "TRADE_IN_DECLARED"

    returning, returning_meta = validate_paginated(api_client.list_device_units(
        make_associate_headers(),
        params={"loan_id": ctx["loan_id"], "possession_status": "RETURN_PENDING"}))
    assert returning_meta["total_count"] == 1
    assert returning[0]["id"] == ctx["device_id"]

    on_network, on_network_meta = validate_paginated(api_client.list_device_units(
        make_associate_headers(),
        params={"loan_id": ctx["loan_id"], "activation_status": "ACTIVATED"}))
    assert on_network_meta["total_count"] == 1
    assert on_network[0]["id"] == ctx["device_id"]


def test_activation_adjusts_the_carrier_account_in_the_same_call():
    """One activation call writes both the handset and the carrier account it joins.

    PRD: "On success the handset advances `UNACTIVATED → ACTIVATED`, records the chosen `carrier_account_id`, and stamps `activated_at` with the logical clock."
    PRD: "The carrier side moves in the same breath: the account's `activation_state` becomes `ACTIVATED` and its `active_device_imei` records this handset's `imei`."

    Design: Corner/state_machines/activation_adjusts_the_carrier_account_in_the_same_call
    """
    ctx = setup_active_loan(activate=False, carrier_overrides={"carrier_code": "ATT"})
    imei = ctx["device"]["imei"]
    assert ctx["device"]["activation_status"] == "UNACTIVATED"
    assert ctx["carrier"]["activation_state"] == "PENDING"
    assert ctx["carrier"]["active_device_imei"] is None

    activated = validate_success(api_client.activate_device_unit(
        ctx["device_id"], activation_payload(ctx["carrier"]["id"]),
        make_technician_headers("u-tech-1")))
    assert_device_unit(activated)
    assert activated["activation_status"] == "ACTIVATED"
    assert activated["carrier_account_id"] == ctx["carrier"]["id"]
    assert_iso_equals(activated["activated_at"], ORIGIN, "DeviceUnit.activated_at")
    # the other two dimensions are untouched by an activation
    assert activated["unlock_status"] == "LOCKED"
    assert activated["possession_status"] == "WITH_CUSTOMER"
    assert activated["unlock_requested_at"] is None
    assert activated["unlocked_at"] is None
    assert activated["returned_at"] is None

    carrier = _carrier_by_id(ctx["customer_id"], ctx["carrier"]["id"])
    assert_carrier_account(carrier)
    assert carrier["activation_state"] == "ACTIVATED"
    assert carrier["active_device_imei"] == imei
    assert len(imei) == 15 and imei.isdigit()

    rows, meta = validate_paginated(api_client.list_device_units(
        make_associate_headers(), params={"carrier_account_id": ctx["carrier"]["id"]}))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == ctx["device_id"]


def test_installment_settlement_syncs_the_loan_ledger_without_drift():
    """Two postings keep the ladder and the loan's rolled-forward ledger in exact step.

    PRD: "At each installment the amount taken is the smaller of the remaining pool and that installment's need, and the pool shrinks by exactly that amount."
    PRD: "A second- or third-bucket take is split between principal and premium in the same proportion the installment itself carries: the principal share is the take multiplied by the installment's `principal_component_cents` divided by its `amount_due_cents`, rounded half up to whole cents, and is added to `paid_principal_cents`; the premium share is the arithmetic complement — the take less the principal share — and is added to `paid_premium_cents`, so that the two shares sum to the take exactly with no cent lost or invented."
    PRD: "The loan's own `paid_principal_cents`, `paid_premium_cents`, `paid_installment_count` and `outstanding_late_fee_cents` are all rolled forward from its installments, `paid_installment_count` counting only installments in `status` `PAID` — a `PARTIALLY_PAID` installment never counts, however close to full it is."

    Design: Corner/state_machines/installment_settlement_syncs_the_loan_ledger_without_drift
    """
    ctx = setup_active_loan()
    loan_id = ctx["loan_id"]
    assert MODEL_B_MONTHLY_INSTALLMENT_CENTS == 4745

    # --- exactly one installment's worth clears installment 1 --------------
    first = validate_success(api_client.create_payment(
        loan_id, payment_payload(MODEL_B_MONTHLY_INSTALLMENT_CENTS),
        make_customer_headers(ctx["customer_id"])), 201)
    assert_payment_posting(first)
    assert_allocation_splits_exactly(first)
    assert first["posting_type"] == "PAYMENT"
    assert first["allocated_late_fee_cents"] == 0
    assert first["allocated_principal_cents"] == 3746
    assert first["allocated_premium_cents"] == 999
    assert first["installments_satisfied_count"] == 1
    assert first["overpayment_cents"] == 0
    assert first["obligation_balance_after_cents"] == 109131
    assert_iso_equals(first["posted_at"], ORIGIN, "PaymentPosting.posted_at")

    installments = read_installments(loan_id)
    settled = installments[0]
    assert settled["installment_number"] == 1
    assert settled["status"] == "PAID"
    assert settled["paid_amount_cents"] == 4745
    assert settled["paid_principal_cents"] == 3746
    assert settled["paid_premium_cents"] == 999
    assert_iso_equals(settled["paid_at"], ORIGIN, "Installment.paid_at")

    # --- a partial 2000 splits pro rata inside installment 2 ---------------
    second = validate_success(api_client.create_payment(
        loan_id, payment_payload(2000), make_collections_headers()), 201)
    assert_payment_posting(second)
    assert_allocation_splits_exactly(second)
    # round_half_up(2000 * 3746 / 4745) == 1579 principal, 2000 - 1579 == 421 premium
    assert second["allocated_late_fee_cents"] == 0
    assert second["allocated_principal_cents"] == 1579
    assert second["allocated_premium_cents"] == 421
    assert second["installments_satisfied_count"] == 0
    assert second["overpayment_cents"] == 0
    assert second["obligation_balance_after_cents"] == 107131

    installments = read_installments(loan_id)
    partial = installments[1]
    assert partial["installment_number"] == 2
    assert partial["status"] == "PARTIALLY_PAID"
    assert partial["paid_amount_cents"] == 2000
    assert partial["paid_principal_cents"] == 1579
    assert partial["paid_premium_cents"] == 421
    assert partial["paid_at"] is None

    loan = read_loan(loan_id)
    assert loan["paid_principal_cents"] == 5325
    assert loan["paid_premium_cents"] == 1420
    assert loan["obligation_balance_cents"] == 107131
    assert (loan["paid_principal_cents"] + loan["paid_premium_cents"]
            + loan["obligation_balance_cents"]) == MODEL_B_OBLIGATION_BALANCE_CENTS == 113876
    assert loan["paid_installment_count"] == 1, (
        "a PARTIALLY_PAID installment never counts toward paid_installment_count")
    assert loan["outstanding_late_fee_cents"] == 0
    assert loan["status"] == "ACTIVE"
    assert loan["delinquency_state"] == "CURRENT"
    assert loan["days_past_due"] == 0
    assert_loan_ledger_invariants(loan)
    assert_loan_matches_schedule(loan, installments)
    assert_schedule_sums_to_principal(installments, loan)

    scheduled, meta = validate_paginated(api_client.list_installments(
        loan_id, make_associate_headers(),
        params={"status": "SCHEDULED", "limit": 100}))
    assert meta["total_count"] == 22


def test_diagnostic_fail_downgrades_the_band_but_does_not_lock_at_zero_strikes():
    """A water-damage FAIL costs a credit notch and a RETURN_FAILED handset, nothing more.

    PRD: "A `FAIL` result drives the handset `RETURNED → RETURN_FAILED` and fires two cascade links."
    PRD: "First, the customer's `credit_score_band` is downgraded one notch along the ladder `PRIME` to `NEAR_PRIME` to `SUBPRIME`, with `SUBPRIME` acting as the floor so a subprime customer stays subprime, and the customer's `credit_limit_cents` is rewritten to the program limit of the new band."
    PRD: "A first-strike diagnostic failure on an otherwise clean customer costs them a credit notch and nothing more; it does not lock their financing."
    PRD: "`derived_condition` is forced to `POOR`, and `computed_credit_cents` is the base credit multiplied by 1,000 basis points and divided by 10,000, rounded half up — a flat 10 percent of base, the program's diagnostic-failure credit."

    Design: Corner/state_machines/diagnostic_fail_downgrades_the_band_but_does_not_lock_at_zero_strikes
    """
    ctx = setup_trade_in_received("GOOD")
    before = read_customer(ctx["customer_id"])
    assert before["credit_score_band"] == "PRIME"
    assert before["credit_limit_cents"] == CREDIT_LIMITS["PRIME"] == 250000
    assert before["default_strike_count"] == 0
    assert before["status"] == "ACTIVE"

    report = validate_success(api_client.create_diagnostic_report(
        ctx["trade_in_id"],
        diagnostic_report_payload(screen_grade="PRISTINE", battery_health_pct=85,
                                  water_damage_flag=True, functional_pass=True),
        make_technician_headers("u-tech-1")), 201)
    assert_diagnostic_report(report)
    assert report["diagnostic_result"] == "FAIL"
    assert report["sequence_no"] == 1
    assert report["report_type"] == "INITIAL"
    assert report["technician_user_id"] == "u-tech-1"
    assert report["override_reason"] is None
    assert report["derived_condition"] == "POOR"
    # a FAIL short-circuits the ladder: 45000 base * 1000 bps / 10000 == 4500
    assert report["computed_credit_cents"] == 4500

    trade_in = read_trade_in(ctx["trade_in_id"])
    assert_trade_in(trade_in)
    assert trade_in["status"] == "GRADED"
    assert trade_in["diagnostic_result"] == "FAIL"
    assert trade_in["graded_condition"] == "POOR"
    assert trade_in["credit_final_cents"] == 4500
    assert trade_in["latest_report_sequence_no"] == 1
    assert_iso_equals(trade_in["graded_at"], WINDOW_OPEN, "TradeIn.graded_at")
    # 4500 final credit against the 38250 GOOD declaration
    assert trade_in["credit_variance_cents"] == -33750

    device = read_device_unit(ctx["device_id"])
    assert device["possession_status"] == "RETURN_FAILED"

    # cascade link one fires: one notch down the ladder, limit rewritten
    after = read_customer(ctx["customer_id"])
    assert after["credit_score_band"] == "NEAR_PRIME"
    assert after["credit_limit_cents"] == CREDIT_LIMITS["NEAR_PRIME"] == 150000
    # cascade link two does NOT fire at default_strike_count 0
    assert after["status"] == "ACTIVE"
    assert after["financing_lock_reason"] is None
    assert after["financing_locked_at"] is None
    assert after["default_strike_count"] == 0

    request = read_upgrade_request(ctx["upgrade_request_id"])
    assert_upgrade_request(request)
    assert request["status"] == "TRADE_IN_GRADED"
    assert request["trade_in_credit_projection_cents"] == 4500


def test_diagnostic_fail_on_a_subprime_customer_stays_at_the_subprime_floor():
    """SUBPRIME is the floor of the downgrade ladder, and no lock lands at zero strikes.

    PRD: "First, the customer's `credit_score_band` is downgraded one notch along the ladder `PRIME` to `NEAR_PRIME` to `SUBPRIME`, with `SUBPRIME` acting as the floor so a subprime customer stays subprime, and the customer's `credit_limit_cents` is rewritten to the program limit of the new band."
    PRD: "A first-strike diagnostic failure on an otherwise clean customer costs them a credit notch and nothing more; it does not lock their financing."

    Design: Corner/state_machines/diagnostic_fail_downgrades_the_band_but_does_not_lock_at_zero_strikes
    """
    # 89900 retail less a 9900 down payment leaves an 80000 principal, exactly the
    # SUBPRIME program limit, so the decision approves and origination passes the
    # re-tested credit limit.
    ctx = setup_trade_in_received("GOOD", credit_score_band="SUBPRIME",
                                  down_payment_cents=9900)
    before = read_customer(ctx["customer_id"])
    assert before["credit_score_band"] == "SUBPRIME"
    assert before["credit_limit_cents"] == CREDIT_LIMITS["SUBPRIME"] == 80000
    assert before["default_strike_count"] == 0

    report = validate_success(api_client.create_diagnostic_report(
        ctx["trade_in_id"],
        diagnostic_report_payload(screen_grade="PRISTINE", battery_health_pct=85,
                                  water_damage_flag=True, functional_pass=True),
        make_technician_headers("u-tech-1")), 201)
    assert report["diagnostic_result"] == "FAIL"
    assert report["derived_condition"] == "POOR"
    assert report["computed_credit_cents"] == 4500

    after = read_customer(ctx["customer_id"])
    assert after["credit_score_band"] == "SUBPRIME", "SUBPRIME is the ladder's floor"
    assert after["credit_limit_cents"] == 80000
    assert after["status"] == "ACTIVE"
    assert after["financing_lock_reason"] is None
    assert after["financing_locked_at"] is None

    device = read_device_unit(ctx["device_id"])
    assert device["possession_status"] == "RETURN_FAILED"

    trade_in = read_trade_in(ctx["trade_in_id"])
    assert trade_in["status"] == "GRADED"
    assert trade_in["credit_final_cents"] == 4500

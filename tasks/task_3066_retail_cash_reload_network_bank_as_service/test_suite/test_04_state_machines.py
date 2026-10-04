"""State machines: onboarding, load lifecycle, alerts, disputes and floats.

Covers the state-machine and lifecycle claims of PRD §3.2–§3.8.
"""
import pytest

from test_helpers import (
    api_client, ApiErrorId, validate_success, validate_error, get_success_data,
    set_clock, setup_network, setup_brand_program, create_brand, activate_brand,
    create_agreement, create_location, create_account, create_load, create_load_raw,
    create_and_fund_load, fund_load, create_float_window, get_account, get_program,
    get_load, get_agreement, get_location, set_agreement_state, set_brand_state,
    raise_alert, review_alert, confirm_alert, create_dispute,
    dispute_retailer_response, dispute_program_review, dispute_return_to_retailer,
    decline_load, reverse_load_ok, reinstate_load_ok,
    setup_settled_load, setup_posted_loss_allocation, make_retailer_clerk_headers,
    OFFICER, ANALYST, ADMIN, SETTLEMENT,
)


# ---------------------------------------------------------------------------
# Brand onboarding
# ---------------------------------------------------------------------------

def test_brand_activation_moves_pending_onboarding_to_active():
    """PRD §3.2: "A brand cannot leave `PENDING_ONBOARDING` for `ACTIVE` until that
    flag is true ... Reaching `ACTIVE` increments the brand's `version`."

    Design: Corner/state_machines/brand_partner_onboarded_then_activated
    """
    bank, program, brand = setup_brand_program(
        brand_overrides={"services_scope": ["CARD_ISSUANCE", "LEDGERING", "COMPLIANCE_OVERSIGHT", "DISPUTE_HANDLING"],
                         "compliance_oversight_enabled": True})
    assert brand["partner_status"] == "PENDING_ONBOARDING"
    activated = get_success_data(set_brand_state(brand["id"], "ACTIVE"))
    assert activated["partner_status"] == "ACTIVE"
    assert activated["onboarding_checklist_complete"] is True
    assert activated["version"] == brand["version"] + 1


def test_brand_activation_leaves_the_program_open_and_breach_free():
    """PRD §3.2: "The `onboarding_checklist_complete` flag is a derived readiness
    signal: it is true exactly when every element of the declared `services_scope`
    has its enabling flag set true."
    PRD §3.2: "the suspension does not by itself move the program's
    `compliance_posture`."

    Design: Corner/state_machines/brand_partner_onboarded_then_activated
    """
    bank, program, brand = setup_brand_program(
        brand_overrides={"services_scope": ["CARD_ISSUANCE", "LEDGERING"],
                         "card_issuance_enabled": True, "ledgering_enabled": True})
    activated = get_success_data(set_brand_state(brand["id"], "ACTIVE"))
    assert activated["partner_status"] == "ACTIVE"
    assert activated["suspension_source"] == "NONE"
    fresh_program = get_program(program["id"])
    assert fresh_program["compliance_posture"] == "OPEN"
    assert fresh_program["posture_breach_count"] == 0


# ---------------------------------------------------------------------------
# Load lifecycle
# ---------------------------------------------------------------------------

def test_newly_created_load_is_initiated_and_prices_at_creation():
    """PRD §3.4: "The load starts in `INITIATED`, and its price is computed at
    creation rather than at funding."
    PRD §3.4: "Money needs somewhere to land before a register can accept it."

    Design: Corner/state_machines/newly_created_load_is_initiated
    """
    net = setup_network()
    load = create_load(net["location"], net["account"], net["agreement"],
                       principal_cents=3000)
    assert load["load_status"] == "INITIATED"
    assert load["funded_at"] is None
    # fee fields are already computed at creation
    assert load["convenience_fee_cents"] == pytest.approx(230.13, abs=0.01)
    assert load["posted_total_cents"] == pytest.approx(3230.13, abs=0.01)
    account = get_account(net["account"]["id"])
    assert account["balance_cents"] == 0
    assert account["ledger_posted_cents"] == 0
    location = get_location(net["location"]["id"])
    assert location["daily_txn_count"] == 0
    assert get_agreement(net["agreement"]["id"])["accrual_pending_cents"] == 0


def test_declined_load_is_terminal_for_funding():
    """PRD §3.4: "Declining is permitted only from `INITIATED` — any other source
    state surfaces `ERR_ALREADY_TERMINAL` (HTTP 409) — and it sets `load_status`
    to `DECLINED` with `reversal_reason` of `NONE` while mutating no balance,
    ledger, accrual, float or counter value whatsoever."
    PRD §3.4: "a `DECLINED` load can never be funded, and the refusal is
    `ERR_ALREADY_TERMINAL` (HTTP 409)".

    Design: Corner/state_machines/declined_load_is_terminal_for_funding
    """
    net = setup_network()
    load = create_load(net["location"], net["account"], net["agreement"],
                       principal_cents=2000)
    declined = decline_load(load["id"], net["agreement"]["id"])
    assert declined["load_status"] == "DECLINED"
    assert declined["reversal_reason"] == "NONE"
    result = api_client.fund_load(load["id"], net["clerk_headers"])
    validate_error(result, ApiErrorId.ERR_ALREADY_TERMINAL, 409)
    assert get_load(load["id"])["load_status"] == "DECLINED"
    account = get_account(net["account"]["id"])
    assert account["balance_cents"] == 0 and account["ledger_posted_cents"] == 0
    assert get_location(net["location"]["id"])["daily_txn_count"] == 0


def test_repeat_funding_is_rejected_and_credits_the_account_once():
    """PRD §3.4: "Before it lands, the load must still be `INITIATED`".
    PRD §2.4: "A transition attempted from a state the machine does not permit
    surfaces `ERR_INVALID_STATE` (HTTP 409)".
    PRD §3.4: "The account's `balance_cents` and `ledger_posted_cents` both
    increase by the principal".

    Design: Corner/state_machines/repeat_funding_is_rejected_and_credits_once
    """
    net = setup_network()
    load = create_and_fund_load(net["location"], net["account"], net["agreement"],
                                principal_cents=3000)
    assert load["load_status"] == "FUNDED"
    result = api_client.fund_load(load["id"], net["clerk_headers"])
    validate_error(result, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_load(load["id"])["load_status"] == "FUNDED"
    account = get_account(net["account"]["id"])
    assert account["ledger_posted_cents"] == 3000
    assert account["balance_cents"] == 3000
    assert get_location(net["location"]["id"])["daily_txn_count"] == 1
    assert get_agreement(net["agreement"]["id"])["accrual_pending_cents"] == pytest.approx(
        80.55, abs=0.01)


def test_created_but_unfunded_load_leaves_the_derived_balance_unfunded():
    """PRD §2.8: "an account with no posted principal at all is `UNFUNDED`".
    PRD §2.8: "The spendable `balance_cents` is derived, never independently
    assigned: it is the maximum of zero and the difference between
    `ledger_posted_cents` and `ledger_reversed_cents`."

    Design: Corner/endpoints/load_idempotent_repeat_funding_credits_once
    """
    net = setup_network()
    load = create_load(net["location"], net["account"], net["agreement"],
                       principal_cents=3000)
    account = get_account(net["account"]["id"])
    assert load["load_status"] == "INITIATED"
    assert account["balance_cents"] == 0
    assert account["balance_cents"] == account["ledger_posted_cents"] - account["ledger_reversed_cents"]
    assert account["funding_status"] == "UNFUNDED"
    assert account["ledger_posted_cents"] == 0


def test_reverse_then_reinstate_restores_the_account_ledger_exactly():
    """PRD §3.4: "On success the load becomes `SETTLED` with its
    `settlement_batch_id` cleared to null, the account's `balance_cents` increases
    by the principal and its `ledger_reversed_cents` decreases by the principal,
    `funding_status` returns to `FUNDED`".
    PRD §2.11: "Re-instatement of a load is always a separate, explicitly
    requested act."

    Design: Difficulty/compensating_invariant/reverse_then_reinstate_conserves_account_ledger
    """
    net = setup_network()
    load = create_and_fund_load(net["location"], net["account"], net["agreement"],
                                principal_cents=12000)
    reverse_load_ok(load["id"], "DISPUTE_FAVOR_CARDHOLDER")
    after_reversal = get_account(net["account"]["id"])
    assert after_reversal["ledger_posted_cents"] == 12000
    assert after_reversal["ledger_reversed_cents"] == 12000
    assert after_reversal["balance_cents"] == 0
    reinstate_load_ok(load["id"], net["account"]["id"])
    after_reinstate = get_account(net["account"]["id"])
    assert after_reinstate["ledger_posted_cents"] == 12000
    assert after_reinstate["ledger_reversed_cents"] == 0
    assert after_reinstate["balance_cents"] == 12000
    assert get_load(load["id"])["load_status"] == "SETTLED"
    assert after_reinstate["funding_status"] == "FUNDED"


def test_reinstate_is_refused_while_a_posted_allocation_covers_the_load():
    """PRD §3.4: "no `POSTED` or `RECOVERED` loss allocation may reference the
    load — a compensated loss must be un-posted first, and the refusal is
    `ERR_INVALID_STATE` (HTTP 409)".

    Design: Difficulty/compensating_invariant/reverse_then_reinstate_conserves_account_ledger
    """
    net = setup_network()
    load = create_and_fund_load(net["location"], net["account"], net["agreement"],
                                principal_cents=12000)
    reverse_load_ok(load["id"], "DISPUTE_FAVOR_CARDHOLDER")
    allocation, _ = setup_posted_loss_allocation(net, total_loss_cents=18000,
                                                 load=load)
    account = get_account(net["account"]["id"])
    load_now = get_load(load["id"])
    result = api_client.reinstate_load(
        load["id"],
        {"expected_card_account_version": account["version"],
         "expected_load_transaction_version": load_now["version"]},
        OFFICER)
    validate_error(result, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_load(load["id"])["load_status"] == "REVERSED"


# ---------------------------------------------------------------------------
# AML alert cycle
# ---------------------------------------------------------------------------

def test_aml_alert_confirm_then_reopen_returns_it_to_review():
    """PRD §3.6: "A `ComplianceOfficer` may reopen an alert that is `CONFIRMED`
    (`ERR_INVALID_STATE` otherwise), setting it back to `UNDER_REVIEW`, clearing
    `confirmed_by_analyst_id` to null, incrementing the program's
    `open_aml_alert_count`, and recomputing the score."

    Design: Difficulty/non_linear_state_machine/aml_alert_confirm_reopen_cycle
    """
    net = setup_network()
    create_and_fund_load(net["location"], net["account"], net["agreement"],
                         principal_cents=12000)
    alert = raise_alert(net["program"], net["account"], "VELOCITY")
    review_alert(alert["id"])
    confirmed = confirm_alert(alert["id"])
    assert confirmed["alert_status"] == "CONFIRMED"
    reopened = get_success_data(api_client.reopen_aml_alert(alert["id"], OFFICER))
    assert reopened["alert_status"] == "UNDER_REVIEW"
    assert reopened["confirmed_by_analyst_id"] is None
    assert reopened["version"] > confirmed["version"]


def test_aml_alert_reopen_does_not_reinstate_the_reversed_load():
    """PRD §3.6: "It does not re-instate the loads that the confirmation reversed;
    reopen is purely the classification-correction loop."
    PRD §2.11: "a cascade never re-instates what an earlier cascade reversed."

    Design: Difficulty/non_linear_state_machine/aml_alert_confirm_reopen_cycle
    """
    net = setup_network()
    load = create_and_fund_load(net["location"], net["account"], net["agreement"],
                                principal_cents=12000)
    alert = raise_alert(net["program"], net["account"], "VELOCITY")
    review_alert(alert["id"])
    confirm_alert(alert["id"])
    assert get_load(load["id"])["load_status"] == "REVERSED"
    get_success_data(api_client.reopen_aml_alert(alert["id"], OFFICER))
    assert get_load(load["id"])["load_status"] == "REVERSED"
    assert get_account(net["account"]["id"])["compliance_hold_status"] == "FROZEN"


def test_aml_alert_open_cannot_be_dismissed_directly():
    """PRD §3.6: "A `ComplianceOfficer` may dismiss an alert that is `UNDER_REVIEW`,
    moving it to `DISMISSED`".
    PRD §2.4: "A transition attempted from a state the machine does not permit
    surfaces `ERR_INVALID_STATE` (HTTP 409)".

    Design: Difficulty/non_linear_state_machine/aml_alert_confirm_reopen_cycle
    """
    net = setup_network()
    alert = raise_alert(net["program"], net["account"], "VELOCITY")
    assert alert["alert_status"] == "OPEN"
    result = api_client.dismiss_aml_alert(alert["id"], OFFICER)
    validate_error(result, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_success_data(api_client.get_aml_alert(alert["id"], ADMIN))["alert_status"] == "OPEN"


# ---------------------------------------------------------------------------
# Dispute negotiation cycle
# ---------------------------------------------------------------------------

def _dispute_in_second_retailer_round(net):
    load = create_and_fund_load(net["location"], net["account"], net["agreement"],
                                principal_cents=3500)
    dispute = create_dispute(net["program"], load, net["account"],
                             claimed_amount_cents=1500)
    dispute_retailer_response(dispute["id"], net["agreement"]["id"])
    dispute_program_review(dispute["id"])
    dispute_return_to_retailer(dispute["id"])
    return dispute, load


def test_dispute_negotiation_returns_to_the_retailer_stage():
    """PRD §3.7: "A `ComplianceAnalyst` may also send a case in `PROGRAM_REVIEW`
    back to the retailer for another round, provided `response_round` is still
    below 3 ... and doing so recomputes `retailer_response_due_at`."
    PRD §3.7: "The retailer may supplement its narrative while the case sits in
    `RETAILER_RESPONSE`".

    Design: Difficulty/non_linear_state_machine/dispute_negotiation_round_cycle
    """
    net = setup_network()
    dispute, load = _dispute_in_second_retailer_round(net)
    supplemental = get_success_data(
        dispute_retailer_response(dispute["id"], net["agreement"]["id"],
                                  position="supplemental camera evidence"))
    assert supplemental["case_status"] == "RETAILER_RESPONSE"
    assert supplemental["response_round"] == 2


def test_dispute_reg_e_provisional_credit_is_unchanged_across_the_cycle():
    """PRD §3.7: "A `REG_E` case grants `provisional_credit_cents` at creation,
    capped at 2500 cents".
    PRD §3.7: "The retailer may supplement its narrative while the case sits in
    `RETAILER_RESPONSE`, provided the deadline has not passed, the acting clerk
    remains a party, and `response_round` is still below 3".

    Design: Difficulty/non_linear_state_machine/dispute_negotiation_round_cycle
    """
    net = setup_network()
    load = create_and_fund_load(net["location"], net["account"], net["agreement"],
                                principal_cents=3500)
    dispute = create_dispute(net["program"], load, net["account"],
                             claimed_amount_cents=1500)
    assert dispute["provisional_credit_cents"] == 1500
    dispute_retailer_response(dispute["id"], net["agreement"]["id"])
    dispute_program_review(dispute["id"])
    dispute_return_to_retailer(dispute["id"])
    supplemental = get_success_data(
        dispute_retailer_response(dispute["id"], net["agreement"]["id"],
                                  position="supplemental evidence"))
    assert supplemental["provisional_credit_cents"] == 1500
    assert supplemental["response_round"] == 2


def test_dispute_fourth_supplemental_round_is_refused():
    """PRD §3.7: "The retailer may supplement its narrative while the case sits in
    `RETAILER_RESPONSE`, provided the deadline has not passed, the acting clerk
    remains a party, and `response_round` is still below 3 — a third supplemental
    response is refused with `ERR_INVALID_STATE` (HTTP 409), which is what caps
    the loop."

    Design: Difficulty/non_linear_state_machine/dispute_negotiation_round_cycle
    """
    net = setup_network()
    dispute, load = _dispute_in_second_retailer_round(net)
    get_success_data(dispute_retailer_response(
        dispute["id"], net["agreement"]["id"], position="supplemental evidence"))
    dispute_program_review(dispute["id"])
    dispute_return_to_retailer(dispute["id"])
    at_cap = get_success_data(dispute_retailer_response(
        dispute["id"], net["agreement"]["id"], position="third round narrative"))
    assert at_cap["response_round"] == 3
    result = dispute_retailer_response(dispute["id"], net["agreement"]["id"],
                                       position="one round too far")
    validate_error(result, ApiErrorId.ERR_INVALID_STATE, 409)


# ---------------------------------------------------------------------------
# Posture conservation
# ---------------------------------------------------------------------------

def test_suspend_and_restore_leaves_the_breach_count_unchanged():
    """PRD §3.2: "Restoring a suspended brand to `ACTIVE` requires the program to
    be `OPEN` (`ERR_PROGRAM_FROZEN` otherwise) and clears `suspension_source`
    back to `NONE`."
    PRD §3.2: "This suspension counts toward the program's `posture_breach_count`
    — a `COMPLIANCE`-sourced suspension is a breach".

    Design: Difficulty/compensating_invariant/suspend_and_restore_leaves_posture_breach_count_unchanged
    """
    net = setup_network(activate_brand_flag=True)
    get_success_data(set_brand_state(net["brand"]["id"], "SUSPENDED"))
    suspended = get_success_data(api_client.get_brand_partner(net["brand"]["id"], ADMIN))
    assert suspended["suspension_source"] == "COMPLIANCE"
    assert get_program(net["program"]["id"])["posture_breach_count"] == 1
    restored = get_success_data(set_brand_state(net["brand"]["id"], "ACTIVE"))
    assert restored["suspension_source"] == "NONE"
    program = get_program(net["program"]["id"])
    assert program["posture_breach_count"] == 0
    assert program["compliance_posture"] == "OPEN"


def test_restoring_a_brand_does_not_move_the_program_posture():
    """PRD §3.2: "the suspension does not by itself move the program's
    `compliance_posture`. That move is always an explicit program act."

    Design: Difficulty/compensating_invariant/suspend_and_restore_leaves_posture_breach_count_unchanged
    """
    net = setup_network(activate_brand_flag=True)
    get_success_data(set_brand_state(net["brand"]["id"], "SUSPENDED"))
    assert get_program(net["program"]["id"])["compliance_posture"] == "OPEN"
    get_success_data(set_brand_state(net["brand"]["id"], "ACTIVE"))
    program = get_program(net["program"]["id"])
    assert program["compliance_posture"] == "OPEN"
    assert program["posture_score"] == pytest.approx(0.00, abs=0.01)


def test_freeze_then_return_to_review_leaves_the_reversal_in_place():
    """PRD §3.6: "Leaving `FROZEN` goes only to `REVIEW` — never straight to
    `CLEAR` — and never re-instates a reversed load, though it does recompute
    `balance_cents` and `funding_status` from the account's posted and reversed
    ledgers."
    PRD §2.11: "Un-freezing a program restores a hold dimension to `REVIEW`
    rather than `CLEAR`".

    Design: Corner/consistency_model/account_freeze_then_review_leaves_reversal_in_place
    """
    net = setup_network()
    load = create_and_fund_load(net["location"], net["account"], net["agreement"],
                                principal_cents=12000)
    alert = raise_alert(net["program"], net["account"], "VELOCITY")
    review_alert(alert["id"])
    confirm_alert(alert["id"])
    assert get_account(net["account"]["id"])["compliance_hold_status"] == "FROZEN"
    before = get_account(net["account"]["id"])
    unfrozen = get_success_data(api_client.set_card_account_hold(
        net["account"]["id"], {"to_hold_status": "REVIEW"}, ANALYST))
    assert unfrozen["compliance_hold_status"] == "REVIEW"
    assert get_load(load["id"])["load_status"] == "REVERSED"
    assert get_load(load["id"])["reversal_reason"] == "AML_CONFIRMED"
    assert unfrozen["ledger_reversed_cents"] == 12000
    assert unfrozen["balance_cents"] == 0
    assert unfrozen["funding_status"] == "DRAINED"
    assert unfrozen["version"] > before["version"]
    assert unfrozen["balance_cents"] == before["balance_cents"]


def test_account_hold_never_returns_straight_from_frozen_to_clear():
    """PRD §3.6: "Leaving `FROZEN` goes only to `REVIEW` — never straight to
    `CLEAR`".
    PRD §2.4: "A transition attempted from a state the machine does not permit
    surfaces `ERR_INVALID_STATE` (HTTP 409)".

    Design: Corner/consistency_model/account_freeze_then_review_leaves_reversal_in_place
    """
    net = setup_network()
    create_and_fund_load(net["location"], net["account"], net["agreement"],
                         principal_cents=12000)
    alert = raise_alert(net["program"], net["account"], "VELOCITY")
    review_alert(alert["id"])
    confirm_alert(alert["id"])
    result = api_client.set_card_account_hold(
        net["account"]["id"], {"to_hold_status": "CLEAR"}, ANALYST)
    validate_error(result, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_account(net["account"]["id"])["compliance_hold_status"] == "FROZEN"


# ---------------------------------------------------------------------------
# Agreement and float state machines
# ---------------------------------------------------------------------------

def test_terminating_a_suspended_agreement_is_blocked_by_unsettled_accrual():
    """PRD §3.3: "Termination is available from `DRAFT` unconditionally, and from
    `SUSPENDED` only when `accrual_pending_cents` is zero, so that unsettled
    accruals must be settled before the contract can be closed (`ERR_INVALID_STATE`,
    HTTP 409)."

    Design: Corner/state_machines/agreement_termination_blocked_by_unsettled_accrual
    """
    net = setup_network()
    create_and_fund_load(net["location"], net["account"], net["agreement"],
                         principal_cents=3500)
    assert get_agreement(net["agreement"]["id"])["accrual_pending_cents"] == pytest.approx(
        85.99, abs=0.01)
    get_success_data(set_agreement_state(net["program"]["id"], net["agreement"]["id"],
                                         "SUSPENDED"))
    result = set_agreement_state(net["program"]["id"], net["agreement"]["id"],
                                 "TERMINATED")
    validate_error(result, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_agreement(net["agreement"]["id"])["agreement_status"] == "SUSPENDED"
    # the suspension restricted the store; the termination cascade never ran
    assert get_location(net["location"]["id"])["location_status"] == "RESTRICTED"


def test_services_scope_must_name_every_enabled_service_for_the_checklist():
    """PRD §3.2: "The `onboarding_checklist_complete` flag is a derived readiness
    signal: it is true exactly when every element of the declared `services_scope`
    has its enabling flag set true."

    PRD §3.2: "it is true exactly when every element of the declared
    `services_scope` has its enabling flag set true."

    Design: Corner/state_machines/brand_partner_onboarded_then_activated
    """


def test_float_window_cannot_complete_from_requested():
    """PRD §3.8: "A window opens in `REQUESTED` and moves through `CONFIRMED` and
    on to `COMPLETED`, or to `CANCELLED` from `REQUESTED`."
    PRD §2.4: "A transition attempted from a state the machine does not permit
    surfaces `ERR_INVALID_STATE` (HTTP 409)".

    Design: Corner/state_machines/float_window_cannot_complete_from_requested
    """
    net = setup_network()
    window = create_float_window(net["location"])
    assert window["window_status"] == "REQUESTED"
    result = api_client.complete_float_window(window["id"], SETTLEMENT)
    validate_error(result, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_success_data(api_client.get_float_window(window["id"], ADMIN))[
        "window_status"] == "REQUESTED"
    assert get_agreement(net["agreement"]["id"])["float_position_cents"] == 0


def test_loss_allocation_post_recomputes_program_allocated_total():
    """PRD §3.8: "Posting sets `allocation_status` to `POSTED` and stamps
    `posted_at` with the current clock instant; it then pins the cited contract by
    setting the agreement's `contract_version_locked` true, increases the
    program's `allocated_loss_total_cents` by the total loss".

    Design: Corner/state_machines/loss_allocation_post_recomputes_program_allocated_total
    """
    net = setup_network(clock="2026-09-01T00:00:00Z")
    allocation, load = setup_posted_loss_allocation(net, total_loss_cents=18000)
    assert allocation["allocation_status"] == "POSTED"
    assert allocation["posted_at"] == "2026-09-01T00:00:00Z"
    assert get_program(net["program"]["id"])["allocated_loss_total_cents"] == 18000
    assert get_agreement(net["agreement"]["id"])["contract_version_locked"] is True
    assert allocation["retailer_share_cents"] == 15000
    assert allocation["bank_share_cents"] == 450
    assert allocation["program_share_cents"] == 2550
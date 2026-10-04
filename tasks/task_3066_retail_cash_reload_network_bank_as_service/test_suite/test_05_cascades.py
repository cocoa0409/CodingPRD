"""Cascades, cross-entity dependencies and hop ordering (PRD §2.11, §3.2–§3.6)."""
import pytest

from test_helpers import (
    api_client, ApiErrorId, validate_error, get_success_data,
    set_clock, setup_network, setup_brand_program, create_brand, activate_brand,
    create_agreement, activate_agreement, create_location, create_account,
    create_load, create_and_fund_load, create_load_raw, fund_load, get_account,
    get_program, get_load, get_agreement, get_location, set_brand_state,
    set_agreement_state, set_location_state, raise_alert, review_alert,
    confirm_alert, create_dispute, dispute_retailer_response, move_program_posture,
    setup_settled_load, setup_posted_loss_allocation, make_program_manager_headers,
    make_retailer_clerk_headers, OFFICER, ANALYST, ADMIN, SETTLEMENT,
)


# ---------------------------------------------------------------------------
# Depth-5 cascade: confirm -> freeze -> reverse -> recover -> counters
# ---------------------------------------------------------------------------

def _depth5_network():
    net = setup_network()
    create_and_fund_load(net["location"], net["account"], net["agreement"],
                         principal_cents=12000)
    alert = raise_alert(net["program"], net["account"], "VELOCITY")
    return net, alert


def test_confirmed_alert_freezes_the_account():
    """PRD §3.6: "Hop 2 pushes the account's hold dimension to `FROZEN` and stamps
    `frozen_at` with the current clock instant."

    Design: Difficulty/transitive_cascade/alert_confirm_freeze_reverse_recover_depth5
    """
    net, alert = _depth5_network()
    review_alert(alert["id"])
    now = set_clock("2026-09-01T12:00:00Z")
    confirmed = confirm_alert(alert["id"])
    assert confirmed["alert_status"] == "CONFIRMED"
    account = get_account(net["account"]["id"])
    assert account["compliance_hold_status"] == "FROZEN"
    assert account["frozen_at"] == "2026-09-01T12:00:00Z"


def test_confirmed_alert_reverses_the_funded_loads_of_that_account():
    """PRD §3.6: "Hop 3 reverses every `FUNDED` load of that account with a
    `reversal_reason` of `AML_CONFIRMED`."

    Design: Difficulty/transitive_cascade/alert_confirm_freeze_reverse_recover_depth5
    """
    net, alert = _depth5_network()
    load_id = get_success_data(api_client.list_loads(
        ADMIN, {"card_account_id": net["account"]["id"]}))[0]["id"]
    review_alert(alert["id"])
    confirm_alert(alert["id"])
    load = get_load(load_id)
    assert load["load_status"] == "REVERSED"
    assert load["reversal_reason"] == "AML_CONFIRMED"
    account = get_account(net["account"]["id"])
    assert account["ledger_posted_cents"] == 12000
    assert account["ledger_reversed_cents"] == 12000
    assert account["balance_cents"] == 0


def test_confirmed_alert_recovers_the_posted_loss_allocation_and_keeps_the_total():
    """PRD §3.6: "Hop 4 marks every `POSTED` loss allocation covering a load
    reversed in hop 3 as `RECOVERED`, again leaving the program's
    `allocated_loss_total_cents` unchanged."
    PRD §3.8: "a recovered allocation is still an allocated one."

    Design: Difficulty/transitive_cascade/alert_confirm_freeze_reverse_recover_depth5
    """
    net = setup_network()
    allocation, load = setup_posted_loss_allocation(net, total_loss_cents=18000,
                                                    principal_cents=12000)
    assert get_program(net["program"]["id"])["allocated_loss_total_cents"] == 18000
    alert = raise_alert(net["program"], net["account"], "VELOCITY")
    review_alert(alert["id"])
    confirm_alert(alert["id"])
    recovered = get_success_data(api_client.get_loss_allocation(allocation["id"], ADMIN))
    assert recovered["allocation_status"] == "RECOVERED"
    assert get_program(net["program"]["id"])["allocated_loss_total_cents"] == 18000


def test_confirmed_alert_recomputes_the_program_alert_count():
    """PRD §3.6: "Hop 5 decrements the program's `open_aml_alert_count`, recomputes
    its `posture_score`, and increases its `unallocated_confirmed_loss_cents` by
    the principal of each load reversed in hop 3".

    Design: Difficulty/transitive_cascade/alert_confirm_freeze_reverse_recover_depth5
    """
    net, alert = _depth5_network()
    assert get_program(net["program"]["id"])["open_aml_alert_count"] == 1
    review_alert(alert["id"])
    confirm_alert(alert["id"])
    program = get_program(net["program"]["id"])
    assert program["open_aml_alert_count"] == 0
    assert program["unallocated_confirmed_loss_cents"] == 12000


# ---------------------------------------------------------------------------
# Depth-3 cascade: brand suspend -> accounts to REVIEW -> pending loads declined
# ---------------------------------------------------------------------------

def test_brand_suspension_moves_its_accounts_to_review():
    """PRD §3.2: "hop 2 moves every `CardAccount` of that brand whose
    `compliance_hold_status` is `CLEAR` into `REVIEW`".

    Design: Difficulty/transitive_cascade/brand_suspend_decline_unwind_depth3
    """
    net = setup_network(activate_brand_flag=True)
    get_success_data(set_brand_state(net["brand"]["id"], "SUSPENDED"))
    assert get_account(net["account"]["id"])["compliance_hold_status"] == "REVIEW"


def test_brand_suspension_declines_the_pending_load():
    """PRD §3.2: "hop 3 declines every pending load of those accounts, moving
    `load_status` from `INITIATED` to `DECLINED` with `reversal_reason` of `NONE`,
    because a pending load of a suspended brand can never be funded."

    Design: Difficulty/transitive_cascade/brand_suspend_decline_unwind_depth3
    """
    net = setup_network(activate_brand_flag=True)
    load = create_load(net["location"], net["account"], net["agreement"],
                       principal_cents=2000)
    assert load["load_status"] == "INITIATED"
    get_success_data(set_brand_state(net["brand"]["id"], "SUSPENDED"))
    declined = get_load(load["id"])
    assert declined["load_status"] == "DECLINED"
    assert declined["reversal_reason"] == "NONE"
    account = get_account(net["account"]["id"])
    assert account["balance_cents"] == 0 and account["ledger_posted_cents"] == 0
    assert get_agreement(net["agreement"]["id"])["accrual_pending_cents"] == 0


def test_brand_suspension_does_not_move_the_program_posture_by_itself():
    """PRD §3.2: "the suspension does not by itself move the program's
    `compliance_posture`. That move is always an explicit program act."

    Design: Difficulty/transitive_cascade/brand_suspend_decline_unwind_depth3
    """
    net = setup_network(activate_brand_flag=True)
    get_success_data(set_brand_state(net["brand"]["id"], "SUSPENDED"))
    program = get_program(net["program"]["id"])
    assert program["compliance_posture"] == "OPEN"
    assert program["posture_breach_count"] == 1
    assert program["posture_score"] == pytest.approx(10.00, abs=0.01)


# ---------------------------------------------------------------------------
# Cross-entity state dependency
# ---------------------------------------------------------------------------

def test_brand_activation_requires_open_program():
    """PRD §3.2: "Activation additionally requires the parent program's
    `compliance_posture` to be `OPEN`, otherwise `ERR_PROGRAM_FROZEN` (HTTP 409)
    applies."
    PRD §3.2: "A brand cannot leave `PENDING_ONBOARDING` for `ACTIVE` until that
    flag is true, and an attempt to activate an incomplete brand is refused with
    `ERR_BRAND_ONBOARDING_INCOMPLETE` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/brand_activation_requires_open_program
    """
    net = setup_network(brand_overrides={
        "services_scope": ["CARD_ISSUANCE", "LEDGERING", "COMPLIANCE_OVERSIGHT"],
        "card_issuance_enabled": True, "ledgering_enabled": True,
        "compliance_oversight_enabled": False})
    # A declared service whose enabling flag is false => incomplete checklist.
    result = set_brand_state(net["brand"]["id"], "ACTIVE")
    validate_error(result, ApiErrorId.ERR_BRAND_ONBOARDING_INCOMPLETE, 422)
    assert get_success_data(api_client.get_brand_partner(net["brand"]["id"], ADMIN))[
        "partner_status"] == "PENDING_ONBOARDING"


def test_brand_activation_is_refused_while_the_program_is_frozen():
    """PRD §3.2: "Activation additionally requires the parent program's
    `compliance_posture` to be `OPEN`, otherwise `ERR_PROGRAM_FROZEN` (HTTP 409)
    applies."
    PRD §2.4: "A write that creates or mutates a child of a program whose
    `compliance_posture` is `FROZEN` is refused with `ERR_PROGRAM_FROZEN` (HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/brand_activation_requires_open_program
    """
    net = setup_network(activate_brand_flag=True)
    # Drive the program FROZEN by accumulating breach count. The freeze band is
    # only reachable with the overdue decay factor (lambda 0.20), so the clock
    # must sit past the program's oversight_review_due_at.
    from test_helpers import suspend_brands, setup_frozen_program
    suspend_brands(net, 5)
    set_clock("2027-01-01T00:00:00Z")
    setup_frozen_program(net)
    assert get_program(net["program"]["id"])["compliance_posture"] == "FROZEN"
    # A fresh complete brand cannot be onboarded while the program is frozen.
    result = api_client.create_brand_partner(
        {"program_id": net["program"]["id"], "brand_name": "Blocked Brand",
         "services_scope": ["LEDGERING"], "ledgering_enabled": True,
         "expected_program_version": get_program(net["program"]["id"])["version"]},
        OFFICER)
    validate_error(result, ApiErrorId.ERR_PROGRAM_FROZEN, 409)


def test_settlement_batch_cannot_open_while_the_agreement_is_suspended():
    """PRD §3.8: "Opening a scheduled batch requires that no other batch of the
    same agreement is already `OPEN` and that the agreement's `agreement_status`
    is `ACTIVE`, else `ERR_AGREEMENT_NOT_ACTIVE` (HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/settlement_requires_active_agreement_status
    """
    net = setup_network()
    create_and_fund_load(net["location"], net["account"], net["agreement"],
                         principal_cents=3500)
    from test_helpers import create_settlement_batch
    batch = create_settlement_batch(net["agreement"])
    get_success_data(set_agreement_state(net["program"]["id"], net["agreement"]["id"],
                                         "SUSPENDED"))
    result = api_client.open_settlement_batch(batch["id"], SETTLEMENT)
    validate_error(result, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE, 409)
    assert get_success_data(api_client.get_settlement_batch(batch["id"], ADMIN))[
        "batch_status"] == "SCHEDULED"


def test_settlement_batch_opens_once_the_agreement_is_active():
    """PRD §3.8: "Opening a scheduled batch requires that no other batch of the
    same agreement is already `OPEN` and that the agreement's `agreement_status`
    is `ACTIVE`, else `ERR_AGREEMENT_NOT_ACTIVE` (HTTP 409); opening advances the
    batch to `OPEN`."

    Design: Difficulty/cross_entity_state_dependency/settlement_requires_active_agreement_status
    """
    net = setup_network()
    create_and_fund_load(net["location"], net["account"], net["agreement"],
                         principal_cents=3500)
    from test_helpers import create_settlement_batch
    batch = create_settlement_batch(net["agreement"])
    opened = get_success_data(api_client.open_settlement_batch(batch["id"], SETTLEMENT))
    assert opened["batch_status"] == "OPEN"


# ---------------------------------------------------------------------------
# Program posture cascade
# ---------------------------------------------------------------------------

def test_open_to_restricted_cascade_suspends_brands_and_restricts_stores():
    """PRD §3.5: "Moving from `OPEN` to `RESTRICTED` performs a single hop that
    touches three subordinate collections: every `ACTIVE` brand of the program is
    suspended with a `suspension_source` of `POSTURE`; every store under the
    program's agreements whose `location_status` is `OPEN` becomes `RESTRICTED` ...
    and every agreement of the program whose `agreement_status` is `ACTIVE`
    becomes `SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/brand_activation_requires_open_program
    """
    net = setup_network(activate_brand_flag=True)
    # Accumulate two breaches: the brand suspension below plus one confirmed alert.
    create_and_fund_load(net["location"], net["account"], net["agreement"],
                         principal_cents=12000)
    alert = raise_alert(net["program"], net["account"], "VELOCITY")
    review_alert(alert["id"])
    confirm_alert(alert["id"])
    program = get_program(net["program"]["id"])
    assert program["compliance_posture"] == "OPEN"
    assert 4.00 <= program["posture_score"] <= 59.99
    resp = move_program_posture(net["program"]["id"], "RESTRICTED", net["bank"]["id"])
    moved = get_success_data(resp)
    assert moved["compliance_posture"] == "RESTRICTED"
    assert get_location(net["location"]["id"])["location_status"] == "RESTRICTED"


def test_restricted_to_open_closes_the_posture_cascade():
    """PRD §3.5: "Returning to `OPEN` from `RESTRICTED` requires a score of 3.99
    or lower and revives only what the posture cascade suspended: brands with a
    `suspension_source` of `POSTURE` become `ACTIVE` again ... stores that are
    `RESTRICTED` become `OPEN`; and the agreements suspended by the posture
    cascade become `ACTIVE`."

    Design: Difficulty/compensating_invariant/suspend_and_restore_leaves_posture_breach_count_unchanged
    """
    net = setup_network(activate_brand_flag=True)
    create_and_fund_load(net["location"], net["account"], net["agreement"],
                         principal_cents=12000)
    alert = raise_alert(net["program"], net["account"], "VELOCITY")
    review_alert(alert["id"])
    confirm_alert(alert["id"])
    get_success_data(move_program_posture(net["program"]["id"], "RESTRICTED",
                                          net["bank"]["id"]))
    assert get_agreement(net["agreement"]["id"])["agreement_status"] == "SUSPENDED"
    # Reopen via the alert being dismissed to lower the score, then restore.
    get_success_data(api_client.reopen_aml_alert(alert["id"], OFFICER))
    get_success_data(api_client.dismiss_aml_alert(alert["id"], OFFICER))
    restored = get_success_data(move_program_posture(net["program"]["id"], "OPEN",
                                                     net["bank"]["id"]))
    assert restored["compliance_posture"] == "OPEN"
    assert restored["posture_breach_count"] == 0


# ---------------------------------------------------------------------------
# Allocation reconciliation across recovery
# ---------------------------------------------------------------------------

def test_allocated_loss_total_reconciles_across_recovery():
    """PRD §3.8: "A `SettlementOperator` later marks a posted allocation
    `RECOVERED` ... and this leaves `allocated_loss_total_cents` unchanged,
    because a recovered allocation is still an allocated one."
    PRD §3.8: "`chargeback_total_cents` is the sum of the total losses of `POSTED`
    allocations charged to the agreement with a `posted_at` inside the period".

    Design: Corner/cross_cutting_complexity_layers/allocated_loss_total_reconciles_across_recovery
    """
    from test_helpers import create_settlement_batch, open_settlement_batch, \
        settle_settlement_batch_ok
    net = setup_network(clock="2026-09-01T00:00:00Z")
    allocation, load = setup_posted_loss_allocation(net, total_loss_cents=18000,
                                                    principal_cents=12000)
    batch = create_settlement_batch(net["agreement"])
    open_settlement_batch(batch["id"])
    settled = settle_settlement_batch_ok(batch["id"])
    assert settled["chargeback_total_cents"] == 18000
    recovered = get_success_data(api_client.recover_loss_allocation(allocation["id"],
                                                                    SETTLEMENT))
    assert recovered["allocation_status"] == "RECOVERED"
    assert get_program(net["program"]["id"])["allocated_loss_total_cents"] == 18000


# ---------------------------------------------------------------------------
# Clawback compensation
# ---------------------------------------------------------------------------

def test_clawback_compensates_the_fee_payable_and_the_float():
    """PRD §3.8: "The agreement's `float_position_cents` decreases by the batch's
    `float_retained_cents` and its `accrual_pending_cents` is restored by the
    `accrued_retailer_share_cents`, so the settlement is undone economically as
    well as on the load rows."
    PRD §3.8: "Hop 1 marks the batch `CLAWED_BACK` and reverses every `SETTLED`
    load of the batch, setting `load_status` to `REVERSED` with a
    `reversal_reason` of `RETAILER_REQUEST`".

    Design: Corner/consistency_model/settlement_clawback_compensates_the_fee_payable
    """
    from test_helpers import create_settlement_batch, open_settlement_batch, \
        settle_settlement_batch_ok, clawback_settlement_batch
    net = setup_network()
    load = create_and_fund_load(net["location"], net["account"], net["agreement"],
                                principal_cents=3500)
    batch = create_settlement_batch(net["agreement"])
    open_settlement_batch(batch["id"])
    settle_settlement_batch_ok(batch["id"])
    assert get_agreement(net["agreement"]["id"])["accrual_pending_cents"] == 0
    clawed = clawback_settlement_batch(batch["id"])
    assert clawed["batch_status"] == "CLAWED_BACK"
    assert get_load(load["id"])["load_status"] == "REVERSED"
    assert get_load(load["id"])["reversal_reason"] == "RETAILER_REQUEST"
    agreement = get_agreement(net["agreement"]["id"])
    assert agreement["accrual_pending_cents"] == pytest.approx(85.99, abs=0.01)


def test_clawback_restores_the_retailer_float_position():
    """PRD §3.8: "The agreement's `float_position_cents` decreases by the batch's
    `float_retained_cents`".
    PRD §3.8: "Hop 1 marks the batch `CLAWED_BACK` and reverses every `SETTLED`
    load of the batch, setting `load_status` to `REVERSED` with a
    `reversal_reason` of `RETAILER_REQUEST` and adjusting each affected account's
    balance and ledger."

    Design: Corner/consistency_model/settlement_clawback_compensates_the_fee_payable
    """
    from test_helpers import create_settlement_batch, open_settlement_batch, \
        settle_settlement_batch_ok, clawback_settlement_batch
    net = setup_network()
    create_and_fund_load(net["location"], net["account"], net["agreement"],
                         principal_cents=3500)
    batch = create_settlement_batch(net["agreement"])
    open_settlement_batch(batch["id"])
    settle_settlement_batch_ok(batch["id"])
    clawback_settlement_batch(batch["id"])
    assert get_agreement(net["agreement"]["id"])["float_position_cents"] == 0
    assert get_account(net["account"]["id"])["ledger_reversed_cents"] == 3500
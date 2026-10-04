"""Operator onboarding, activation gating, agreement immutability, and the
suspend/reinstate compensating pair."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_operator_onboarding, setup_active_operator, set_clock,
    make_operator_headers, setup_restaurant_available, create_operator_payload,
)

ADMIN = TEST_USERS["system_admin_headers"]
FC = TEST_USERS["field_consultant_headers"]
SC = TEST_USERS["selection_committee_headers"]


def test_agreement_immutability_transferable_and_equity(api):
    """PRD §3.6: "simultaneously a draft operator agreement is created binding
    that operator to that restaurant — the agreement carries its own
    `operator_id` and `restaurant_id` references, both immutable — with
    `transferable` always false and `equity_stake_bps` always zero, and its
    `agreement_status` at `DRAFT`."

    Design: Corner/validations/agreement_immutability_transferable_and_equity
    """
    set_clock()
    ctx = setup_operator_onboarding()
    agreements = get_success_data(api.get_operator_agreement(ctx["operator"]["id"], SC))
    assert len(agreements) == 1
    agreement = agreements[0]
    assert agreement["transferable"] is False
    assert agreement["equity_stake_bps"] == 0
    assert agreement["agreement_status"] == "DRAFT"


def test_operator_activate_refused_while_agreement_draft(api):
    """PRD §3.6: "activation requires `residency_verified` and
    `full_time_attested` both true, the linked agreement `EXECUTED`, and the
    linked restaurant `ASSIGNED` to this operator."
    PRD §2.8: "fourth, whether the target resource's current state permits the
    requested transition (`ERR_INVALID_STATE`)"

    Design: Difficulty/cross_entity_state_dependency/operator_activate_gated_by_agreement_and_restaurant_state
    """
    set_clock()
    ctx = setup_operator_onboarding()
    operator = ctx["operator"]
    op_headers = make_operator_headers(operator["id"])
    validate_success(api.attest_operator(
        operator["id"], {"residency_verified": True, "full_time_attested": True}, op_headers
    ))
    # Agreement is still DRAFT; the restaurant is not ASSIGNED to this operator.
    resp = api.activate_operator(operator["id"], FC)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_operator_status_unchanged_when_activation_refused(api):
    """PRD §3.6: "activation requires `residency_verified` and
    `full_time_attested` both true, the linked agreement `EXECUTED`, and the
    linked restaurant `ASSIGNED` to this operator."
    PRD §3.6: "The operator is created with `operator_status` at `ONBOARDING`"

    Design: Difficulty/cross_entity_state_dependency/operator_activate_gated_by_agreement_and_restaurant_state
    """
    set_clock()
    ctx = setup_operator_onboarding()
    operator = ctx["operator"]
    op_headers = make_operator_headers(operator["id"])
    validate_success(api.attest_operator(
        operator["id"], {"residency_verified": True, "full_time_attested": True}, op_headers
    ))
    validate_error(api.activate_operator(operator["id"], FC), ApiErrorId.ERR_INVALID_STATE)
    current = get_success_data(api.get_operator(operator["id"], ADMIN))
    assert current["operator_status"] == "ONBOARDING"
    agreement = get_success_data(api.get_operator_agreement(operator["id"], SC))[0]
    assert agreement["agreement_status"] == "DRAFT"


def test_suspend_then_reinstate_restores_agreement_executed(api):
    """PRD §3.6: "Suspending an `ACTIVE` operator moves them to `SUSPENDED` and
    cascades the agreement from `EXECUTED` to `SUSPENDED`. Reinstating requires
    `residency_verified` to still hold true, moves the operator back to
    `ACTIVE`, and cascades the agreement back from `SUSPENDED` to `EXECUTED`."

    Design: Difficulty/compensating_invariant/operator_suspend_reinstate_restores_agreement_executed
    """
    set_clock()
    ctx = setup_active_operator()
    operator_id = ctx["operator"]["id"]
    validate_success(api.suspend_operator(operator_id, FC))
    suspended = get_success_data(api.get_operator(operator_id, ADMIN))
    assert suspended["operator_status"] == "SUSPENDED"
    agreement = get_success_data(api.get_operator_agreement(operator_id, SC))[0]
    assert agreement["agreement_status"] == "SUSPENDED"

    validate_success(api.reinstate_operator(operator_id, FC))
    reinstated = get_success_data(api.get_operator(operator_id, ADMIN))
    assert reinstated["operator_status"] == "ACTIVE"
    agreement = get_success_data(api.get_operator_agreement(operator_id, SC))[0]
    assert agreement["agreement_status"] == "EXECUTED"


def test_restaurant_assignment_conserved_across_suspend_reinstate(api):
    """PRD §3.6: "Suspending an `ACTIVE` operator moves them to `SUSPENDED` and
    cascades the agreement from `EXECUTED` to `SUSPENDED`. Reinstating requires
    `residency_verified` to still hold true, moves the operator back to
    `ACTIVE`, and cascades the agreement back from `SUSPENDED` to `EXECUTED`."
    PRD §3.6: "execution moves the agreement's `agreement_status` to `EXECUTED`
    and simultaneously moves the restaurant to `ASSIGNED` with
    `current_operator_id` set to this operator."

    Design: Difficulty/compensating_invariant/operator_suspend_reinstate_restores_agreement_executed
    """
    set_clock()
    ctx = setup_active_operator()
    operator_id = ctx["operator"]["id"]
    restaurant_id = ctx["restaurant"]["id"]
    validate_success(api.suspend_operator(operator_id, FC))
    mid = get_success_data(api.get_restaurant(restaurant_id, ADMIN))
    assert mid["restaurant_status"] == "ASSIGNED"
    assert mid["current_operator_id"] == operator_id
    validate_success(api.reinstate_operator(operator_id, FC))
    after = get_success_data(api.get_restaurant(restaurant_id, ADMIN))
    assert after["restaurant_status"] == "ASSIGNED"
    assert after["current_operator_id"] == operator_id

"""Compensating actions that restore a quantity the system should conserve (PRD 3.1, 3.4)."""
import pytest
from test_helpers import (
    api_client, validate_success,
    reset_clock, setup_funded_program, create_advance, approve_advance, get_program,
    create_agent, qualify_agent, create_referral, suspend_agent,
    TEST_USERS, ApiErrorId,
)

COORD = TEST_USERS["coordinator_headers"]
UW = TEST_USERS["underwriter_headers"]


def _program_with_approved_down_payment():
    sc = setup_funded_program(
        variant="CONSERVATIVE", income_cents=30_000_000,
        departing={"address": "36 Departing Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
        new={"address": "37 New Way", "appraised_value_cents": 55_000_000,
             "purchase_price_cents": 50_000_000, "condition_grade": "A"},
    )
    advance = approve_advance(
        create_advance(sc["program"]["id"], sc["loan"]["id"], "DOWN_PAYMENT", 8_000_000)["id"]
    )
    assert advance["status"] == "APPROVED", "Setup failed: advance not approved"
    sc["advance"] = advance
    return sc


def test_rejecting_the_sole_down_payment_returns_the_program_to_pending(api):
    """PRD section 3.4: "On an approved-advance rejection the system unwinds what the
    approval implied: any coordination task that had been moved to `IN_PROGRESS` is
    cancelled, and if the rejected advance was the program's sole down payment advance the
    program's advance axis is returned to `PENDING`."

    Design: Difficulty/compensating_invariant/advance_reject_restores_program_advance_status
    """
    reset_clock()
    sc = _program_with_approved_down_payment()
    assert get_program(sc["program"]["id"])["advance_status"] == "FUNDING"

    validate_success(api.reject_bridge_advance(sc["advance"]["id"], UW), 200)

    after = get_program(sc["program"]["id"])
    assert after["advance_status"] == "PENDING", "the fund transition is compensated"


def test_rejecting_the_sole_down_payment_marks_the_advance_rejected(api):
    """PRD section 3.4: "Rejecting an advance that is `PENDING` carries none of this
    compensation."

    PRD section 3.4: "An underwriter may reject an advance that is `PENDING`, and may also
    reject one that has already been approved provided that no coordination task linked to
    the program has yet been completed."

    Design: Difficulty/compensating_invariant/advance_reject_restores_program_advance_status
    """
    reset_clock()
    sc = _program_with_approved_down_payment()
    rejected = validate_success(api.reject_bridge_advance(sc["advance"]["id"], UW), 200)
    assert rejected["status"] == "REJECTED"
    assert rejected["version"] > sc["advance"]["version"], "rejection is a mutation"


def _qualifying_agent_with_two_referrals(api):
    sc = setup_funded_program(
        variant="CONSERVATIVE", income_cents=30_000_000,
        departing={"address": "38 Departing Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
    )
    agent = create_agent(license_number="LIC-INV")
    qualify_agent(agent["id"])
    program_id = sc["program"]["id"]
    refs = []
    for scope in ("DEPARTING_SIDE", "NEW_SIDE"):
        ref = validate_success(api.create_referral(
            {"agent_id": agent["id"], "bridge_program_id": program_id, "role_scope": scope},
            COORD), 201)
        refs.append(ref)
    sc["agent"], sc["referrals"] = agent, refs
    return sc


def test_suspending_an_agent_voids_every_open_referral_it_holds(api):
    """PRD section 3.1: "Should a partner fall out of good standing, a coordinator can
    suspend an agent that is either `PENDING` or `QUALIFIED`, and suspension is contagious
    in exactly one direction: every referral belonging to that agent whose status is `OPEN`
    is simultaneously moved to `VOIDED`"

    Design: Difficulty/compensating_invariant/suspension_voids_and_restores_referral_counts
    """
    reset_clock()
    sc = _qualifying_agent_with_two_referrals(api)
    for ref in sc["referrals"]:
        assert ref["status"] == "OPEN"

    suspend_agent(sc["agent"]["id"])

    for ref in sc["referrals"]:
        after = validate_success(api.get_referral(ref["id"], COORD), 200)
        assert after["status"] == "VOIDED", "an open referral is voided with its agent"


def test_suspension_recomputes_the_agent_and_program_active_referral_counts(api):
    """PRD section 3.1: "and the `active_referral_count` on both the agent and each affected
    program is recomputed."

    Design: Difficulty/compensating_invariant/suspension_voids_and_restores_referral_counts
    """
    reset_clock()
    sc = _qualifying_agent_with_two_referrals(api)
    program_id = sc["program"]["id"]
    assert validate_success(api.get_agent(sc["agent"]["id"], COORD), 200)[
        "active_referral_count"] == 2
    assert get_program(program_id)["active_referral_count"] == 2

    suspend_agent(sc["agent"]["id"])

    agent_after = validate_success(api.get_agent(sc["agent"]["id"], COORD), 200)
    assert agent_after["active_referral_count"] == 0
    assert get_program(program_id)["active_referral_count"] == 0
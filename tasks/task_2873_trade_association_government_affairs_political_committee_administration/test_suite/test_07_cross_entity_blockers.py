"""Writes refused because of the state of a *different* entity: an impaired
roster, a restricted fund, and a registration the previous request amended."""
from test_helpers import (
    assert_fund_invariants,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import create_activity_payload
from test_helpers.fixtures import (
    COMPLIANCE,
    DIRECTOR,
    TRUSTEE_2,
    board_approve,
    propose_contribution,
    read_candidate,
    read_committee,
    read_contribution,
    read_fund,
    read_member,
    read_position,
    read_registration,
    read_seat,
    register_candidate,
    setup_funded_fund,
    setup_impaired_committee,
    setup_position_at_consensus,
    setup_registration_with_activities,
)

IMPAIRED_BALLOTS = ["SUPPORT", "SUPPORT", "OPPOSE"]


def _impaired_committee_at_consensus():
    roster = setup_impaired_committee(committee_name="Small Manufacturers Subcommittee")
    return setup_position_at_consensus(
        roster=roster,
        ballots=IMPAIRED_BALLOTS,
        position_overrides={"title": "Small Supplier Set-Aside"},
    )


def test_adoption_is_refused_while_the_roster_is_only_impaired():
    """Adoption demands a quorate roster even though balloting did not.

    PRD 3.4: "Adoption applies a stricter roster test than balloting did: the
    committee's `roster_state` must be exactly `QUORATE`, and both `IMPAIRED` and
    `FORMING` are refused with `ERR_COMMITTEE_NOT_QUORATE`."
    PRD 3.2: "three `ASSOCIATE` members supply three seats but only three units of
    weight, so the committee reaches `IMPAIRED` rather than `QUORATE` — enough to
    ballot, not enough to adopt."

    Design: Difficulty/cross_entity_state_dependency/adopt_blocked_by_impaired_committee_roster_rejected
    """
    state = _impaired_committee_at_consensus()
    committee = read_committee(state["committee"]["id"])
    assert committee["seat_count"] == 3
    assert committee["total_voting_weight"] == 3
    assert committee["roster_state"] == "IMPAIRED"

    response = api_client.adopt_position(state["position"]["id"], TRUSTEE_2)

    validate_error(response, "ERR_COMMITTEE_NOT_QUORATE", 409)
    position = read_position(state["position"]["id"])
    assert position["status"] == "CONSENSUS_REACHED"
    assert position["adopted_at"] is None
    assert position["dissent_register_count"] == 0


def test_an_impaired_roster_still_ballots_and_still_reaches_consensus():
    """The two roster gates are deliberately asymmetric.

    PRD 3.3: "The committee's `roster_state` must not be `FORMING`; both
    `QUORATE` and `IMPAIRED` are acceptable here, and a still-forming roster is
    refused with `ERR_COMMITTEE_FORMING`."
    PRD 3.4: "This is the gate that dissent damping can close, as the cascade
    below shows."

    Design: Difficulty/cross_entity_state_dependency/adopt_blocked_by_impaired_committee_roster_rejected
    """
    state = _impaired_committee_at_consensus()

    assert state["position"]["round_number"] == 1
    assert state["position"]["quorum_pct"] == 100.00
    assert state["position"]["consensus_pct"] == 66.67
    assert state["position"]["last_tally_outcome"] == "CONSENSUS"
    assert state["position"]["status"] == "CONSENSUS_REACHED"

    api_client.adopt_position(state["position"]["id"], TRUSTEE_2)

    # The refused adoption ran no cascade link at all.
    for seat in state["seats"]:
        assert read_seat(state["committee"]["id"], seat["id"])["dissent_strikes"] == 0
        assert read_seat(state["committee"]["id"], seat["id"])["status"] == "ACTIVE"
    for member in state["members"]:
        assert read_member(member["id"])["recorded_dissent_count"] == 0


def _fund_restricted_by_an_earlier_approval():
    """Approve one contribution to restrict the fund, then propose another."""
    funded = setup_funded_fund(
        min_reserve_cents=400_000, receipt_amount_cents=600_000, received_date="2026-07-01"
    )
    fund_id = funded["fund"]["id"]
    candidate_a = register_candidate(name="Rep. Jane Alvarez")
    candidate_b = register_candidate(name="Rep. Omar Bennett", district_code="TX-07")
    first = propose_contribution(fund_id, candidate_a["id"], amount_cents=250_000,
                                 memo="Primary support")
    board_approve(first["id"])
    fresh = propose_contribution(fund_id, candidate_b["id"], amount_cents=50_000,
                                 memo="Small general-election support")
    return {**funded, "candidate_a": candidate_a, "candidate_b": candidate_b,
            "approved": first, "fresh": fresh}


def test_board_approval_is_refused_by_the_funds_restricted_posture():
    """The blocker is the fund's posture, not anything on the contribution.

    PRD 3.8: "While the fund's posture is `RESTRICTED`, board approval of any
    contribution drawn on it is refused with `ERR_FUND_RESTRICTED`."
    PRD 3.8: "And `posture` is a pure function of that balance: it reads
    `RESTRICTED` whenever `available_balance_cents` is strictly below
    `min_reserve_cents`, and `OPEN` otherwise."

    Design: Difficulty/cross_entity_state_dependency/board_approve_blocked_by_restricted_fund_posture_rejected
    """
    state = _fund_restricted_by_an_earlier_approval()
    fund = read_fund(state["fund"]["id"])
    assert fund["posture"] == "RESTRICTED"
    assert fund["available_balance_cents"] == 350_000
    # Created after the flip, so the suspension cascade never saw this row.
    assert state["fresh"]["status"] == "PENDING_BOARD"

    response = api_client.board_approve_contribution(state["fresh"]["id"], TRUSTEE_2)

    validate_error(response, "ERR_FUND_RESTRICTED", 409)


def test_the_posture_gate_outranks_the_balance_gate_and_moves_nothing():
    """50,000 cents fits inside 350,000, so only the posture can refuse it.

    PRD 2.11: "13. The fund posture gate on contribution board approval —
    otherwise `ERR_FUND_RESTRICTED` (409)."
    PRD 2.11: "30. The fund balance covers the amount, on board approval —
    otherwise `ERR_INSUFFICIENT_FUND_BALANCE` (422)."

    Design: Difficulty/cross_entity_state_dependency/board_approve_blocked_by_restricted_fund_posture_rejected
    """
    state = _fund_restricted_by_an_earlier_approval()

    api_client.board_approve_contribution(state["fresh"]["id"], TRUSTEE_2)

    unchanged = read_contribution(state["fresh"]["id"])
    assert unchanged["status"] == "PENDING_BOARD"
    assert unchanged["board_approved_by_user_id"] is None

    fund = read_fund(state["fund"]["id"])
    assert fund["committed_balance_cents"] == 250_000
    assert fund["available_balance_cents"] == 350_000
    assert_fund_invariants(fund)

    candidate_b = read_candidate(state["candidate_b"]["id"])
    assert candidate_b["pending_support_cents"] == 50_000
    assert candidate_b["committed_support_cents"] == 0


THRESHOLD_ACTIVITY = {
    "activity_date": "2026-07-05", "hours": 4.0, "expenditure_cents": 1_400_000,
}
NEXT_ACTIVITY = {"activity_date": "2026-07-06", "hours": 1.0, "expenditure_cents": 10_000}


def test_the_threshold_flip_inside_the_previous_log_blocks_the_next_activity():
    """The blocking state was created by the previous successful request.

    PRD 3.5: "Immediately after the accumulator increment, if the registration's
    `amendment_round` is still 0 and its new `ytd_reportable_cents` has reached the
    registration threshold for its jurisdiction — 1,400,000 cents federally,
    200,000 in California, 500,000 in New York — the registration flips `ACTIVE →
    AMENDMENT_PENDING` inside the very same request that created the activity."
    PRD 3.5: "The boundary is inclusive: landing exactly on the threshold flips it.
    The activity itself is still created, and still `LOGGED`."

    Design: Difficulty/cross_entity_state_dependency/log_activity_blocked_by_auto_amendment_pending_registration_rejected
    """
    state = setup_registration_with_activities([THRESHOLD_ACTIVITY])
    registration_id = state["registration"]["id"]
    assert state["activities"][0]["status"] == "LOGGED"

    registration = read_registration(registration_id)
    assert registration["status"] == "AMENDMENT_PENDING"
    assert registration["ytd_reportable_cents"] == 1_400_000
    assert registration["ytd_reportable_hours"] == 4.0
    assert registration["amendment_round"] == 0

    response = api_client.create_lobbying_activity(
        create_activity_payload(registration_id, state["position"]["id"], **NEXT_ACTIVITY),
        DIRECTOR,
    )
    validate_error(response, "ERR_REGISTRATION_NOT_ACTIVE", 409)

    rows, meta = validate_paginated(
        api_client.list_registration_activities(registration_id, COMPLIANCE)
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1
    after = read_registration(registration_id)
    assert after["ytd_reportable_cents"] == 1_400_000
    assert after["ytd_reportable_hours"] == 4.0


def test_certifying_the_amendment_disarms_the_threshold_trigger_for_good():
    """Only certify-amendment consumes the round, and it disarms the trigger.

    PRD 3.5: "A compliance officer opens an amendment, moving `ACTIVE →
    AMENDMENT_PENDING`, and certifies it afterwards, moving `AMENDMENT_PENDING →
    ACTIVE` and incrementing `amendment_round` by one."
    PRD 3.5: "Because the trigger requires `amendment_round` to be 0, it fires at
    most once in a registration's life; a certified amendment disarms it forever,
    and further spending past the threshold no longer disturbs the registration."

    Design: Difficulty/cross_entity_state_dependency/log_activity_blocked_by_auto_amendment_pending_registration_rejected
    """
    state = setup_registration_with_activities([THRESHOLD_ACTIVITY])
    registration_id = state["registration"]["id"]
    payload = create_activity_payload(
        registration_id, state["position"]["id"], **NEXT_ACTIVITY
    )
    validate_error(
        api_client.create_lobbying_activity(payload, DIRECTOR),
        "ERR_REGISTRATION_NOT_ACTIVE",
        409,
    )

    certified = validate_success(
        api_client.certify_registration_amendment(registration_id, COMPLIANCE)
    )
    assert certified["status"] == "ACTIVE"
    assert certified["amendment_round"] == 1

    activity = validate_success(
        api_client.create_lobbying_activity(payload, DIRECTOR), 201
    )
    assert activity["status"] == "LOGGED"

    registration = read_registration(registration_id)
    assert registration["status"] == "ACTIVE"
    assert registration["amendment_round"] == 1
    assert registration["ytd_reportable_cents"] == 1_410_000
    assert registration["ytd_reportable_hours"] == 5.0

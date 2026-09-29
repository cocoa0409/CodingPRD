"""The two four-link cascades of the system: adopting a position over recorded
dissent, and board-approving a contribution out of a thinly funded fund."""
from test_helpers import (
    assert_candidate_accumulator_split,
    assert_fund_invariants,
    assert_fund_terms,
    assert_instant_equals,
)
from test_helpers.constants import DEFAULT_CLOCK_INSTANT
from test_helpers.fixtures import (
    adopt_position,
    read_candidate,
    read_committee,
    read_contribution,
    read_fund,
    read_member,
    read_position,
    read_seat,
    read_vote,
    setup_position_at_consensus,
    setup_quorate_committee,
    setup_suspended_contribution,
)

DISSENT_TEXT = "Our sector carries the cost of this position without the benefit."
# PREMIER and ASSOCIATE support, FULL opposes: 4 of 6 units, exactly 66.67 percent.
SPLIT = ["SUPPORT", "OPPOSE", "SUPPORT"]
DISSENT_ON_FULL = [None, DISSENT_TEXT, None]


def _committee_with_one_recorded_dissent():
    """Adopt a first position over the FULL member's recorded dissent."""
    roster = setup_quorate_committee()
    state = setup_position_at_consensus(
        roster=roster,
        ballots=SPLIT,
        dissent_statements=DISSENT_ON_FULL,
        position_overrides={"title": "Support the Manufacturing Credit"},
    )
    position = adopt_position(state["position"]["id"])
    assert position["dissent_register_count"] == 1
    seat = read_seat(roster["committee"]["id"], roster["seats"][1]["id"])
    assert seat["dissent_strikes"] == 1
    assert seat["status"] == "ACTIVE"
    assert seat["voting_weight"] == 2
    return {"roster": roster, "first_position": position}


def test_the_second_recorded_dissent_dampens_the_seat_and_impairs_the_roster():
    """All four links of the adoption cascade fire inside the one request.

    PRD 3.4: "Once a seat's `dissent_strikes` reaches two, the seat flips `ACTIVE →
    DAMPENED` and its `voting_weight` is re-derived as half the member's tier weight rounded
    down, but never below one".
    PRD 3.4: "Because a seat's `voting_weight` changed, the committee's
    `total_voting_weight` and `roster_state` are recomputed by the rules of §3.2. A
    committee that was `QUORATE` may become `IMPAIRED` as a direct consequence of adopting a
    position over recorded dissent".

    Design: Difficulty/transitive_cascade/adopt_position_cascades_votes_to_members_to_seats_to_committee
    """
    base = _committee_with_one_recorded_dissent()
    roster = base["roster"]
    committee_id = roster["committee"]["id"]
    dissenting_member = roster["members"][1]

    second = setup_position_at_consensus(
        roster=roster,
        ballots=SPLIT,
        dissent_statements=DISSENT_ON_FULL,
        position_overrides={"title": "Support the Apprenticeship Deduction"},
    )
    assert second["position"]["consensus_pct"] == 66.67
    assert second["position"]["status"] == "CONSENSUS_REACHED"

    adopted = adopt_position(second["position"]["id"])

    # Link 1: the position and its dissenting ballot.
    assert adopted["status"] == "ADOPTED"
    assert_instant_equals(adopted["adopted_at"], DEFAULT_CLOCK_INSTANT, "adopted_at")
    assert adopted["dissent_register_count"] == 1
    vote = read_vote(second["position"]["id"], second["votes"][1]["id"])
    assert vote["dissent_status"] == "RECORDED"
    assert vote["ballot_status"] == "CAST"

    # Link 2: the member behind that ballot.
    assert read_member(dissenting_member["id"])["recorded_dissent_count"] == 2

    # Link 3: that member's seat on this position's committee.
    seat = read_seat(committee_id, roster["seats"][1]["id"])
    assert seat["dissent_strikes"] == 2
    assert seat["status"] == "DAMPENED"
    assert seat["voting_weight"] == 1

    # Link 4: the committee's roster health.
    committee = read_committee(committee_id)
    assert committee["seat_count"] == 3
    assert committee["total_voting_weight"] == 5
    assert committee["roster_state"] == "IMPAIRED"


def test_the_adoption_cascade_leaves_every_other_seat_and_member_untouched():
    """Only the dissenting member's own chain moves, and it moves once.

    PRD 3.4: "Because those ballots reached `RECORDED`, each distinct member
    behind them has its `recorded_dissent_count` incremented by one."
    PRD 3.4: "Because that member's recorded dissent grew, its seat on *this
    position's committee* has `dissent_strikes` incremented by one."

    Design: Difficulty/transitive_cascade/adopt_position_cascades_votes_to_members_to_seats_to_committee
    """
    base = _committee_with_one_recorded_dissent()
    roster = base["roster"]
    committee_id = roster["committee"]["id"]

    second = setup_position_at_consensus(
        roster=roster,
        ballots=SPLIT,
        dissent_statements=DISSENT_ON_FULL,
        position_overrides={"title": "Support the Apprenticeship Deduction"},
    )
    adopt_position(second["position"]["id"])

    premier_seat = read_seat(committee_id, roster["seats"][0]["id"])
    associate_seat = read_seat(committee_id, roster["seats"][2]["id"])
    assert premier_seat["voting_weight"] == 3
    assert premier_seat["dissent_strikes"] == 0
    assert premier_seat["status"] == "ACTIVE"
    assert associate_seat["voting_weight"] == 1
    assert associate_seat["dissent_strikes"] == 0
    assert associate_seat["status"] == "ACTIVE"

    assert read_member(roster["members"][0]["id"])["recorded_dissent_count"] == 0
    assert read_member(roster["members"][2]["id"])["recorded_dissent_count"] == 0

    # The earlier position keeps its own register; nothing is counted twice.
    first = read_position(base["first_position"]["id"])
    assert first["dissent_register_count"] == 1
    assert first["status"] == "ADOPTED"


def test_board_approval_commits_the_amount_and_flips_the_fund_to_restricted():
    """The first two links: the fund's commitment and its posture.

    PRD 3.9: "The fund's `committed_balance_cents` grows by the contribution's
    `amount_cents` and `available_balance_cents` is recomputed from the four
    accumulators. In the same step the candidate's `pending_support_cents` falls
    by that amount and its `committed_support_cents` rises by it, so the money
    moves between two candidate accumulators rather than being counted twice."
    PRD 3.9: "If the recomputed `available_balance_cents` is now strictly below
    the fund's `min_reserve_cents`, the fund's `posture` flips `OPEN →
    RESTRICTED`."

    Design: Difficulty/transitive_cascade/board_approve_cascades_fund_posture_to_sibling_contribution_to_candidate
    """
    state = setup_suspended_contribution(
        first_amount_cents=250_000,
        second_amount_cents=200_000,
        min_reserve_cents=400_000,
        receipt_amount_cents=600_000,
    )

    approved = read_contribution(state["contribution_x"]["id"])
    assert approved["status"] == "BOARD_APPROVED"
    assert approved["amount_cents"] == 250_000

    fund = read_fund(state["fund"]["id"])
    assert_fund_terms(
        fund,
        receipts=600_000,
        committed=250_000,
        disbursed=0,
        fees=0,
        available=350_000,
        posture="RESTRICTED",
    )
    assert_fund_invariants(fund)

    candidate_a = read_candidate(state["candidate_a"]["id"])
    assert_candidate_accumulator_split(candidate_a, pending=0, committed=250_000, disbursed=0)


def test_the_restricted_posture_suspends_the_sibling_row_and_rewinds_its_candidate():
    """The last two links: the sibling contribution and its candidate.

    PRD 3.9: "Because the posture became `RESTRICTED`, every *other* contribution
    of that fund still in `PENDING_BOARD` moves `PENDING_BOARD → SUSPENDED`."
    PRD 3.9: "Because those rows left `PENDING_BOARD`, each of their candidates
    has `pending_support_cents` decremented by that row's `amount_cents`. A
    suspended row contributes to no candidate accumulator and to no fund
    accumulator at all."

    Design: Difficulty/transitive_cascade/board_approve_cascades_fund_posture_to_sibling_contribution_to_candidate
    """
    state = setup_suspended_contribution(
        first_amount_cents=250_000,
        second_amount_cents=200_000,
        min_reserve_cents=400_000,
        receipt_amount_cents=600_000,
    )

    sibling = read_contribution(state["contribution_y"]["id"])
    assert sibling["status"] == "SUSPENDED"
    assert sibling["amount_cents"] == 200_000
    assert sibling["board_approved_by_user_id"] is None

    candidate_b = read_candidate(state["candidate_b"]["id"])
    assert_candidate_accumulator_split(candidate_b, pending=0, committed=0, disbursed=0)

    # The suspended row feeds no fund accumulator either.
    fund = read_fund(state["fund"]["id"])
    assert fund["committed_balance_cents"] == 250_000
    assert fund["available_balance_cents"] == 350_000
    assert_fund_invariants(fund)

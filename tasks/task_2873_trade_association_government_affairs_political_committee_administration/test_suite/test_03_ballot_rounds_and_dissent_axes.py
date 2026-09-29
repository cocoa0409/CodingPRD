"""The ballot cycle as a state machine: the reconsideration loop, and the two
independent statuses a single ballot carries."""
from test_helpers import (
    assert_policy_position,
    assert_position_vote,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.fixtures import (
    adopt_position,
    cast_ballots,
    open_ballot_round,
    read_committee,
    read_member,
    read_seat,
    read_vote,
    setup_position_in_balloting,
    tally_round,
)
from test_helpers.test_users import make_member_delegate_headers

DISSENT_TEXT = "The association should not spend member dues on this credit."


def test_a_dissensus_round_sends_the_position_back_for_reconsideration():
    """Quorum reached but support short of the threshold is DISSENSUS.

    PRD 3.4: "If `quorum_pct` is less than the committee's
    `quorum_threshold_pct`, the outcome is `NO_QUORUM`. Otherwise, if
    `consensus_pct` is greater than or equal to the committee's
    `consensus_threshold_pct`, the outcome is `CONSENSUS`. Otherwise the outcome
    is `DISSENSUS`."
    PRD 3.4: "Abstentions therefore count toward reaching quorum but are excluded
    from the consensus denominator, which is the whole point of allowing an
    abstention at all."

    Design: Difficulty/non_linear_state_machine/policy_position_reconsideration_cycle_reopens_second_round
    """
    state = setup_position_in_balloting()
    position_id = state["position"]["id"]
    assert state["position"]["round_number"] == 1

    cast_ballots(position_id, state["members"], ["SUPPORT", "OPPOSE", "ABSTAIN"])
    position = tally_round(position_id)

    assert_policy_position(position)
    assert position["support_weight"] == 3
    assert position["oppose_weight"] == 2
    assert position["abstain_weight"] == 1
    assert position["quorum_pct"] == 100.00
    assert position["consensus_pct"] == 60.00
    assert position["last_tally_outcome"] == "DISSENSUS"
    assert position["status"] == "RECONSIDERATION"
    assert position["round_number"] == 1
    assert position["adopted_at"] is None


def test_reopening_the_round_clears_the_snapshot_and_supersedes_the_old_ballots():
    """Opening the next round zeroes the tally and retires the live ballots.

    PRD 3.3: "It clears the tally snapshot, setting `support_weight`,
    `oppose_weight`, `abstain_weight`, `quorum_pct` and `consensus_pct` back to 0
    and `last_tally_outcome` back to `NONE`."
    PRD 3.3: "And it retires the previous round's ballots: every ballot of this
    position belonging to an earlier round whose `ballot_status` is `CAST` flips
    to `SUPERSEDED`."

    Design: Difficulty/non_linear_state_machine/policy_position_reconsideration_cycle_reopens_second_round
    """
    state = setup_position_in_balloting()
    position_id = state["position"]["id"]
    first_round_votes = cast_ballots(
        position_id, state["members"], ["SUPPORT", "OPPOSE", "ABSTAIN"]
    )
    tally_round(position_id)

    reopened = open_ballot_round(position_id, ballot_deadline_date="2026-09-10")

    assert reopened["status"] == "BALLOTING"
    assert reopened["round_number"] == 2
    assert reopened["ballot_deadline_date"] == "2026-09-10"
    assert reopened["support_weight"] == 0
    assert reopened["oppose_weight"] == 0
    assert reopened["abstain_weight"] == 0
    assert reopened["quorum_pct"] == 0
    assert reopened["consensus_pct"] == 0
    assert reopened["last_tally_outcome"] == "NONE"

    for vote in first_round_votes:
        retired = read_vote(position_id, vote["id"])
        assert retired["ballot_status"] == "SUPERSEDED"
        assert retired["round_number"] == 1


def test_the_second_round_is_scored_on_its_own_ballots_alone():
    """Only ballots of the current round that are still CAST are scored.

    PRD 3.4: "The input set for scoring is narrow and must be read literally:
    ballots of this position whose `round_number` equals the position's current
    `round_number` and whose `ballot_status` is `CAST`. Superseded ballots are
    excluded."
    PRD 3.4: "A `CONSENSUS` outcome moves the position `BALLOTING →
    CONSENSUS_REACHED`."

    Design: Difficulty/non_linear_state_machine/policy_position_reconsideration_cycle_reopens_second_round
    """
    state = setup_position_in_balloting()
    position_id = state["position"]["id"]
    cast_ballots(position_id, state["members"], ["SUPPORT", "OPPOSE", "ABSTAIN"])
    tally_round(position_id)
    open_ballot_round(position_id, ballot_deadline_date="2026-09-10")

    # Only the two heavier members vote in the renegotiated round.
    cast_ballots(position_id, state["members"][:2], ["SUPPORT", "SUPPORT"])
    position = tally_round(position_id)

    assert position["round_number"] == 2
    assert position["support_weight"] == 5
    assert position["oppose_weight"] == 0
    assert position["abstain_weight"] == 0
    assert position["quorum_pct"] == 83.33
    assert position["consensus_pct"] == 100.00
    assert position["last_tally_outcome"] == "CONSENSUS"
    assert position["status"] == "CONSENSUS_REACHED"


def test_withdrawing_a_dissent_leaves_the_opposing_ballot_counting_in_full():
    """The two statuses on a ballot move on independent axes.

    PRD 3.3: "Withdrawing a dissent moves that ballot's `dissent_status` from
    `FILED` to `WITHDRAWN` and leaves `ballot_status` untouched, which means a
    still-`CAST` opposing ballot keeps contributing its full weight to the
    opposition side of the tally — the withdrawal is a statement about the formal
    record, not about the vote."
    PRD 3.4: "A ballot's `dissent_status` is irrelevant here — a withdrawn dissent
    still leaves an opposing ballot counting at its full weight."

    Design: Difficulty/non_linear_state_machine/position_vote_parallel_ballot_and_dissent_axes_move_independently
    """
    state = setup_position_in_balloting()
    position_id = state["position"]["id"]
    votes = cast_ballots(
        position_id,
        state["members"],
        ["SUPPORT", "SUPPORT", "OPPOSE"],
        dissent_statements=[None, None, DISSENT_TEXT],
    )
    dissenting_vote = votes[2]
    dissenting_member = state["members"][2]

    assert_position_vote(dissenting_vote)
    assert dissenting_vote["ballot"] == "OPPOSE"
    assert dissenting_vote["ballot_status"] == "CAST"
    assert dissenting_vote["dissent_status"] == "FILED"
    assert dissenting_vote["weight_snapshot"] == 1

    withdrawn = validate_success(
        api_client.withdraw_dissent(
            position_id,
            dissenting_vote["id"],
            make_member_delegate_headers(dissenting_member["id"]),
        )
    )
    assert withdrawn["dissent_status"] == "WITHDRAWN"
    assert withdrawn["ballot_status"] == "CAST"
    assert withdrawn["ballot"] == "OPPOSE"

    position = tally_round(position_id)
    assert position["support_weight"] == 5
    assert position["oppose_weight"] == 1
    assert position["abstain_weight"] == 0
    assert position["quorum_pct"] == 100.00
    assert position["consensus_pct"] == 83.33
    assert position["last_tally_outcome"] == "CONSENSUS"
    assert position["status"] == "CONSENSUS_REACHED"


def test_a_withdrawn_dissent_is_never_recorded_by_adoption():
    """Adoption registers only dissents still standing on a live opposing ballot.

    PRD 3.4: "Every ballot of this position whose `round_number` equals the
    position's `round_number`, whose `ballot_status` is `CAST`, whose `ballot` is
    `OPPOSE`, and whose `dissent_status` is `FILED` moves to `dissent_status`
    `RECORDED`."
    PRD 3.4: "Ballots that are superseded, from an earlier round, not opposing, or
    whose dissent was withdrawn are all left alone — a `WITHDRAWN` dissent can
    never become `RECORDED`."

    Design: Difficulty/non_linear_state_machine/position_vote_parallel_ballot_and_dissent_axes_move_independently
    """
    state = setup_position_in_balloting()
    position_id = state["position"]["id"]
    votes = cast_ballots(
        position_id,
        state["members"],
        ["SUPPORT", "SUPPORT", "OPPOSE"],
        dissent_statements=[None, None, DISSENT_TEXT],
    )
    dissenting_member = state["members"][2]
    dissenting_seat = state["seats"][2]
    validate_success(
        api_client.withdraw_dissent(
            position_id, votes[2]["id"], make_member_delegate_headers(dissenting_member["id"])
        )
    )
    tally_round(position_id)

    position = adopt_position(position_id)

    assert position["status"] == "ADOPTED"
    assert position["dissent_register_count"] == 0
    vote = read_vote(position_id, votes[2]["id"])
    assert vote["dissent_status"] == "WITHDRAWN"
    assert vote["ballot_status"] == "CAST"
    assert read_member(dissenting_member["id"])["recorded_dissent_count"] == 0
    seat = read_seat(state["committee"]["id"], dissenting_seat["id"])
    assert seat["dissent_strikes"] == 0
    assert seat["status"] == "ACTIVE"
    assert seat["voting_weight"] == 1
    committee = read_committee(state["committee"]["id"])
    assert committee["total_voting_weight"] == 6
    assert committee["roster_state"] == "QUORATE"

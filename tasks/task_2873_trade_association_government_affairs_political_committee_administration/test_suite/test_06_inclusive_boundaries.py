"""Values that land exactly on a boundary: a consensus share on its threshold,
an empty match set, and a contribution on its ceiling."""
from test_helpers import (
    assert_action_alert,
    assert_instant_equals,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.constants import DEFAULT_CLOCK_INSTANT
from test_helpers.factories import create_contribution_payload, dispatch_alert_payload
from test_helpers.fixtures import (
    DIRECTOR,
    cast_ballots,
    create_committee,
    draft_position,
    open_ballot_round,
    open_fund,
    propose_contribution,
    read_campaign,
    read_candidate,
    register_candidate,
    seat_member,
    setup_campaign_on_adopted_position,
    setup_quorate_committee,
    tally_round,
)

# PREMIER and ASSOCIATE support, FULL opposes: 4 of the 6 units that took a
# side, which is 66.6666... percent and rounds half up to exactly 66.67.
SPLIT = ["SUPPORT", "OPPOSE", "SUPPORT"]


def _two_committees_one_hundredth_apart():
    """One roster seated on two committees whose consensus thresholds differ."""
    roster = setup_quorate_committee(committee_name="Committee At The Threshold")
    higher = create_committee(
        name="Committee One Hundredth Higher",
        jurisdiction_scope="FEDERAL",
        quorum_threshold_pct=60.00,
        consensus_threshold_pct=66.68,
    )
    for index, member in enumerate(roster["members"]):
        seat_member(higher["id"], member["id"], **({"seat_role": "CHAIR"} if index == 0 else {}))
    return {"roster": roster, "higher": higher}


def _ballot_to_tally(committee_id, members, title):
    position = draft_position(committee_id, title=title)
    open_ballot_round(position["id"])
    cast_ballots(position["id"], members, SPLIT)
    return tally_round(position["id"])


def test_a_consensus_share_exactly_on_the_threshold_reaches_consensus():
    """Equality satisfies the inclusive consensus comparison.

    PRD 3.4: "Both threshold comparisons are inclusive at the boundary: a
    `quorum_pct` exactly equal to the quorum threshold passes, and a
    `consensus_pct` exactly equal to the consensus threshold reaches consensus."
    PRD 2.6: "where a threshold comparison is made against a rounded percentage,
    the comparison is made against the **rounded** value, not the unrounded one".

    Design: Difficulty/boundary_precision_check/consensus_pct_rounds_up_onto_the_threshold_exactly
    """
    state = _two_committees_one_hundredth_apart()
    roster = state["roster"]

    position = _ballot_to_tally(
        roster["committee"]["id"], roster["members"], "Credit Position At The Threshold"
    )

    assert position["support_weight"] == 4
    assert position["oppose_weight"] == 2
    assert position["abstain_weight"] == 0
    assert position["quorum_pct"] == 100.00
    assert position["consensus_pct"] == 66.67
    assert position["last_tally_outcome"] == "CONSENSUS"
    assert position["status"] == "CONSENSUS_REACHED"


def test_the_same_share_one_hundredth_below_a_higher_threshold_dissents():
    """The identical ballots diverge on one hundredth of a percentage point.

    PRD 3.4: "`consensus_pct` is one hundred times `support_weight` divided by the
    sum of `support_weight` and `oppose_weight`, rounded half up to two decimals."
    PRD 3.4: "A `NO_QUORUM` or `DISSENSUS` outcome moves it `BALLOTING → RECONSIDERATION`
    while `round_number` is still below three".

    Design: Difficulty/boundary_precision_check/consensus_pct_rounds_up_onto_the_threshold_exactly
    """
    state = _two_committees_one_hundredth_apart()

    position = _ballot_to_tally(
        state["higher"]["id"], state["roster"]["members"], "Credit Position Just Short"
    )

    assert position["consensus_pct"] == 66.67
    assert position["quorum_pct"] == 100.00
    assert position["last_tally_outcome"] == "DISSENSUS"
    assert position["status"] == "RECONSIDERATION"
    # The reconsideration branch does not itself open the next round.
    assert position["round_number"] == 1


def test_an_alert_that_matches_nobody_is_persisted_as_no_match_at_zero_cost():
    """An empty match set is a record, not an error.

    PRD 3.7: "An empty match set is emphatically **not** an error — the alert is
    still persisted, as a `NO_MATCH` record, so the association can see which
    districts it cannot reach. Either way `dispatched_at` is stamped with the
    logical clock instant."
    PRD 3.7: "The alert's `cost_cents` is its `unit_cost_cents` multiplied by
    `matched_member_count`, which is 0 when the match set is empty."

    Design: Difficulty/boundary_precision_check/empty_constituent_match_set_persists_alert_with_no_match
    """
    state = setup_campaign_on_adopted_position()

    alert = validate_success(
        api_client.dispatch_alert(
            state["campaign"]["id"],
            dispatch_alert_payload(
                target_district_code="NY-05",
                target_chamber="US_HOUSE",
                message_subject="No constituents live here",
                unit_cost_cents=30_000,
            ),
            DIRECTOR,
        ),
        201,
    )

    assert_action_alert(alert)
    assert alert["status"] == "NO_MATCH"
    assert alert["matched_member_ids"] == []
    assert alert["matched_member_count"] == 0
    assert alert["cost_cents"] == 0
    assert_instant_equals(alert["dispatched_at"], DEFAULT_CLOCK_INSTANT, "dispatched_at")


def test_a_no_match_alert_opens_no_cooling_window_and_leaves_the_campaign_planned():
    """Because last_alert_at never moved, the next alert may go out at once.

    PRD 3.7: "`last_alert_at` is set to the alert's `dispatched_at` **only** for a
    `DISPATCHED` alert; a `NO_MATCH` alert leaves `last_alert_at` exactly as it
    was and therefore never starts a cooling window, so a district with no
    reachable members can be retried immediately."
    PRD 3.7: "`unmatched_alert_count` increments only for a `NO_MATCH` alert."

    Design: Difficulty/boundary_precision_check/empty_constituent_match_set_persists_alert_with_no_match
    """
    state = setup_campaign_on_adopted_position()
    campaign_id = state["campaign"]["id"]

    first = validate_success(
        api_client.dispatch_alert(
            campaign_id,
            dispatch_alert_payload(target_district_code="NY-05", target_chamber="US_HOUSE",
                                   message_subject="No constituents live here",
                                   unit_cost_cents=30_000),
            DIRECTOR,
        ),
        201,
    )
    second = validate_success(
        api_client.dispatch_alert(
            campaign_id,
            dispatch_alert_payload(target_district_code="NY-05", target_chamber="US_SENATE",
                                   message_subject="Still no constituents",
                                   unit_cost_cents=30_000),
            DIRECTOR,
        ),
        201,
    )

    assert first["status"] == "NO_MATCH"
    assert second["status"] == "NO_MATCH"

    campaign = read_campaign(campaign_id)
    assert campaign["status"] == "PLANNED"
    assert campaign["alert_count"] == 2
    assert campaign["unmatched_alert_count"] == 2
    assert campaign["matched_member_total"] == 0
    assert campaign["cumulative_cost_cents"] == 0
    assert campaign["last_alert_at"] is None
    assert campaign["disclosure_required"] is False


# An INCUMBENT scoring 0.45 x 90.00 + 0.25 x 80 + 0.20 x 100 = 80.50 earns half
# of the 500,000 cent federal limit.
CEILING = 250_000


def test_a_contribution_exactly_equal_to_the_ceiling_is_accepted():
    """The ceiling comparison is inclusive.

    PRD 3.9: "If the proposed `amount_cents` exceeds `max_allowed_cents` the
    proposal is refused with `ERR_CONTRIBUTION_LIMIT_EXCEEDED`; an amount exactly
    equal to `max_allowed_cents` is accepted, because the boundary is inclusive."
    PRD 3.9: "The score then selects a share of that limit: a `support_score` of
    at least 85.00 earns the full limit, a score of at least 70.00 earns half of
    it, and a score of at least 55.00 earns a quarter of it."

    Design: Difficulty/boundary_precision_check/contribution_amount_exactly_equal_to_max_allowed_then_one_cent_over
    """
    fund = open_fund(min_reserve_cents=0)
    candidate = register_candidate(name="Rep. Jane Alvarez")

    contribution = propose_contribution(
        fund["id"], candidate["id"], amount_cents=CEILING,
        memo="Exactly at the tier ceiling",
    )

    assert contribution["support_score"] == 80.50
    assert contribution["max_allowed_cents"] == CEILING
    assert contribution["amount_cents"] == CEILING
    assert contribution["status"] == "PENDING_BOARD"

    scored = read_candidate(candidate["id"])
    assert scored["latest_support_score"] == 80.50
    assert scored["pending_support_cents"] == CEILING


def test_one_cent_past_the_remaining_headroom_is_refused():
    """A pending row already consumes headroom, so the next cent is over.

    PRD 3.9: "Separately, compute what the candidate has already absorbed in this
    election cycle: the sum of `amount_cents` over that candidate's contributions
    whose status is `PENDING_BOARD`, `SUSPENDED`, `BOARD_APPROVED` or
    `DISBURSED`."
    PRD 3.9: "The remaining room is the jurisdiction limit less that
    already-absorbed total, floored at 0. `max_allowed_cents` is then the smaller
    of the tier allowance and the remaining room."

    Design: Difficulty/boundary_precision_check/contribution_amount_exactly_equal_to_max_allowed_then_one_cent_over
    """
    fund = open_fund(min_reserve_cents=0)
    candidate = register_candidate(name="Rep. Jane Alvarez")
    propose_contribution(fund["id"], candidate["id"], amount_cents=CEILING)

    response = api_client.create_pac_contribution(
        create_contribution_payload(
            fund["id"], candidate["id"], amount_cents=CEILING + 1,
            memo="One cent over the remaining headroom",
        ),
        DIRECTOR,
    )
    validate_error(response, "ERR_CONTRIBUTION_LIMIT_EXCEEDED", 422)

    rows, meta = validate_paginated(
        api_client.list_candidate_pac_contributions(candidate["id"], DIRECTOR)
    )
    assert meta["total_count"] == 1
    assert rows[0]["amount_cents"] == CEILING
    assert read_candidate(candidate["id"])["pending_support_cents"] == CEILING

    # The refusal was the single cent, not the tier: the same amount again fits.
    again = propose_contribution(fund["id"], candidate["id"], amount_cents=CEILING)
    assert again["max_allowed_cents"] == CEILING
    assert again["status"] == "PENDING_BOARD"

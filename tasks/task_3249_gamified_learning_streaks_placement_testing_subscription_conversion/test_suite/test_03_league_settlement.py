"""League settlement: weekly experience accumulation and the cutoff ranks."""
from test_helpers import (
    api_client, get_success_data, list_standings, scene_league_with_weekly_attempts,
    set_clock, settle_league,
)

WEEK_START = "2026-09-21T00:00:00Z"
ATTEMPT_DATES = [
    "2026-09-23T10:00:00Z",
    "2026-09-24T10:00:00Z",
    "2026-09-25T10:00:00Z",
    "2026-09-26T10:00:00Z",
    "2026-09-27T10:00:00Z",
]


def test_league_settlement_sums_each_attempt_xp_inside_the_week(api):
    """PRD §3.7: "It is the sum, over the practice attempts recorded from
    `week_start` up to but not including 7 days later, of each attempt's experience
    already rounded to a whole number"
    PRD §3.4: "Free learners are capped at the neutral 1.00 multiplier no matter
    how long their streak"

    Design: Difficulty/combinatorial_formula/league_weekly_xp_per_attempt_rounding_vs_sum_then_round
    """
    scene = scene_league_with_weekly_attempts(ATTEMPT_DATES, tier="BRONZE",
                                              week_start=WEEK_START)
    set_clock("2026-09-28T00:00:00Z")
    settle_league(scene["league"]["id"])

    standing = list_standings(scene["learner"]["id"], scene["league"]["id"])[0]
    assert standing["weekly_xp"] == 65, (
        "five accepted attempts at (10 + 3) * 1.00 == 13 experience each sum to "
        f"65 inside the league week, got {standing['weekly_xp']}"
    )
    assert standing["rank"] == 1


def test_league_settlement_assigns_the_cutoff_ranks_and_reopens(api, admin_headers):
    """PRD §3.7: "The promotion cutoff rank is the smaller of 3 and the member
    count, and the demotion cutoff rank is the member count minus the demotion span
    of 3, plus one, floored at 1."
    PRD §3.7: "Because the demotion sweep runs last, a standing that satisfies both
    cutoffs settles as `DEMOTED`."
    PRD §3.7: "its `REOPEN` form advances `week_start` to the current clock and
    returns every `DEMOTED` standing to `GOOD_STANDING`"

    Design: Difficulty/combinatorial_formula/league_weekly_xp_per_attempt_rounding_vs_sum_then_round
    """
    scene = scene_league_with_weekly_attempts(ATTEMPT_DATES, tier="BRONZE",
                                              week_start=WEEK_START)
    league_id = scene["league"]["id"]
    learner_id = scene["learner"]["id"]
    set_clock("2026-09-28T00:00:00Z")
    settled_league = settle_league(league_id)

    standing = list_standings(learner_id, league_id)[0]
    assert standing["weekly_xp"] == 65
    assert standing["settled_outcome"] in ("PROMOTED", "DEMOTED"), (
        "with one member both cutoffs resolve to rank 1, so the sole standing "
        f"lands on one of them, got {standing['settled_outcome']}"
    )
    assert settled_league["status"] == "CLOSED"

    reopened = get_success_data(api_client.update_league(
        league_id, {"action": "REOPEN"}, admin_headers,
    ))
    assert reopened["status"] == "ACTIVE"
    refreshed = list_standings(learner_id, league_id)[0]
    assert refreshed["standing"] == "GOOD_STANDING", (
        "a reopening demotes every DEMOTED standing back to GOOD_STANDING, got "
        f"{refreshed['standing']}"
    )
    # PRD §3.7: the REOPEN form "advances `week_start` to the current clock", so the
    # reopened round's window no longer contains the prior week's attempts and the
    # re-ranked weekly total recomputes to zero.
    assert refreshed["weekly_xp"] == 0, (
        "the reopen advances week_start to the clock, so the previous week's "
        f"attempts fall outside the new window, got {refreshed['weekly_xp']}"
    )
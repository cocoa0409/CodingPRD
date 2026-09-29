"""Multi-factor formulas whose evaluation order is part of the contract:
where the rounding happens, which composite the penalty band is read from, and
how two independent weight tables combine under a capped input.
"""
import pytest

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    expected_crew_contribution,
    expected_crew_strength_index,
)
from test_helpers.constants import INSTANT_G3_KICKOFF


# ─── Round per play, then sum ──────────────────────────

@pytest.fixture
def two_high_impact_missed_calls():
    """Two identical high-impact missed calls on the same umpire, the first
    already posted and the second still a draft."""
    ctx = fx.played_solo_game()
    game_id = ctx["game"]["id"]
    official_id = ctx["official"]["id"]
    ctx["first"] = fx.posted_grade(
        game_id,
        official_id,
        play_ref="Q1-P11",
        call_category="PASS_INTERFERENCE",
        grade_code="MISSED_CALL",
        impact="HIGH",
    )
    ctx["second"] = fx.grade_play(
        game_id,
        official_id,
        play_ref="Q4-P02",
        call_category="ROUGHING_PASSER",
        grade_code="MISSED_CALL",
        impact="HIGH",
    )
    return ctx


def test_each_play_rounds_its_own_error_points_when_it_is_written(
    two_high_impact_missed_calls,
):
    """Both plays store 2.63, the rounded value of the raw product 2.625.

    PRD §3.6: "A missed call of `HIGH` impact by an umpire therefore scores 1.50
    times 1.75 times 1.00, which is 2.625 and rounds to 2.63; the same call by a
    referee scores 1.50 times 1.75 times 1.20, which is exactly 3.15; an
    incorrect call of `MEDIUM` impact by a referee scores 1.00 times 1.00 times
    1.20, which is 1.20; a missed call of `LOW` impact scores 0.75 for an umpire
    and 0.90 for a referee."

    Design: Difficulty/combinatorial_formula/error_points_round_per_play_then_sum_mode_b
    """
    assert two_high_impact_missed_calls["first"]["error_points"] == 2.63
    assert two_high_impact_missed_calls["second"]["error_points"] == 2.63


def test_the_season_aggregate_sums_already_rounded_per_play_values(
    two_high_impact_missed_calls,
):
    """Posting the second grade lands the season record on 5.26 and an index of
    47.40, not the 5.25 and 47.50 that summing raw products would give.

    PRD §3.6: "Round-then-sum is the contract: two missed calls of `HIGH` impact
    by an umpire give 2.63 plus 2.63, which is 5.26, where summing the raw
    products first and rounding afterwards would wrongly give 5.25."

    Design: Difficulty/combinatorial_formula/error_points_round_per_play_then_sum_mode_b
    """
    official_id = two_high_impact_missed_calls["official"]["id"]

    fx.post_grade(two_high_impact_missed_calls["second"]["id"])
    record = fx.season_record_for(official_id)

    assert record["graded_play_count"] == 2
    assert record["weighted_error_points"] == 5.26
    assert record["accuracy_index"] == 47.40


def test_two_graded_plays_miss_the_play_count_floor_for_eligibility(
    two_high_impact_missed_calls,
):
    """Even setting accuracy aside, two graded plays are below the minimum of
    three, so the record is not accuracy eligible.

    PRD §3.6: "`accuracy_eligible` is then true when `accuracy_index` is greater
    than or equal to the program's `accuracy_eligibility_threshold` **and**
    `graded_play_count` is greater than or equal to the program's
    `min_graded_plays_for_eligibility`."

    Design: Difficulty/combinatorial_formula/error_points_round_per_play_then_sum_mode_b
    """
    official_id = two_high_impact_missed_calls["official"]["id"]

    fx.post_grade(two_high_impact_missed_calls["second"]["id"])
    record = fx.season_record_for(official_id)

    assert record["graded_play_count"] == 2
    assert record["accuracy_eligible"] is False


# ─── The retention penalty band ────────────────────────

@pytest.fixture
def retention_scenario():
    """An umpire with a 95.00 final accuracy index, one completed and one
    withdrawn assignment, and no clinic attendance on file."""
    ctx = fx.finalized_game_with_final_grades()
    spare = fx.schedule_game(
        ctx["program"]["id"],
        home_team_code="NYJ",
        away_team_code="KAN",
        venue_market_code="NYJ",
        kickoff_utc=INSTANT_G3_KICKOFF,
    )
    spare_assignment = fx.propose_assignment(
        spare["id"],
        ctx["official"]["id"],
        "UMPIRE",
        expected_game_version=spare["version"],
    )
    fx.withdraw_assignment(spare_assignment["id"], "personal availability")
    ctx["spare_game"] = spare
    ctx["withdrawn_assignment"] = spare_assignment
    return ctx


def test_availability_component_divides_completed_work_by_settled_obligations(
    retention_scenario,
):
    """One completed and one withdrawn assignment give an availability component
    of 50.00 alongside the 95.00 final index.

    PRD §3.9: "The server counts that official's assignments in `COMPLETED`
    status as the numerator, and counts their assignments in `COMPLETED`,
    `VOIDED` or `WITHDRAWN` status as the obligation total."

    Design: Difficulty/combinatorial_formula/retention_penalty_band_selected_from_pre_penalty_score_mode_c
    """
    fx.lock_postseason(retention_scenario["program"]["id"])

    record = fx.season_record_for(retention_scenario["official"]["id"])

    assert record["accuracy_variant"] == "FINAL"
    assert record["accuracy_index"] == 95.00
    assert record["availability_component"] == 50.00


def test_the_penalty_band_is_read_from_the_pre_penalty_composite(
    retention_scenario,
):
    """The raw composite of 81.50 selects a rate of 5.00, giving 76.50 and
    DEVELOP rather than the 72.50 and RELEASE a re-banded reading would produce.

    PRD §3.9: "Selecting the band from the post-penalty number instead would
    re-band 76.50 below 80.00, apply a rate of 9.00, produce 72.50, and recommend
    `RELEASE` — the circular reading changes both the score and the official's
    employment, which is why the band is fixed to the pre-penalty composite."

    Design: Difficulty/combinatorial_formula/retention_penalty_band_selected_from_pre_penalty_score_mode_c
    """
    fx.lock_postseason(retention_scenario["program"]["id"])

    record = fx.season_record_for(retention_scenario["official"]["id"])

    assert record["retention_score"] == 76.50
    assert record["retention_recommendation"] == "DEVELOP"


def test_a_develop_recommendation_leaves_the_official_active(retention_scenario):
    """Only a RELEASE recommendation releases an official, so this one keeps
    working.

    PRD §3.9: "Fourth, every record whose `retention_recommendation` came out as
    `RELEASE` has its linked official's `status` set to `RELEASED` — a
    system-driven transition out of `ACTIVE`, `PROBATION` or `SUSPENDED` — with
    that official's `version` bumped by 1 and that official's `PROPOSED` and
    `CONFIRMED` assignments voided."

    Design: Difficulty/combinatorial_formula/retention_penalty_band_selected_from_pre_penalty_score_mode_c
    """
    fx.lock_postseason(retention_scenario["program"]["id"])

    official = fx.read_official(retention_scenario["official"]["id"])

    assert official["status"] == "ACTIVE"


# ─── Two weight tables under a capped input ────────────

def test_crew_strength_caps_seasons_of_experience_at_twelve():
    """A fourteen-season referee is scored at twelve seasons, so the crew reads
    8.64 rather than the 9.68 an uncapped reading would give.

    PRD §3.4: "Each included assignment contributes points equal to the lesser of
    12 and its official's `seasons_experience`, multiplied by a tier weight of
    1.00 for `TIER_1`, 0.80 for `TIER_2` or 0.60 for `TIER_3`, multiplied again
    by a position weight of 1.30 for `REFEREE`, 1.00 for `UMPIRE` or 0.85 for
    `DOWN_JUDGE` — where the position weight is read from the *assignment's*
    `position`, not from the official's registered position — and the product is
    rounded half up to two decimal places."

    Design: Difficulty/combinatorial_formula/crew_strength_experience_cap_and_two_weight_tables_mode_a
    """
    ctx = fx.crew_game()

    game = fx.read_game(ctx["game"]["id"])

    assert game["crew_strength_index"] == 8.64
    assert game["crew_strength_index"] != 9.68
    assert game["crew_posture"] == "STAFFED"
    assert game["confirmed_crew_count"] == 2


def test_each_assignment_is_weighted_by_its_own_crew_position():
    """The referee slot is weighted at 1.30 and the umpire slot at 1.00, summing
    to 17.28 and yielding 8.64 over the required crew of two.

    PRD §3.4: "A referee at `TIER_2` with 14 seasons behind them contributes 12
    times 0.80 times 1.30, which is 12.48; an umpire at `TIER_2` with 6 seasons
    contributes 6 times 0.80 times 1.00, which is 4.80."

    Design: Difficulty/combinatorial_formula/crew_strength_experience_cap_and_two_weight_tables_mode_a
    """
    ctx = fx.crew_game()
    referee_points = expected_crew_contribution(14, "TIER_2", "REFEREE")
    umpire_points = expected_crew_contribution(6, "TIER_2", "UMPIRE")

    game = fx.read_game(ctx["game"]["id"])

    assert referee_points == 12.48
    assert umpire_points == 4.80
    assert game["crew_strength_index"] == expected_crew_strength_index(
        [referee_points, umpire_points], 2
    )
    assert game["crew_strength_index"] == 8.64
    assert game["crew_strength_index"] != 7.20

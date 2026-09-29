"""Dual-variant derivations: the same rows, scored two different ways.

An official's accuracy record and a game's crew strength each exist in two
variants, and the variant marker on the stored row says which inclusion set
produced the number.
"""
import pytest

from test_helpers import fixtures as fx
from test_helpers.assertions import assert_season_record
from test_helpers.constants import (
    INSTANT_G1_KICKOFF,
    INSTANT_G1_POSTGAME,
    INSTANT_G2_KICKOFF,
    INSTANT_G2_POSTGAME,
)


# ─── accuracy_index PROVISIONAL vs FINAL ───────────────

@pytest.fixture
def two_game_accuracy_scenario():
    """One umpire with three FINAL grades on a finalized game and one POSTED
    grade on a game that never finalized."""
    ctx = fx.finalized_game_with_final_grades()
    program_id = ctx["program"]["id"]
    umpire_id = ctx["official"]["id"]

    second = fx.schedule_game(
        program_id,
        home_team_code="DAL",
        away_team_code="PHI",
        venue_market_code="DAL",
        kickoff_utc=INSTANT_G2_KICKOFF,
    )
    assignment = fx.propose_assignment(
        second["id"], umpire_id, "UMPIRE", expected_game_version=second["version"]
    )
    fx.confirm_assignment(assignment["id"])
    fx.pin_clock(INSTANT_G2_KICKOFF)
    fx.kickoff(second["id"])
    fx.pin_clock(INSTANT_G2_POSTGAME)
    fx.mark_played(second["id"])
    ctx["second_game"] = second
    ctx["unfinalized_grade"] = fx.posted_grade(
        second["id"],
        umpire_id,
        play_ref="Q1-P03",
        call_category="PASS_INTERFERENCE",
        grade_code="MISSED_CALL",
        impact="HIGH",
    )
    return ctx


def test_provisional_accuracy_counts_posted_and_final_grades_alike(
    two_game_accuracy_scenario,
):
    """In season, four graded plays across two games read 3.38 error points and
    an index of 83.10.

    PRD §3.6: "The provisional view has four plays and 3.38 weighted error
    points: 3.38 divided by 4 is 0.845, multiplied by 20.00 is 16.90, giving an
    index of 83.10."

    Design: Difficulty/dual_variant_calc/accuracy_index_provisional_vs_final_on_season_record
    """
    official_id = two_game_accuracy_scenario["official"]["id"]

    record = fx.season_record_for(official_id)

    assert_season_record(record)
    assert record["accuracy_variant"] == "PROVISIONAL"
    assert record["graded_play_count"] == 4
    assert record["weighted_error_points"] == 3.38
    assert record["accuracy_index"] == 83.10


def test_final_accuracy_variant_drops_the_grade_left_posted(
    two_game_accuracy_scenario,
):
    """The postseason lock rescores the same four grades over the three that
    reached FINAL, moving the index from 83.10 to 95.00.

    PRD §3.6: "The final view has three plays and 0.75 weighted error points:
    0.75 divided by 3 is 0.25, multiplied by 20.00 is 5.00, giving an index of
    95.00."

    Design: Difficulty/dual_variant_calc/accuracy_index_provisional_vs_final_on_season_record
    """
    program_id = two_game_accuracy_scenario["program"]["id"]
    official_id = two_game_accuracy_scenario["official"]["id"]
    before = fx.season_record_for(official_id)

    fx.lock_postseason(program_id)
    after = fx.season_record_for(official_id)

    assert after["accuracy_variant"] == "FINAL"
    assert after["graded_play_count"] == 3
    assert after["weighted_error_points"] == 0.75
    assert after["accuracy_index"] == 95.00
    assert round(after["accuracy_index"] - before["accuracy_index"], 2) == 11.90


def test_final_variant_eligibility_and_the_programs_eligible_count(
    two_game_accuracy_scenario,
):
    """Rescored to 95.00 over three plays, the record is accuracy eligible and
    the locked program counts one eligible official.

    PRD §3.1: "A season program's `eligible_official_count` is never supplied by
    a client. It stays at 0 until the postseason lock recomputes it, at which
    point it becomes the number of that program's season records whose
    postseason eligibility flag is true."

    Design: Difficulty/dual_variant_calc/accuracy_index_provisional_vs_final_on_season_record
    """
    program_id = two_game_accuracy_scenario["program"]["id"]
    official_id = two_game_accuracy_scenario["official"]["id"]

    locked = fx.lock_postseason(program_id)
    record = fx.season_record_for(official_id)

    assert record["accuracy_eligible"] is True
    assert record["retention_recommendation"] == "RETAIN"
    assert locked["status"] == "POSTSEASON_LOCKED"
    assert locked["eligible_official_count"] == 1


# ─── crew_strength_index PROJECTED vs REALIZED ─────────

@pytest.fixture
def crew_repricing_scenario():
    """A two-person crew whose umpire is voided by a suspension while the game is
    in progress, so only the referee reaches COMPLETED."""
    ctx = fx.crew_game()
    fx.pin_clock(INSTANT_G1_KICKOFF)
    ctx["kicked_off"] = fx.kickoff(ctx["game"]["id"])
    ctx["discipline"] = fx.open_discipline(
        ctx["umpire"]["id"], "CONDUCT", "SUSPENSION", suspension_games=2
    )
    fx.pin_clock(INSTANT_G1_POSTGAME)
    fx.mark_played(ctx["game"]["id"])
    return ctx


def test_projected_crew_strength_at_kickoff_scores_the_whole_crew(
    crew_repricing_scenario,
):
    """Kickoff stores the projected index of 8.64 for a referee contributing
    12.48 and an umpire contributing 4.80 over a required crew of two.

    PRD §3.4: "With a required crew of 2, the two contributions above sum to
    17.28 and yield an index of 8.64."

    Design: Difficulty/dual_variant_calc/crew_strength_index_projected_vs_realized_on_game
    """
    kicked_off = crew_repricing_scenario["kicked_off"]

    assert kicked_off["crew_strength_variant"] == "PROJECTED"
    assert kicked_off["crew_strength_index"] == 8.64


def test_realized_crew_strength_at_finalization_scores_only_completed_work(
    crew_repricing_scenario,
):
    """Finalization rescores the crew over its COMPLETED assignments alone,
    dropping the voided umpire and keeping the required crew size as divisor.

    PRD §3.4: "In the crew above, if the umpire is voided by a suspension and
    only the referee reaches `COMPLETED`, the realized index is 12.48 divided by
    2, which is 6.24 — not 12.48, because the required crew size stays the
    divisor."

    Design: Difficulty/dual_variant_calc/crew_strength_index_projected_vs_realized_on_game
    """
    finalized = fx.finalize_game(crew_repricing_scenario["game"]["id"])

    assert finalized["crew_strength_variant"] == "REALIZED"
    assert finalized["crew_strength_index"] == 6.24


def test_the_voided_assignment_is_excluded_while_the_completed_one_counts(
    crew_repricing_scenario,
):
    """The realized variant's inclusion set is exactly the COMPLETED
    assignments, and the suspended umpire's row is VOIDED rather than completed.

    PRD §3.4: "The `REALIZED` variant includes assignments in `COMPLETED` status
    only, so anything `WITHDRAWN`, `SUPERSEDED` or `VOIDED` before kickoff
    contributes nothing; it is computed once, at finalization."

    Design: Difficulty/dual_variant_calc/crew_strength_index_projected_vs_realized_on_game
    """
    fx.finalize_game(crew_repricing_scenario["game"]["id"])

    umpire_assignment = fx.read_assignment(
        crew_repricing_scenario["umpire_assignment"]["id"]
    )
    referee_assignment = fx.read_assignment(
        crew_repricing_scenario["referee_assignment"]["id"]
    )
    umpire = fx.read_official(crew_repricing_scenario["umpire"]["id"])

    assert umpire_assignment["status"] == "VOIDED"
    assert referee_assignment["status"] == "COMPLETED"
    assert umpire["status"] == "SUSPENDED"
    assert umpire["open_assignment_count"] == 0

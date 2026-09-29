"""Every derived value is already correct when the request returns: the create
response carries its computed window, the confirm response carries the new posture,
and the read taken immediately after a post already shows the recomputed accuracy.
"""
import pytest

from test_helpers import fixtures as fx
from test_helpers.assertions import assert_instant_equals
from test_helpers.constants import (
    INSTANT_G1_KICKOFF,
    INSTANT_G1_OCCUPIED_FROM,
    INSTANT_G1_POSTGAME,
)


@pytest.fixture
def one_slot_game_awaiting_its_umpire():
    """A one-official program with a SCHEDULED game and Dan Ruiz cleared to work
    it."""
    program = fx.solo_program()
    official = fx.register_umpire(program["id"])
    return {
        "program": program,
        "official": official,
        "game": fx.schedule_game(program["id"]),
    }


def test_the_window_and_the_posture_are_correct_the_moment_they_are_written(
    one_slot_game_awaiting_its_umpire,
):
    """The proposal's own response already carries the computed occupancy window, and
    the read taken straight after the confirmation already shows the staffed posture,
    the incremented count and the projected index.

    PRD §2.10: "Third, **cascades run to completion within the triggering request**:
    there is no deferred settlement, no background sweep and no eventual consistency."

    Design: Corner/consistency_model/derived_values_are_visible_in_the_same_request_response
    """
    game = one_slot_game_awaiting_its_umpire["game"]

    assignment = fx.propose_assignment(
        game["id"],
        one_slot_game_awaiting_its_umpire["official"]["id"],
        "UMPIRE",
        expected_game_version=game["version"],
    )

    assert_instant_equals(
        assignment["occupied_from_utc"], INSTANT_G1_OCCUPIED_FROM, "occupied_from_utc"
    )

    confirmed = fx.confirm_assignment(assignment["id"])
    after = fx.read_game(game["id"])

    assert confirmed["status"] == "CONFIRMED"
    assert after["crew_posture"] == "STAFFED"
    assert after["confirmed_crew_count"] == 1
    assert after["crew_strength_index"] == 4.80


def test_posting_the_grade_refreshes_the_record_with_no_second_call(
    one_slot_game_awaiting_its_umpire,
):
    """A DRAFT grade prices its error points immediately yet leaves the season record
    untouched, and the read taken directly after the post already shows the play, the
    error points and the new index.

    PRD §3.6: "It then recomputes the graded official's season record with the
    provisional accuracy variant, refreshing `graded_play_count`,
    `weighted_error_points`, `accuracy_index`, `accuracy_eligible` and
    `postseason_eligible`, and bumps the grade's `version` by 1."

    Design: Corner/consistency_model/derived_values_are_visible_in_the_same_request_response
    """
    game = one_slot_game_awaiting_its_umpire["game"]
    official_id = one_slot_game_awaiting_its_umpire["official"]["id"]
    assignment = fx.propose_assignment(
        game["id"], official_id, "UMPIRE", expected_game_version=game["version"]
    )
    fx.confirm_assignment(assignment["id"])
    fx.pin_clock(INSTANT_G1_KICKOFF)
    fx.kickoff(game["id"])
    fx.pin_clock(INSTANT_G1_POSTGAME)
    fx.mark_played(game["id"])

    drafted = fx.grade_play(
        game["id"],
        official_id,
        play_ref="Q3-P22",
        call_category="HOLDING",
        grade_code="MISSED_CALL",
        impact="LOW",
    )
    while_draft = fx.season_record_for(official_id)

    assert drafted["grade_status"] == "DRAFT"
    assert drafted["error_points"] == 0.75
    assert while_draft["graded_play_count"] == 0
    assert while_draft["accuracy_index"] == 100.00

    posted = fx.post_grade(drafted["id"])
    after_post = fx.season_record_for(official_id)

    assert posted["grade_status"] == "POSTED"
    assert_instant_equals(posted["posted_at"], INSTANT_G1_POSTGAME, "posted_at")
    assert after_post["graded_play_count"] == 1
    assert after_post["weighted_error_points"] == 0.75
    assert after_post["accuracy_index"] == 85.00

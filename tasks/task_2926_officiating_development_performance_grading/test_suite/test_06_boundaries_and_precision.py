"""Boundary behaviour on three different metrics: an inclusive score threshold,
an empty collection, and an inclusive deadline measured in whole seconds.
"""
import pytest

from test_helpers import fixtures as fx
from test_helpers.assertions import assert_instant_equals
from test_helpers.constants import (
    INSTANT_G1_KICKOFF,
    INSTANT_G1_POSTGAME,
    INSTANT_G1_REPLAY_OPEN,
    INSTANT_PAST_REPLAY_WINDOW_CLOSE,
    INSTANT_REPLAY_WINDOW_CLOSE,
)


# ─── The eligibility threshold at exactly 95.00 ────────

@pytest.fixture
def umpire_and_referee_one_grade_short():
    """Both officials worked the same played game and each carries two posted
    clean calls plus one low-impact missed call still in DRAFT."""
    program = fx.solo_program()
    umpire = fx.register_umpire(program["id"])
    referee = fx.register_referee(program["id"])
    game = fx.schedule_game(program["id"])
    umpire_assignment = fx.propose_assignment(
        game["id"], umpire["id"], "UMPIRE", expected_game_version=game["version"]
    )
    referee_assignment = fx.propose_assignment(
        game["id"], referee["id"], "REFEREE"
    )
    fx.confirm_assignment(umpire_assignment["id"])
    fx.confirm_assignment(referee_assignment["id"])
    fx.pin_clock(INSTANT_G1_KICKOFF)
    fx.kickoff(game["id"])
    fx.pin_clock(INSTANT_G1_POSTGAME)
    fx.mark_played(game["id"])

    drafts = {}
    for official, play_prefix in ((umpire, "U"), (referee, "R")):
        fx.posted_grade(
            game["id"],
            official["id"],
            play_ref=f"Q1-P05-{play_prefix}",
            call_category="FALSE_START",
            grade_code="CORRECT",
            impact="LOW",
        )
        fx.posted_grade(
            game["id"],
            official["id"],
            play_ref=f"Q2-P18-{play_prefix}",
            call_category="HOLDING",
            grade_code="CORRECT",
            impact="LOW",
        )
        drafts[play_prefix] = fx.grade_play(
            game["id"],
            official["id"],
            play_ref=f"Q3-P31-{play_prefix}",
            call_category="HOLDING",
            grade_code="MISSED_CALL",
            impact="LOW",
        )
    return {
        "program": program,
        "umpire": umpire,
        "referee": referee,
        "game": game,
        "umpire_draft": drafts["U"],
        "referee_draft": drafts["R"],
    }


def test_an_index_landing_exactly_on_the_threshold_is_eligible(
    umpire_and_referee_one_grade_short,
):
    """Posting the umpire's missed call at 0.75 puts him on exactly 95.00 over
    three plays, which the inclusive comparison accepts.

    PRD §3.6: "Both comparisons are inclusive, which is why an index landing
    exactly on 95.00 under the default threshold qualifies while 94.00 does not —
    an umpire with three final plays scoring 0.00, 0.00 and 0.75 reads 100.00
    minus 5.00, exactly 95.00, and is eligible, whereas a referee with one
    low-impact missed call worth 0.90 across three plays reads 100.00 minus 6.00,
    which is 94.00, and is not."

    Design: Difficulty/boundary_precision_check/accuracy_eligibility_threshold_inclusive_at_exactly_95
    """
    posted = fx.post_grade(umpire_and_referee_one_grade_short["umpire_draft"]["id"])

    record = fx.season_record_for(umpire_and_referee_one_grade_short["umpire"]["id"])

    assert posted["error_points"] == 0.75
    assert record["accuracy_index"] == 95.00
    assert record["graded_play_count"] == 3
    assert record["accuracy_eligible"] is True


def test_an_index_one_grade_point_below_the_threshold_is_not_eligible(
    umpire_and_referee_one_grade_short,
):
    """The referee's identical call costs 0.90 rather than 0.75, which leaves him
    on 94.00 and outside eligibility.

    PRD §3.6: "`accuracy_eligible` is then true when `accuracy_index` is greater
    than or equal to the program's `accuracy_eligibility_threshold` **and**
    `graded_play_count` is greater than or equal to the program's
    `min_graded_plays_for_eligibility`."

    Design: Difficulty/boundary_precision_check/accuracy_eligibility_threshold_inclusive_at_exactly_95
    """
    posted = fx.post_grade(umpire_and_referee_one_grade_short["referee_draft"]["id"])

    record = fx.season_record_for(umpire_and_referee_one_grade_short["referee"]["id"])

    assert posted["error_points"] == 0.90
    assert record["accuracy_index"] == 94.00
    assert record["graded_play_count"] == 3
    assert record["accuracy_eligible"] is False


# ─── The empty crew ────────────────────────────────────

@pytest.fixture
def crew_being_dismantled():
    """A confirmed two-person crew whose referee has already been withdrawn."""
    ctx = fx.crew_game()
    fx.withdraw_assignment(
        ctx["referee_assignment"]["id"], "reassigned to a network game"
    )
    return ctx


def test_withdrawing_one_member_reprices_over_the_required_crew_size(
    crew_being_dismantled,
):
    """One umpire left on a crew of two scores 4.80 divided by 2, which is 2.40,
    and the posture falls to UNDERSTAFFED.

    PRD §3.4: "Withdrawing a **confirmed** assignment additionally walks the
    posture cascade backwards: the game's `confirmed_crew_count` decrements by 1,
    which re-derives `crew_posture` from `STAFFED` to `UNDERSTAFFED` as soon as the
    count falls below `crew_size_required`, and because the crew left `STAFFED` the
    projected index is recomputed over the assignments that remain in `PROPOSED`
    or `CONFIRMED`."

    Design: Difficulty/boundary_precision_check/crew_strength_index_zero_on_empty_assignment_set
    """
    game = fx.read_game(crew_being_dismantled["game"]["id"])

    assert game["confirmed_crew_count"] == 1
    assert game["crew_posture"] == "UNDERSTAFFED"
    assert game["crew_strength_index"] == 2.40


def test_withdrawing_the_last_member_yields_an_index_of_exactly_zero(
    crew_being_dismantled,
):
    """With no assignments left in the included set the index reads 0.00 rather
    than carrying the previous 2.40 forward, and neither official holds an open
    assignment.

    PRD §3.4: "An empty included set yields exactly 0.00."

    Design: Difficulty/boundary_precision_check/crew_strength_index_zero_on_empty_assignment_set
    """
    fx.withdraw_assignment(
        crew_being_dismantled["umpire_assignment"]["id"], "crew rebuild"
    )

    game = fx.read_game(crew_being_dismantled["game"]["id"])
    referee = fx.read_official(crew_being_dismantled["referee"]["id"])
    umpire = fx.read_official(crew_being_dismantled["umpire"]["id"])

    assert game["crew_strength_index"] == 0.00
    assert game["confirmed_crew_count"] == 0
    assert game["crew_posture"] == "UNDERSTAFFED"
    assert referee["open_assignment_count"] == 0
    assert umpire["open_assignment_count"] == 0


# ─── The replay decision limit ─────────────────────────

@pytest.fixture
def two_open_replay_windows():
    """Two reviews opened on the same two-window booth at 18:00:00, so both
    windows close at 18:02:00."""
    ctx = fx.in_progress_game_with_station(
        station_code="BOOTH-1", concurrent_capacity=2
    )
    fx.pin_clock(INSTANT_G1_REPLAY_OPEN)
    ctx["first_review"] = fx.open_review(
        ctx["game"]["id"],
        ctx["station"]["id"],
        play_ref="Q1-P12",
        category="SCORING_PLAY",
    )
    ctx["second_review"] = fx.open_review(
        ctx["game"]["id"],
        ctx["station"]["id"],
        play_ref="Q1-P13",
        category="TURNOVER",
    )
    return ctx


def test_a_decision_at_exactly_the_limit_still_decides(two_open_replay_windows):
    """At 18:02:00 the elapsed count is exactly 120 seconds, so the review is
    DECIDED and keeps the submitted decision.

    PRD §3.5: "With the default limit, exactly 120 elapsed seconds still decides —
    storing `elapsed_seconds` 120 — while 121 elapsed seconds expires with
    `elapsed_seconds` 121."

    Design: Difficulty/boundary_precision_check/replay_decision_limit_inclusive_at_exactly_120_seconds
    """
    assert_instant_equals(
        two_open_replay_windows["first_review"]["window_close_utc"],
        INSTANT_REPLAY_WINDOW_CLOSE,
        "window_close_utc",
    )

    fx.pin_clock(INSTANT_REPLAY_WINDOW_CLOSE)
    decided = fx.decide_review(two_open_replay_windows["first_review"]["id"], "CONFIRMED")

    assert decided["elapsed_seconds"] == 120
    assert decided["status"] == "DECIDED"
    assert decided["decision"] == "CONFIRMED"


def test_a_decision_one_second_late_expires_and_discards_it(two_open_replay_windows):
    """At 18:02:01 the elapsed count is 121, so the review expires and the
    submitted REVERSED is thrown away — still on a successful response.

    PRD §3.5: "The server measures `elapsed_seconds` as the whole seconds from the
    review's `window_open_utc` to the current logical clock, and the boundary is
    **inclusive**: when `elapsed_seconds` is less than or equal to the program's
    `replay_decision_limit_seconds` the review moves `INITIATED → DECIDED` and
    stores the supplied `decision`; when it exceeds that limit the review moves
    `INITIATED → EXPIRED`, the supplied `decision` is discarded and `decision` is
    stored as null."

    Design: Difficulty/boundary_precision_check/replay_decision_limit_inclusive_at_exactly_120_seconds
    """
    fx.pin_clock(INSTANT_PAST_REPLAY_WINDOW_CLOSE)

    expired = fx.decide_review(
        two_open_replay_windows["second_review"]["id"], "REVERSED"
    )

    assert expired["elapsed_seconds"] == 121
    assert expired["status"] == "EXPIRED"
    assert expired["decision"] is None


def test_both_settled_reviews_release_the_booths_capacity(two_open_replay_windows):
    """One decided and one expired review leave the booth holding no active
    windows.

    PRD §3.5: "Reviews that reach `DECIDED` or `EXPIRED` release their capacity
    immediately."

    Design: Difficulty/boundary_precision_check/replay_decision_limit_inclusive_at_exactly_120_seconds
    """
    fx.pin_clock(INSTANT_REPLAY_WINDOW_CLOSE)
    fx.decide_review(two_open_replay_windows["first_review"]["id"], "CONFIRMED")
    fx.pin_clock(INSTANT_PAST_REPLAY_WINDOW_CLOSE)
    fx.decide_review(two_open_replay_windows["second_review"]["id"], "REVERSED")

    station = fx.read_station(two_open_replay_windows["station"]["id"])

    assert station["active_review_count"] == 0

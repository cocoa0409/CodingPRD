"""Two resources with deliberately opposite interval conventions: an official's
half-open occupancy calendar, and a replay booth's closed windows counted in
aggregate against its capacity.
"""
import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.assertions import assert_instant_equals
from test_helpers.constants import (
    INSTANT_BOOTH_B_FIRST_OPEN,
    INSTANT_BOOTH_B_SECOND_OPEN,
    INSTANT_BOOTH_B_THIRD_OPEN,
    INSTANT_G1_OCCUPIED_FROM,
    INSTANT_G1_OCCUPIED_UNTIL,
    INSTANT_G1_REPLAY_OPEN,
    INSTANT_G2_KICKOFF,
    INSTANT_G2_KICKOFF_MINUS_1MIN,
    INSTANT_PAST_REPLAY_WINDOW_CLOSE,
    INSTANT_REPLAY_WINDOW_CLOSE,
)


# ─── The official's half-open calendar ─────────────────

@pytest.fixture
def umpire_occupied_by_one_game():
    """Dan Ruiz holds a proposed assignment on the 13 September game, which
    occupies him from 12 September 17:00 until 17 September 21:00."""
    program = fx.solo_program()
    official = fx.register_umpire(program["id"])
    game = fx.schedule_game(program["id"])
    assignment = fx.propose_assignment(
        game["id"], official["id"], "UMPIRE", expected_game_version=game["version"]
    )
    return {
        "program": program,
        "official": official,
        "game": game,
        "assignment": fx.read_assignment(assignment["id"]),
    }


def test_the_occupancy_window_runs_from_travel_lead_to_the_end_of_rest(
    umpire_occupied_by_one_game,
):
    """The stored window opens 24 hours before kickoff and closes 96 hours after
    the four-hour game.

    PRD §3.4: "`occupied_until_utc` is the game's `kickoff_utc` moved later by four
    hours of game duration and then further by the program's
    `min_rest_hours_between_games` — with the defaults, the same kickoff yields
    21:00 on 13 September plus 96 hours, which is 21:00 on 17 September."

    Design: Difficulty/resource_temporal_overlap/official_occupancy_half_open_allows_exact_adjacency
    """
    assignment = umpire_occupied_by_one_game["assignment"]

    assert_instant_equals(
        assignment["occupied_from_utc"], INSTANT_G1_OCCUPIED_FROM, "occupied_from_utc"
    )
    assert_instant_equals(
        assignment["occupied_until_utc"],
        INSTANT_G1_OCCUPIED_UNTIL,
        "occupied_until_utc",
    )


def test_a_window_opening_exactly_on_the_previous_close_is_accepted(
    umpire_occupied_by_one_game,
):
    """A game whose window opens precisely at 21:00 on 17 September is adjacent,
    not overlapping, so the assignment is written and the umpire now holds two.

    PRD §3.4: "Exact adjacency does not conflict — a second game whose
    `occupied_from_utc` lands precisely on the first window's `occupied_until_utc`
    is accepted, while a second game whose window opens even one minute before that
    instant is rejected with `ERR_OFFICIAL_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/official_occupancy_half_open_allows_exact_adjacency
    """
    official_id = umpire_occupied_by_one_game["official"]["id"]
    adjacent_game = fx.schedule_game(
        umpire_occupied_by_one_game["program"]["id"],
        home_team_code="KAN",
        away_team_code="NYJ",
        venue_market_code="KAN",
        kickoff_utc=INSTANT_G2_KICKOFF,
    )

    adjacent = fx.propose_assignment(
        adjacent_game["id"],
        official_id,
        "UMPIRE",
        expected_game_version=adjacent_game["version"],
    )
    official = fx.read_official(official_id)

    assert_instant_equals(
        adjacent["occupied_from_utc"], INSTANT_G1_OCCUPIED_UNTIL, "occupied_from_utc"
    )
    assert adjacent["status"] == "PROPOSED"
    assert official["open_assignment_count"] == 2


def test_a_window_opening_one_minute_earlier_conflicts(umpire_occupied_by_one_game):
    """Moving the same kickoff back by a minute pulls the new window's start
    strictly inside the existing one, which is refused and writes nothing.

    PRD §3.4: "Two windows conflict when the new window's start is strictly earlier
    than the existing window's end *and* the existing window's start is strictly
    earlier than the new window's end."

    Design: Difficulty/resource_temporal_overlap/official_occupancy_half_open_allows_exact_adjacency
    """
    overlapping_game = fx.schedule_game(
        umpire_occupied_by_one_game["program"]["id"],
        home_team_code="DAL",
        away_team_code="PHI",
        venue_market_code="DAL",
        kickoff_utc=INSTANT_G2_KICKOFF_MINUS_1MIN,
    )

    response = api_client.create_crew_assignment(
        f.crew_assignment_payload(
            overlapping_game["id"],
            umpire_occupied_by_one_game["official"]["id"],
            "UMPIRE",
            overlapping_game["version"],
        ),
        fx.SCHEDULER,
    )
    validate_error(response, "ERR_OFFICIAL_WINDOW_CONFLICT", 409)

    after = fx.read_game(overlapping_game["id"])
    assert after["version"] == overlapping_game["version"]


# ─── The booth's closed windows and aggregate capacity ──

@pytest.fixture
def two_booths_one_review_open():
    """A live game with a capacity-1 booth already holding a review opened at
    18:00:00, and a spare capacity-2 booth."""
    ctx = fx.in_progress_game_with_station(
        station_code="BOOTH-A", concurrent_capacity=1
    )
    ctx["booth_b"] = fx.register_station(
        station_code="BOOTH-B", concurrent_capacity=2
    )
    fx.pin_clock(INSTANT_G1_REPLAY_OPEN)
    ctx["first_review"] = fx.open_review(
        ctx["game"]["id"],
        ctx["station"]["id"],
        play_ref="Q1-P01",
        category="SCORING_PLAY",
    )
    return ctx


def test_a_window_opening_on_the_predecessors_close_instant_conflicts(
    two_booths_one_review_open,
):
    """On a capacity-1 booth a review opened at exactly 18:02:00 touches the open
    window's close instant and is refused — the opposite of the assignment rule.

    PRD §3.5: "Both endpoints are *inclusive*: two review windows conflict when the
    new window's open instant is at or before the existing window's close instant
    and the existing window's open instant is at or before the new window's close
    instant."

    Design: Difficulty/resource_temporal_overlap/replay_station_closed_interval_and_aggregate_capacity
    """
    assert_instant_equals(
        two_booths_one_review_open["first_review"]["window_close_utc"],
        INSTANT_REPLAY_WINDOW_CLOSE,
        "window_close_utc",
    )

    fx.pin_clock(INSTANT_REPLAY_WINDOW_CLOSE)
    response = api_client.create_replay_review(
        f.replay_review_payload(
            two_booths_one_review_open["game"]["id"],
            two_booths_one_review_open["station"]["id"],
            play_ref="Q1-P02",
            category="TURNOVER",
        ),
        fx.REPLAY,
    )
    validate_error(response, "ERR_REPLAY_STATION_AT_CAPACITY", 409)


def test_the_same_window_one_second_later_clears_the_booth(
    two_booths_one_review_open,
):
    """Opened at 18:02:01 the new window no longer touches the old one, so the
    capacity-1 booth accepts it.

    PRD §3.5: "Concretely, a review opened at 18:00:00 on a two-minute limit closes
    at 18:02:00; on a capacity-1 booth a second review opened at exactly 18:02:00
    touches that close instant and is refused, while the same review opened at
    18:02:01 succeeds."

    Design: Difficulty/resource_temporal_overlap/replay_station_closed_interval_and_aggregate_capacity
    """
    fx.pin_clock(INSTANT_PAST_REPLAY_WINDOW_CLOSE)

    accepted = fx.open_review(
        two_booths_one_review_open["game"]["id"],
        two_booths_one_review_open["station"]["id"],
        play_ref="Q1-P03",
        category="TURNOVER",
    )

    assert accepted["status"] == "INITIATED"
    assert_instant_equals(
        accepted["window_open_utc"],
        INSTANT_PAST_REPLAY_WINDOW_CLOSE,
        "window_open_utc",
    )


def test_the_two_window_booth_admits_the_second_overlap_and_refuses_the_third(
    two_booths_one_review_open,
):
    """Capacity is an aggregate count, so the second overlapping review is
    accepted and only the third — overlapping both predecessors — is refused,
    leaving that booth holding two active windows.

    PRD §3.5: "This is an aggregate capacity test, not pairwise exclusion: on a
    booth with a capacity of 2, a second overlapping review is accepted because the
    overlapping count of 1 is below 2, and only a third is refused."

    Design: Difficulty/resource_temporal_overlap/replay_station_closed_interval_and_aggregate_capacity
    """
    game_id = two_booths_one_review_open["game"]["id"]
    booth_b_id = two_booths_one_review_open["booth_b"]["id"]

    fx.pin_clock(INSTANT_BOOTH_B_FIRST_OPEN)
    fx.open_review(game_id, booth_b_id, play_ref="Q2-P01", category="SCORING_PLAY")
    fx.pin_clock(INSTANT_BOOTH_B_SECOND_OPEN)
    second = fx.open_review(
        game_id, booth_b_id, play_ref="Q2-P02", category="PLAYER_SAFETY"
    )
    fx.pin_clock(INSTANT_BOOTH_B_THIRD_OPEN)
    response = api_client.create_replay_review(
        f.replay_review_payload(
            game_id, booth_b_id, play_ref="Q2-P03", category="TURNOVER"
        ),
        fx.REPLAY,
    )
    validate_error(response, "ERR_REPLAY_STATION_AT_CAPACITY", 409)

    booth_b = fx.read_station(booth_b_id)

    assert second["status"] == "INITIATED"
    assert booth_b["active_review_count"] == 2

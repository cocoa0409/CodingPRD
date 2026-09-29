"""The endpoint surface itself: the logical clock behind every stamp, a computed
read that must agree with the arithmetic, the flat filtered lists that stand in for
navigation, and the one sub-resource scoped to its parent.
"""
import pytest
from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.assertions import assert_instant_equals
from test_helpers.constants import (
    CLOCK_START,
    INSTANT_G1_KICKOFF,
    INSTANT_G2_KICKOFF,
    INSTANT_MIDSEASON_CLOCK_SET,
)
from test_helpers.test_users import make_official_headers


# ─── The clock behind every timestamp ──────────────────

def test_the_first_write_is_stamped_from_the_default_logical_clock():
    """On an untouched server the program is created and opened at the declared
    default instant, not at wall-clock time.

    PRD §2.4: "At server startup the logical clock reads exactly
    `2026-08-01T00:00:00.000Z`; it must never fall back to real wall-clock time, not
    even before the clock has been set for the first time."

    Design: Corner/endpoints/logical_clock_defaults_to_2026_08_01_and_then_follows_the_setter
    """
    rows, meta = validate_paginated(api_client.list_officials(fx.DIRECTOR))

    assert rows == []
    assert meta["total_count"] == 0

    program = validate_success(
        api_client.create_season_program(f.season_program_payload(), fx.DIRECTOR), 201
    )
    opened = fx.open_program(program["id"])

    assert_instant_equals(program["created_at"], CLOCK_START, "created_at")
    assert opened["status"] == "OPEN"
    assert_instant_equals(opened["updated_at"], CLOCK_START, "updated_at")


def test_every_stamp_after_the_setter_reads_the_supplied_instant():
    """The setter is a shared operation any declared role may call, and the official
    registered after it carries the new instant as its `created_at`.

    PRD §2.4: "An administrative test-driving capability, available to all eight
    roles, sets the logical clock to a supplied UTC instant carried in a
    `current_utc` field."

    Design: Corner/endpoints/logical_clock_defaults_to_2026_08_01_and_then_follows_the_setter
    """
    program = fx.create_program()
    fx.open_program(program["id"])

    fx.pin_clock(INSTANT_MIDSEASON_CLOCK_SET, fx.TRAINING)
    official = fx.register_official(
        program["id"],
        full_name="Clock Witness",
        position="UMPIRE",
        seasons_experience=4,
        home_market_code="PHI",
    )

    assert_instant_equals(
        official["created_at"], INSTANT_MIDSEASON_CLOCK_SET, "created_at"
    )
    assert_instant_equals(
        fx.read_program(program["id"])["created_at"], CLOCK_START, "created_at"
    )


# ─── A computed read must match the arithmetic ─────────

@pytest.fixture
def one_posted_missed_call_on_dan():
    """A one-official program whose played game carries Dan's single POSTED
    MISSED_CALL at LOW impact, worth 0.75 error points."""
    return fx.posted_grade_for_appeal()


def test_the_filtered_list_carries_the_posted_grade_arithmetic(
    one_posted_missed_call_on_dan,
):
    """Read by the official himself, the season record shows one play, 0.75 weighted
    error points and an index of 85.00, and neither eligibility leg holds.

    PRD §3.6: "Otherwise the index is 100.00 minus the quantity obtained by dividing
    `weighted_error_points` by `graded_play_count` and multiplying the quotient by an
    error scale of 20.00, with the final result rounded half up to two decimal
    places."

    Design: Corner/endpoints/season_record_read_matches_the_posted_grade_arithmetic
    """
    official_id = one_posted_missed_call_on_dan["official"]["id"]
    program_id = one_posted_missed_call_on_dan["program"]["id"]

    rows, meta = validate_paginated(
        api_client.list_season_records(
            make_official_headers(official_id),
            {"official_id": official_id, "season_program_id": program_id},
        )
    )

    assert meta["total_count"] == 1
    assert rows[0]["weighted_error_points"] == 0.75
    assert rows[0]["graded_play_count"] == 1
    assert rows[0]["accuracy_index"] == 85.00
    assert rows[0]["accuracy_variant"] == "PROVISIONAL"
    assert rows[0]["accuracy_eligible"] is False


def test_the_single_read_is_the_same_row_and_no_record_is_eligible(
    one_posted_missed_call_on_dan,
):
    """The addressed read returns the identical numbers and links back to the same
    official and program, and filtering on eligibility yields nothing.

    PRD §3.6: "Season records are readable individually and listable with filters on
    `official_id`, `season_program_id`, `accuracy_variant`, `accuracy_eligible`,
    `postseason_eligible` and `retention_recommendation`."

    Design: Corner/endpoints/season_record_read_matches_the_posted_grade_arithmetic
    """
    official_id = one_posted_missed_call_on_dan["official"]["id"]
    program_id = one_posted_missed_call_on_dan["program"]["id"]
    listed = fx.season_record_for(official_id)

    one = validate_success(
        api_client.get_season_record(listed["id"], fx.GRADER), 200
    )

    assert one["accuracy_index"] == listed["accuracy_index"]
    assert one["weighted_error_points"] == listed["weighted_error_points"]
    assert one["graded_play_count"] == listed["graded_play_count"]
    assert one["official_id"] == official_id
    assert one["season_program_id"] == program_id

    rows, meta = validate_paginated(
        api_client.list_season_records(fx.DIRECTOR, {"accuracy_eligible": "true"})
    )

    assert rows == []
    assert meta["total_count"] == 0


# ─── The flat list is the only navigation ──────────────

@pytest.fixture
def two_games_sharing_one_official():
    """G1 (MIA vs BUF) holds Dan CONFIRMED as umpire and Rita PROPOSED as referee;
    G2 (BUF vs DEN) holds Dan PROPOSED as umpire, its window opening exactly where
    his G1 window closes."""
    program = fx.crew_program()
    dan = fx.register_umpire(program["id"])
    rita = fx.register_referee(program["id"])
    game_one = fx.schedule_game(
        program["id"],
        home_team_code="MIA",
        away_team_code="BUF",
        venue_market_code="MIA",
        kickoff_utc=INSTANT_G1_KICKOFF,
    )
    game_two = fx.schedule_game(
        program["id"],
        home_team_code="BUF",
        away_team_code="DEN",
        venue_market_code="BUF",
        kickoff_utc=INSTANT_G2_KICKOFF,
    )
    dan_on_one = fx.propose_assignment(
        game_one["id"], dan["id"], "UMPIRE", expected_game_version=game_one["version"]
    )
    fx.confirm_assignment(dan_on_one["id"])
    rita_on_one = fx.propose_assignment(game_one["id"], rita["id"], "REFEREE")
    dan_on_two = fx.propose_assignment(
        game_two["id"], dan["id"], "UMPIRE", expected_game_version=game_two["version"]
    )
    return {
        "program": program,
        "dan": dan,
        "rita": rita,
        "game_one": game_one,
        "game_two": game_two,
        "dan_on_one": dan_on_one,
        "rita_on_one": rita_on_one,
        "dan_on_two": dan_on_two,
    }


def test_both_sides_of_the_relationship_are_reached_by_the_same_list(
    two_games_sharing_one_official,
):
    """Filtering by game gives that game's two crew rows in creation order, and
    filtering by official gives his two games — the same rows read from the other
    side.

    PRD §3.4: "Assignments are readable individually — including their computed
    `occupied_from_utc` and `occupied_until_utc` — and listable with filters on
    `game_id`, `official_id`, `status` and `position`, which is the only way to
    discover an assignment that a cascade voided or superseded behind the scheduler's
    back."

    Design: Corner/endpoints/crew_assignment_filters_are_the_flat_reverse_lookups
    """
    by_game, game_meta = validate_paginated(
        api_client.list_crew_assignments(
            fx.DIRECTOR, {"game_id": two_games_sharing_one_official["game_one"]["id"]}
        )
    )
    by_official, official_meta = validate_paginated(
        api_client.list_crew_assignments(
            fx.DIRECTOR, {"official_id": two_games_sharing_one_official["dan"]["id"]}
        )
    )

    assert game_meta["total_count"] == 2
    assert by_game[0]["id"] == two_games_sharing_one_official["dan_on_one"]["id"]
    assert by_game[0]["position"] == "UMPIRE"
    assert by_game[1]["id"] == two_games_sharing_one_official["rita_on_one"]["id"]
    assert by_game[1]["position"] == "REFEREE"

    assert official_meta["total_count"] == 2
    assert by_official[0]["game_id"] == two_games_sharing_one_official["game_one"]["id"]
    assert by_official[1]["game_id"] == two_games_sharing_one_official["game_two"]["id"]


def test_status_and_position_each_narrow_the_same_underlying_set(
    two_games_sharing_one_official,
):
    """Composed with the game filter, `status` isolates the confirmed umpire and
    `position` isolates the proposed referee.

    PRD §2.3: "List results are ordered by `created_at` ascending unless a specific
    workflow below states otherwise."

    Design: Corner/endpoints/crew_assignment_filters_are_the_flat_reverse_lookups
    """
    game_id = two_games_sharing_one_official["game_one"]["id"]

    confirmed, confirmed_meta = validate_paginated(
        api_client.list_crew_assignments(
            fx.DIRECTOR, {"game_id": game_id, "status": "CONFIRMED"}
        )
    )
    referees, referee_meta = validate_paginated(
        api_client.list_crew_assignments(
            fx.DIRECTOR, {"game_id": game_id, "position": "REFEREE"}
        )
    )

    assert confirmed_meta["total_count"] == 1
    assert confirmed[0]["id"] == two_games_sharing_one_official["dan_on_one"]["id"]
    assert confirmed[0]["official_id"] == two_games_sharing_one_official["dan"]["id"]

    assert referee_meta["total_count"] == 1
    assert referees[0]["id"] == two_games_sharing_one_official["rita_on_one"]["id"]
    assert referees[0]["status"] == "PROPOSED"


# ─── The evidence log beneath its owner ────────────────

@pytest.fixture
def two_officials_with_training_histories():
    """Dan holds a passed rules exam and a passed physical test; Tom Wells holds only
    a passed rules exam."""
    program = fx.create_open_program()
    dan = fx.register_official(program["id"])
    tom = fx.register_official(
        program["id"],
        full_name="Tom Wells",
        position="REFEREE",
        seasons_experience=11,
        home_market_code="SEA",
    )
    dan_exam = fx.add_training_record(dan["id"], f.rules_exam_payload(84.00, "EX-D1"))
    dan_physical = fx.add_training_record(
        dan["id"], f.physical_test_payload(79.00, "PT-D1")
    )
    tom_exam = fx.add_training_record(tom["id"], f.rules_exam_payload(90.00, "EX-T1"))
    return {
        "program": program,
        "dan": dan,
        "tom": tom,
        "dan_exam": dan_exam,
        "dan_physical": dan_physical,
        "tom_exam": tom_exam,
    }


def test_each_parents_list_holds_only_its_own_records(
    two_officials_with_training_histories,
):
    """Dan's two records come back in creation order carrying the `official_id` the
    path supplied, and Tom's list holds his single exam and nothing of Dan's.

    PRD §2.11: "Only the two append-only evidence logs are exposed as sub-resources
    beneath their owner, because each is owned by exactly one parent: field
    evaluation reports live beneath their advancement application, and training
    records live beneath their official."

    Design: Corner/endpoints/training_records_subresource_is_scoped_to_its_parent_official
    """
    dan_rows, dan_meta = validate_paginated(
        api_client.list_training_records(
            two_officials_with_training_histories["dan"]["id"], fx.TRAINING
        )
    )
    tom_rows, tom_meta = validate_paginated(
        api_client.list_training_records(
            two_officials_with_training_histories["tom"]["id"], fx.DIRECTOR
        )
    )

    assert dan_meta["total_count"] == 2
    assert dan_rows[0]["record_type"] == "RULES_EXAM"
    assert dan_rows[0]["official_id"] == two_officials_with_training_histories["dan"]["id"]
    assert dan_rows[1]["record_type"] == "PHYSICAL_TEST"
    assert dan_rows[1]["score"] == 79.00

    assert tom_meta["total_count"] == 1
    assert tom_rows[0]["id"] == two_officials_with_training_histories["tom_exam"]["id"]
    assert tom_rows[0]["official_id"] == two_officials_with_training_histories["tom"]["id"]
    assert tom_rows[0]["record_type"] == "RULES_EXAM"
    assert tom_rows[0]["id"] != two_officials_with_training_histories["dan_exam"]["id"]


def test_the_record_type_filter_narrows_each_parents_list(
    two_officials_with_training_histories,
):
    """The physical test is the only row Dan's filtered list returns, and the clinic
    neither official attended returns an empty page.

    PRD §3.2: "An official's training history is readable only by listing that
    official's training records, optionally filtered by `record_type` or by
    `passed`."

    Design: Corner/endpoints/training_records_subresource_is_scoped_to_its_parent_official
    """
    physicals, physical_meta = validate_paginated(
        api_client.list_training_records(
            two_officials_with_training_histories["dan"]["id"],
            fx.DIRECTOR,
            {"record_type": "PHYSICAL_TEST"},
        )
    )
    clinics, clinic_meta = validate_paginated(
        api_client.list_training_records(
            two_officials_with_training_histories["tom"]["id"],
            fx.DIRECTOR,
            {"record_type": "RULES_CLINIC"},
        )
    )

    assert physical_meta["total_count"] == 1
    assert physicals[0]["id"] == two_officials_with_training_histories["dan_physical"]["id"]
    assert physicals[0]["passed"] is True

    assert clinics == []
    assert clinic_meta["total_count"] == 0

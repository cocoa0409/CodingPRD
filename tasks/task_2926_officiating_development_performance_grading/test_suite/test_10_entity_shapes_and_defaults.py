"""Row shapes as they come out of the create calls: declared defaults, seeded
counters, server-derived fields, append-only evidence logs, and the shape and
identifier failures that write nothing at all.
"""
import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.assertions import (
    assert_append_only_fields,
    assert_instant_equals,
    assert_list_meta,
    assert_official,
    assert_season_program,
)
from test_helpers.constants import (
    INSTANT_SEASON_START,
    PROGRAM_DEFAULTS,
    UNKNOWN_ID,
)
from test_helpers.test_users import GRADER_USER_ID


# ─── The season program's declared defaults ────────────

@pytest.fixture
def program_created_with_only_a_season_year():
    """The create call carries nothing but `season_year`, so every threshold
    falls back to its league-standard default."""
    fx.pin_clock(INSTANT_SEASON_START)
    response = api_client.create_season_program({"season_year": 2026}, fx.DIRECTOR)
    return validate_success(response, 201)


def test_a_program_created_with_only_a_season_year_carries_every_default(
    program_created_with_only_a_season_year,
):
    """All fourteen thresholds come back at their documented values, and
    GAME_ADMIN is a declared category that the default review set leaves out.

    PRD §3.1: "Creation is the department's single opportunity to tune the season,
    because every threshold below is an optional input on the create call and each
    has a league-standard default that applies when the field is omitted."

    Design: Corner/entities/season_program_creation_returns_declared_defaults
    """
    program = program_created_with_only_a_season_year

    for field, expected in PROGRAM_DEFAULTS.items():
        assert program[field] == expected, (
            f"{field} must default to {expected!r}, got {program[field]!r}"
        )
    assert "GAME_ADMIN" not in program["reviewable_categories"]


def test_the_new_program_is_configuring_with_no_eligible_officials_yet(
    program_created_with_only_a_season_year,
):
    """It is born private, counting no eligible officials, and stamped with the
    logical clock rather than wall-clock time.

    PRD §3.1: "The program is born with `status` equal to `CONFIGURING` and
    `eligible_official_count` at 0, and it stays private to the department until the
    director opens it."

    Design: Corner/entities/season_program_creation_returns_declared_defaults
    """
    program = program_created_with_only_a_season_year

    assert_season_program(program)
    assert program["status"] == "CONFIGURING"
    assert program["eligible_official_count"] == 0
    assert program["version"] == 1
    assert_instant_equals(program["created_at"], INSTANT_SEASON_START, "created_at")


# ─── The official's defaults and seeded quota ──────────

@pytest.fixture
def official_registered_with_only_required_fields():
    """Dan Ruiz registered into an open program with no `tier` and no
    `affiliated_team_code` supplied."""
    program = fx.create_open_program()
    response = api_client.create_official(
        f.official_payload(program["id"]), fx.DIRECTOR
    )
    return {"program": program, "official": validate_success(response, 201)}


def test_a_new_official_enters_as_a_candidate_holding_the_seasons_appeal_quota(
    official_registered_with_only_required_fields,
):
    """Status, clearance and the assignment counter all start where the PRD says,
    and the appeal ledger is seeded from the program's quota of three.

    PRD §3.2: "A newly registered official enters at `status` `CANDIDATE`, with
    `preseason_cleared` false and `open_assignment_count` at 0, and with
    `appeal_credits_remaining` seeded from the program's
    `appeal_credits_per_official`."

    Design: Corner/entities/official_creation_applies_tier_default_and_seeds_appeal_credits
    """
    official = official_registered_with_only_required_fields["official"]

    assert_official(official)
    assert official["status"] == "CANDIDATE"
    assert official["preseason_cleared"] is False
    assert official["open_assignment_count"] == 0
    assert official["appeal_credits_remaining"] == PROGRAM_DEFAULTS[
        "appeal_credits_per_official"
    ]
    assert_instant_equals(official["created_at"], INSTANT_SEASON_START, "created_at")


def test_the_optional_tier_and_conflict_code_take_their_declared_defaults(
    official_registered_with_only_required_fields,
):
    """He enters the pipeline at TIER_3 with no declared conflict of interest, and
    the read-back agrees with the create response field for field.

    PRD §3.2: "`tier` is the official's pipeline level, one of `TIER_3`, `TIER_2` or
    `TIER_1`, defaulting to `TIER_3` for a new recruit from the lower levels."

    PRD §3.2: "`affiliated_team_code` declares the team the official has a conflict
    of interest with, either null — the default — or exactly three uppercase
    letters."

    Design: Corner/entities/official_creation_applies_tier_default_and_seeds_appeal_credits
    """
    created = official_registered_with_only_required_fields["official"]

    read_back = fx.read_official(created["id"])

    assert created["tier"] == "TIER_3"
    assert created["affiliated_team_code"] is None
    assert read_back["tier"] == created["tier"]
    assert read_back["status"] == created["status"]
    assert read_back["full_name"] == "Dan Ruiz"


# ─── Paging the officials collection ──────────────────

@pytest.fixture
def three_registered_officials():
    """One open program carrying exactly three officials."""
    program = fx.create_open_program()
    dan = fx.register_official(
        program["id"], full_name="Dan Ruiz", position="UMPIRE", seasons_experience=6
    )
    rita = fx.register_official(
        program["id"],
        full_name="Rita Vance",
        position="REFEREE",
        seasons_experience=14,
        home_market_code="BUF",
    )
    kim = fx.register_official(
        program["id"],
        full_name="Kim Ortega",
        position="DOWN_JUDGE",
        seasons_experience=9,
        home_market_code="DEN",
    )
    return {"program": program, "ids": [dan["id"], rita["id"], kim["id"]]}


def test_the_first_page_reports_the_unpaginated_total_and_more_to_come(
    three_registered_officials,
):
    """A limit of two returns two rows while `total_count` still counts all three
    matching officials and `has_more` is true.

    PRD §2.3: "For list responses, the `meta` object carries `limit` and `offset` as
    applied, `total_count` as the number of records matching the filter before
    pagination, and `has_more` as a boolean that is true when records matching the
    filter remain beyond the current page."

    Design: Corner/entities/officials_list_paginates_with_total_count_and_has_more
    """
    response = api_client.list_officials(
        fx.DIRECTOR,
        {
            "season_program_id": three_registered_officials["program"]["id"],
            "limit": 2,
            "offset": 0,
        },
    )
    rows, meta = validate_paginated(response)

    assert len(rows) == 2
    assert_list_meta(
        meta,
        expected_total=3,
        expected_limit=2,
        expected_offset=0,
        expected_has_more=True,
    )


def test_the_offset_page_returns_the_remainder_without_repeating_a_row(
    three_registered_officials,
):
    """Skipping the first two rows yields the third and only the third, so the two
    pages together cover every official exactly once.

    PRD §2.3: "`offset` controls how many matching records are skipped before the
    page begins: it defaults to 0 and may not be negative."

    Design: Corner/entities/officials_list_paginates_with_total_count_and_has_more
    """
    params = {
        "season_program_id": three_registered_officials["program"]["id"],
        "limit": 2,
    }
    first_rows, _ = validate_paginated(
        api_client.list_officials(fx.DIRECTOR, dict(params, offset=0))
    )
    second_rows, second_meta = validate_paginated(
        api_client.list_officials(fx.DIRECTOR, dict(params, offset=2))
    )

    assert len(second_rows) == 1
    assert_list_meta(second_meta, expected_total=3, expected_has_more=False)
    page_ids = [row["id"] for row in first_rows] + [row["id"] for row in second_rows]
    assert sorted(page_ids) == sorted(three_registered_officials["ids"])
    assert len(set(page_ids)) == 3


# ─── Reads and writes that resolve nothing ─────────────

def test_reading_a_game_that_no_row_holds_is_a_not_found_error():
    """The unknown identifier produces the game-specific 404 in the error
    envelope, not an empty success.

    PRD §2.9: "The first unresolved identifier determines which of the not-found
    errors is returned (`ERR_SEASON_PROGRAM_NOT_FOUND`, `ERR_OFFICIAL_NOT_FOUND`,
    `ERR_APPLICATION_NOT_FOUND`, `ERR_GAME_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
    `ERR_PLAY_GRADE_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`,
    `ERR_REPLAY_STATION_NOT_FOUND`, `ERR_REPLAY_REVIEW_NOT_FOUND`,
    `ERR_POOL_REPORT_NOT_FOUND`, `ERR_DISCIPLINE_ACTION_NOT_FOUND`), all at HTTP
    404."

    Design: Corner/entities/game_get_with_unknown_id_returns_not_found
    """
    program = fx.create_open_program()

    response = api_client.get_game(UNKNOWN_ID, fx.DIRECTOR)
    error = validate_error(response, "ERR_GAME_NOT_FOUND", 404)

    assert error["message"].strip()
    _, meta = validate_paginated(
        api_client.list_games(fx.DIRECTOR, {"season_program_id": program["id"]})
    )
    assert_list_meta(meta, expected_total=0)


def test_scheduling_a_game_without_a_kickoff_instant_is_malformed():
    """`kickoff_utc` is a required input with no default, so its absence is a shape
    failure and no game is written.

    PRD §2.9: "The request body is well-formed: every required input field is
    present, no unknown field is honored, every enum-valued field carries a declared
    value, every score lies within the inclusive range 0.00 through 100.00, every
    timestamp parses as an ISO 8601 UTC instant, integers are non-negative, and a
    `MODIFIED` appeal decision carries a `revised_grade_code` that differs from the
    grade's current `grade_code`."

    Design: Corner/entities/game_creation_missing_kickoff_returns_invalid_request
    """
    program = fx.create_open_program()

    response = api_client.create_game(
        {
            "season_program_id": program["id"],
            "home_team_code": "MIA",
            "away_team_code": "BUF",
            "venue_market_code": "MIA",
        },
        fx.DIRECTOR,
    )
    validate_error(response, "ERR_INVALID_REQUEST", 400)

    _, meta = validate_paginated(
        api_client.list_games(fx.DIRECTOR, {"season_program_id": program["id"]})
    )
    assert_list_meta(meta, expected_total=0)


def test_a_game_cannot_name_the_same_team_on_both_sides():
    """Naming MIA as both home and away side breaks the cross-field rule, which is
    a 400 rather than a state or lookup failure.

    PRD §3.4: "An `OfficiatingDirector` schedules each **game** under an open season
    program, supplying the `season_program_id`, a `home_team_code` and an
    `away_team_code` — each exactly three uppercase letters, and the two must
    differ, since a request naming the same code twice is rejected with
    `ERR_INVALID_REQUEST` — a `venue_market_code` of exactly three uppercase letters
    naming the market the game is played in, and a `kickoff_utc` instant."

    Design: Corner/entities/game_creation_with_identical_team_codes_rejected
    """
    program = fx.create_open_program()

    response = api_client.create_game(
        f.game_payload(
            program["id"],
            home_team_code="MIA",
            away_team_code="MIA",
            venue_market_code="MIA",
        ),
        fx.DIRECTOR,
    )
    validate_error(response, "ERR_INVALID_REQUEST", 400)

    _, meta = validate_paginated(
        api_client.list_games(fx.DIRECTOR, {"season_program_id": program["id"]})
    )
    assert_list_meta(meta, expected_total=0)


def test_values_outside_a_declared_enum_are_refused_on_shape():
    """A position of LINE_JUDGE and a review category of PENALTY_ENFORCEMENT are
    both outside their declared enums, so both calls are malformed and neither row
    is written.

    PRD §2.9: "The request body is well-formed: every required input field is
    present, no unknown field is honored, every enum-valued field carries a declared
    value, every score lies within the inclusive range 0.00 through 100.00, every
    timestamp parses as an ISO 8601 UTC instant, integers are non-negative, and a
    `MODIFIED` appeal decision carries a `revised_grade_code` that differs from the
    grade's current `grade_code`."

    Design: Corner/entities/undeclared_enum_values_are_rejected_before_business_rules
    """
    program = fx.create_open_program()
    game = fx.schedule_game(program["id"])
    station = fx.register_station(station_code="BOOTH-1", concurrent_capacity=2)

    position_response = api_client.create_official(
        f.official_payload(
            program["id"],
            full_name="Val Reyes",
            position="LINE_JUDGE",
            seasons_experience=4,
            home_market_code="DEN",
        ),
        fx.DIRECTOR,
    )
    category_response = api_client.create_replay_review(
        f.replay_review_payload(
            game["id"], station["id"], play_ref="Q1-P01", category="PENALTY_ENFORCEMENT"
        ),
        fx.REPLAY,
    )
    validate_error(position_response, "ERR_INVALID_REQUEST", 400)
    validate_error(category_response, "ERR_INVALID_REQUEST", 400)

    _, official_meta = validate_paginated(
        api_client.list_officials(fx.DIRECTOR, {"season_program_id": program["id"]})
    )
    _, review_meta = validate_paginated(
        api_client.list_replay_reviews(fx.REPLAY, {"game_id": game["id"]})
    )
    assert_list_meta(official_meta, expected_total=0)
    assert_list_meta(review_meta, expected_total=0)


# ─── A draft grade's computed fields ──────────────────

@pytest.fixture
def draft_grade_on_a_high_impact_miss():
    """One DRAFT grade of a high-impact missed call by an umpire on a played
    game."""
    ctx = fx.played_solo_game()
    ctx["grade"] = fx.grade_play(
        ctx["game"]["id"],
        ctx["official"]["id"],
        play_ref="Q4-P11",
        call_category="PASS_INTERFERENCE",
        grade_code="MISSED_CALL",
        impact="HIGH",
    )
    return ctx


def test_error_points_and_the_author_are_stamped_when_the_play_is_written(
    draft_grade_on_a_high_impact_miss,
):
    """1.50 times 1.75 times 1.00 rounds to 2.63 on the create call itself, the
    authoring supervisor's identifier is recorded, and posting has not happened.

    PRD §3.6: "A new grade records `graded_by_user_id` from the authoring
    supervisor's `X-User-ID`, and is written with `grade_status` `DRAFT`,
    `appeal_state` `NOT_APPEALED` and a null `posted_at`."

    Design: Corner/entities/play_grade_error_points_is_computed_at_creation
    """
    grade = draft_grade_on_a_high_impact_miss["grade"]

    assert grade["error_points"] == 2.63
    assert grade["grade_status"] == "DRAFT"
    assert grade["appeal_state"] == "NOT_APPEALED"
    assert grade["posted_at"] is None
    assert grade["graded_by_user_id"] == GRADER_USER_ID


def test_a_draft_grade_is_outside_the_officials_season_aggregate(
    draft_grade_on_a_high_impact_miss,
):
    """The provisional included set takes posted and final grades only, so the
    season record still reads zero plays and an untouched 100.00.

    PRD §3.6: "The `PROVISIONAL` variant is used by every in-season recompute —
    posting a grade, deciding an appeal, finalizing a game — and includes every
    grade whose `grade_status` is `POSTED` or `FINAL`, using each grade's current
    `grade_code` whatever an appeal did to it."

    Design: Corner/entities/play_grade_error_points_is_computed_at_creation
    """
    record = fx.season_record_for(draft_grade_on_a_high_impact_miss["official"]["id"])

    assert record["graded_play_count"] == 0
    assert record["weighted_error_points"] == 0.00
    assert record["accuracy_index"] == 100.00


# ─── The append-only training log ─────────────────────

@pytest.fixture
def two_training_records_on_a_candidate():
    """A clinic attendance and a failed physical test filed against Dan Ruiz while
    he is still a CANDIDATE."""
    program = fx.create_open_program()
    official = fx.register_umpire(program["id"], cleared=False)
    clinic = fx.add_training_record(
        official["id"], f.rules_clinic_payload("CL-SPRING")
    )
    failed_physical = fx.add_training_record(
        official["id"], f.physical_test_payload(65.00, "PT-FAIL")
    )
    return {
        "program": program,
        "official": official,
        "clinic": clinic,
        "failed_physical": failed_physical,
    }


def test_a_training_record_carries_only_an_id_and_a_created_at(
    two_training_records_on_a_candidate,
):
    """Both rows are evidence, not state: they have no `version` and no
    `updated_at` to amend, and their `created_at` is the logical clock.

    PRD §2.6: "Two resources are append-only evidence logs and are never mutated
    after they are written: a **field evaluation report** filed against an
    advancement application, and a **training record** filed against an official."

    Design: Corner/entities/training_record_is_immutable_with_server_generated_fields
    """
    for label in ("clinic", "failed_physical"):
        record = two_training_records_on_a_candidate[label]
        assert_append_only_fields(record, f"training record ({label})")
        assert_instant_equals(record["created_at"], INSTANT_SEASON_START, "created_at")


def test_the_passed_flag_is_derived_and_neither_record_clears_the_official(
    two_training_records_on_a_candidate,
):
    """The clinic passes with no score at all, the 65.00 physical fails against the
    70.00 minimum, and the official stays an un-cleared CANDIDATE.

    PRD §3.2: "A `RULES_CLINIC` record ignores `score` entirely and always stores
    `passed` true — attendance is the whole point."

    PRD §3.2: "A `PHYSICAL_TEST` record passes when its `score` is greater than or
    equal to the program's `physical_test_min_score`, and a `RULES_EXAM` record
    passes when its `score` is greater than or equal to the program's
    `exam_min_score`; in both cases a score sitting exactly on the minimum passes."

    Design: Corner/entities/training_record_is_immutable_with_server_generated_fields
    """
    clinic = two_training_records_on_a_candidate["clinic"]
    failed_physical = two_training_records_on_a_candidate["failed_physical"]

    official = fx.read_official(two_training_records_on_a_candidate["official"]["id"])

    assert clinic["passed"] is True
    assert clinic["score"] is None
    assert failed_physical["passed"] is False
    assert official["status"] == "CANDIDATE"
    assert official["preseason_cleared"] is False


# ─── A foreign key that resolves to nothing ───────────

def test_proposing_an_unknown_official_is_a_not_found_before_any_crew_rule():
    """The body identifier is resolved before clearance, occupancy or the pinned
    version, and the rejected create bumps nothing on the game.

    PRD §2.9: "Every identifier resolves to a live row — path identifiers first, in
    left-to-right path order, then body identifiers in the order the endpoint
    declares its inputs."

    Design: Corner/entities/crew_assignment_with_unknown_official_id_returns_not_found
    """
    program = fx.create_open_program()
    game = fx.schedule_game(program["id"])

    response = api_client.create_crew_assignment(
        f.crew_assignment_payload(
            game["id"], UNKNOWN_ID, "UMPIRE", game["version"]
        ),
        fx.SCHEDULER,
    )
    validate_error(response, "ERR_OFFICIAL_NOT_FOUND", 404)

    after = fx.read_game(game["id"])
    _, meta = validate_paginated(
        api_client.list_crew_assignments(fx.SCHEDULER, {"game_id": game["id"]})
    )

    assert after["version"] == game["version"]
    assert after["confirmed_crew_count"] == 0
    assert_list_meta(meta, expected_total=0)

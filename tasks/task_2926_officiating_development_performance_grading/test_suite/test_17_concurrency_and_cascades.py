"""The layers that cut across every workflow: the two version-pinned creates, the
season quota that counts prior work, and the single call that closes the season and
settles every retention number behind it.
"""
import pytest
from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.assertions import assert_instant_equals
from test_helpers.constants import (
    INSTANT_G1_KICKOFF,
    INSTANT_G1_OCCUPIED_UNTIL,
    INSTANT_G2_KICKOFF,
    INSTANT_G2_OCCUPIED_FROM,
    INSTANT_G2_OCCUPIED_UNTIL,
    INSTANT_G3_KICKOFF,
)


# ─── The game version a proposal must pin ──────────────

@pytest.fixture
def game_whose_version_one_proposal_has_already_moved():
    """A two-slot game holding Dan's UMPIRE proposal, with the version the game
    carried before that proposal remembered."""
    program = fx.crew_program()
    umpire = fx.register_umpire(program["id"])
    referee = fx.register_referee(program["id"])
    game = fx.schedule_game(program["id"])
    fx.propose_assignment(
        game["id"], umpire["id"], "UMPIRE", expected_game_version=game["version"]
    )
    return {
        "program": program,
        "umpire": umpire,
        "referee": referee,
        "game": game,
        "stale_version": game["version"],
    }


def test_replaying_the_stale_game_version_is_refused_without_side_effects(
    game_whose_version_one_proposal_has_already_moved,
):
    """The referee's proposal pinned to the pre-proposal version is refused, and the
    rejection neither bumps the version a second time nor changes the projected
    index.

    PRD §2.8: "If `expected_game_version` does not equal the game's current `version`,
    the request is rejected with `ERR_STALE_GAME_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/stale_expected_game_version_on_assignment_create_returns_412
    """
    game = game_whose_version_one_proposal_has_already_moved["game"]
    stale_version = game_whose_version_one_proposal_has_already_moved["stale_version"]

    validate_error(
        api_client.create_crew_assignment(
            f.crew_assignment_payload(
                game["id"],
                game_whose_version_one_proposal_has_already_moved["referee"]["id"],
                "REFEREE",
                stale_version,
            ),
            fx.SCHEDULER,
        ),
        "ERR_STALE_GAME_VERSION",
        412,
    )

    after = fx.read_game(game["id"])

    assert after["version"] == stale_version + 1
    assert after["crew_strength_index"] == 2.40


def test_the_retry_with_the_re_read_version_succeeds_and_reprices_the_crew(
    game_whose_version_one_proposal_has_already_moved,
):
    """Re-reading the game and pinning the fresh version writes the second proposal,
    which moves the index to the two-official figure.

    PRD §2.8: "**Proposing a crew assignment** (`POST /crew-assignments`) requires a
    non-optional `expected_game_version` field in the request body, carrying the
    `version` of the target game as the client last observed it — the same value
    returned when reading that game."

    Design: Corner/cross_cutting_layers/stale_expected_game_version_on_assignment_create_returns_412
    """
    game = game_whose_version_one_proposal_has_already_moved["game"]
    fresh = fx.read_game(game["id"])

    retried = fx.propose_assignment(
        game["id"],
        game_whose_version_one_proposal_has_already_moved["referee"]["id"],
        "REFEREE",
        expected_game_version=fresh["version"],
    )
    after = fx.read_game(game["id"])

    assert retried["status"] == "PROPOSED"
    assert after["version"] == fresh["version"] + 1
    assert after["crew_strength_index"] == 8.64


# ─── The official version a discipline create must pin ──

@pytest.fixture
def official_activated_behind_the_directors_back():
    """Dan registered as a CANDIDATE — his version remembered from that moment — and
    then activated by a passed rules exam."""
    program = fx.create_open_program()
    official = fx.register_official(program["id"])
    fx.add_training_record(official["id"], f.rules_exam_payload(84.00, "EX-D1"))
    return {
        "program": program,
        "official": official,
        "stale_version": official["version"],
    }


def test_the_version_captured_before_activation_is_stale(
    official_activated_behind_the_directors_back,
):
    """The exam's auto-activation moved the official, so a discipline action pinned to
    the registration-time version is refused.

    PRD §2.8: "If `expected_official_version` does not equal the official's current
    `version`, the request is rejected with `ERR_STALE_OFFICIAL_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/stale_expected_official_version_on_discipline_create_returns_412
    """
    official = official_activated_behind_the_directors_back["official"]
    stale_version = official_activated_behind_the_directors_back["stale_version"]

    validate_error(
        api_client.create_discipline_action(
            f.discipline_action_payload(
                official["id"], "PERFORMANCE", "REMEDIATION", stale_version
            ),
            fx.DIRECTOR,
        ),
        "ERR_STALE_OFFICIAL_VERSION",
        412,
    )

    fresh = fx.read_official(official["id"])

    assert fresh["status"] == "ACTIVE"
    assert fresh["version"] > stale_version


def test_the_retry_opens_the_action_and_puts_him_on_probation(
    official_activated_behind_the_directors_back,
):
    """Pinned to the re-read version the action opens with no cycles spent, and the
    remediation moves the official from ACTIVE to PROBATION.

    PRD §3.8: "A `REMEDIATION` of any reason category moves an `ACTIVE` official to
    `PROBATION`."

    Design: Corner/cross_cutting_layers/stale_expected_official_version_on_discipline_create_returns_412
    """
    official_id = official_activated_behind_the_directors_back["official"]["id"]
    fresh = fx.read_official(official_id)

    action = fx.open_discipline(
        official_id,
        "PERFORMANCE",
        "REMEDIATION",
        expected_official_version=fresh["version"],
    )
    after = fx.read_official(official_id)

    assert action["status"] == "OPENED"
    assert action["remediation_cycle_count"] == 0
    assert after["status"] == "PROBATION"
    assert after["version"] == fresh["version"] + 1


# ─── The season quota counts prior work ────────────────

@pytest.fixture
def three_games_against_the_same_team():
    """Three one-slot games whose occupancy windows touch but never overlap, with
    Buffalo appearing in all three."""
    program = fx.solo_program()
    official = fx.register_umpire(program["id"])
    return {
        "program": program,
        "official": official,
        "game_one": fx.schedule_game(
            program["id"],
            home_team_code="MIA",
            away_team_code="BUF",
            venue_market_code="MIA",
            kickoff_utc=INSTANT_G1_KICKOFF,
        ),
        "game_two": fx.schedule_game(
            program["id"],
            home_team_code="BUF",
            away_team_code="DEN",
            venue_market_code="BUF",
            kickoff_utc=INSTANT_G2_KICKOFF,
        ),
        "game_three": fx.schedule_game(
            program["id"],
            home_team_code="SEA",
            away_team_code="BUF",
            venue_market_code="SEA",
            kickoff_utc=INSTANT_G3_KICKOFF,
        ),
    }


def test_the_first_two_exposures_are_accepted_on_adjacent_windows(
    three_games_against_the_same_team,
):
    """Both proposals are written, and the second window opens exactly where the first
    one closes, so the fatigue rule above the quota never fires.

    PRD §3.4: "Exact adjacency does not conflict — a second game whose
    `occupied_from_utc` lands precisely on the first window's `occupied_until_utc` is
    accepted, while a second game whose window opens even one minute before that
    instant is rejected with `ERR_OFFICIAL_WINDOW_CONFLICT`."

    Design: Corner/cross_cutting_layers/third_exposure_to_the_same_team_trips_the_rotation_cap
    """
    official_id = three_games_against_the_same_team["official"]["id"]

    first = fx.propose_assignment(
        three_games_against_the_same_team["game_one"]["id"],
        official_id,
        "UMPIRE",
        expected_game_version=three_games_against_the_same_team["game_one"]["version"],
    )
    second = fx.propose_assignment(
        three_games_against_the_same_team["game_two"]["id"],
        official_id,
        "UMPIRE",
        expected_game_version=three_games_against_the_same_team["game_two"]["version"],
    )

    assert_instant_equals(
        first["occupied_until_utc"], INSTANT_G1_OCCUPIED_UNTIL, "occupied_until_utc"
    )
    assert_instant_equals(
        second["occupied_from_utc"], INSTANT_G2_OCCUPIED_FROM, "occupied_from_utc"
    )
    assert_instant_equals(
        second["occupied_until_utc"], INSTANT_G2_OCCUPIED_UNTIL, "occupied_until_utc"
    )


def test_the_third_exposure_to_buffalo_is_refused_and_counts_nothing(
    three_games_against_the_same_team,
):
    """Two prior exposures to Buffalo already exist, so the third proposal trips the
    cap, exactly two assignments survive and the official's open count never moved.

    PRD §3.4: "If that count is greater than or equal to the program's
    `max_team_exposures_per_season`, the proposal is rejected with
    `ERR_TEAM_ROTATION_LIMIT`; either of the two teams may trip the cap."

    Design: Corner/cross_cutting_layers/third_exposure_to_the_same_team_trips_the_rotation_cap
    """
    official_id = three_games_against_the_same_team["official"]["id"]
    first = fx.propose_assignment(
        three_games_against_the_same_team["game_one"]["id"],
        official_id,
        "UMPIRE",
        expected_game_version=three_games_against_the_same_team["game_one"]["version"],
    )
    second = fx.propose_assignment(
        three_games_against_the_same_team["game_two"]["id"],
        official_id,
        "UMPIRE",
        expected_game_version=three_games_against_the_same_team["game_two"]["version"],
    )

    validate_error(
        api_client.create_crew_assignment(
            f.crew_assignment_payload(
                three_games_against_the_same_team["game_three"]["id"],
                official_id,
                "UMPIRE",
                three_games_against_the_same_team["game_three"]["version"],
            ),
            fx.SCHEDULER,
        ),
        "ERR_TEAM_ROTATION_LIMIT",
        409,
    )

    rows, meta = validate_paginated(
        api_client.list_crew_assignments(fx.SCHEDULER, {"official_id": official_id})
    )

    assert meta["total_count"] == 2
    assert rows[0]["id"] == first["id"]
    assert rows[1]["id"] == second["id"]
    assert fx.read_official(official_id)["open_assignment_count"] == 2


# ─── One call closes the season ────────────────────────

@pytest.fixture
def finalized_season_ready_to_lock():
    """A one-official program whose only game is FINALIZED with three FINAL grades on
    Dan — two clean plays and one low-impact missed call — and who attended no rules
    clinic, leaving him one training deficiency."""
    return fx.finalized_game_with_final_grades()


def test_the_lock_moves_the_program_and_counts_the_eligible_official(
    finalized_season_ready_to_lock,
):
    """Before the lock the record is still provisional at 95.00; the lock terminates
    the program, bumps its version once and publishes the eligible count.

    PRD §3.9: "Once every record is settled, the program's `eligible_official_count`
    is set to the number of its season records whose `postseason_eligible` is true, the
    program's `status` moves `OPEN → POSTSEASON_LOCKED`, and the program's `version`
    bumps by 1."

    Design: Corner/cross_cutting_layers/postseason_lock_cascades_into_retention_and_the_eligible_count
    """
    program_id = finalized_season_ready_to_lock["program"]["id"]
    before_program = fx.read_program(program_id)
    before_record = fx.season_record_for(
        finalized_season_ready_to_lock["official"]["id"]
    )

    assert before_record["accuracy_variant"] == "PROVISIONAL"
    assert before_record["graded_play_count"] == 3
    assert before_record["accuracy_index"] == 95.00

    locked = fx.lock_postseason(program_id)

    assert locked["status"] == "POSTSEASON_LOCKED"
    assert locked["version"] == before_program["version"] + 1
    assert locked["eligible_official_count"] == 1


def test_the_lock_settles_accuracy_availability_and_retention_together(
    finalized_season_ready_to_lock,
):
    """The single lock call switches the record to its final variant, computes full
    availability, and prices retention from the pre-penalty composite: 96.50 in the
    high band, less 2.00 for the missing clinic, is 94.50 and a RETAIN.

    PRD §3.9: "Stage two selects a penalty rate **from that raw composite, before any
    penalty is applied** — 2.00 when the raw composite is greater than or equal to
    90.00, otherwise 5.00 when it is greater than or equal to 80.00, otherwise 9.00."

    Design: Corner/cross_cutting_layers/postseason_lock_cascades_into_retention_and_the_eligible_count
    """
    official_id = finalized_season_ready_to_lock["official"]["id"]

    fx.lock_postseason(finalized_season_ready_to_lock["program"]["id"])
    record = fx.season_record_for(official_id)

    assert record["accuracy_variant"] == "FINAL"
    assert record["graded_play_count"] == 3
    assert record["weighted_error_points"] == 0.75
    assert record["accuracy_index"] == 95.00
    assert record["accuracy_eligible"] is True
    assert record["availability_component"] == 100.00
    assert record["retention_score"] == 94.50
    assert record["retention_recommendation"] == "RETAIN"
    assert record["postseason_eligible"] is True
    assert fx.read_official(official_id)["status"] == "ACTIVE"

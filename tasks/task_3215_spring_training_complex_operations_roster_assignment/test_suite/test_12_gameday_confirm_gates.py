"""Gameday confirm gates: the medical-clearance precondition outranks the
injury-travel safety pairing."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_complex,
    create_game,
    create_group_with_assignment,
    fresh_game_version,
    get_participation,
    get_throw_program,
    onboard_player,
    publish_game,
    schedule_physical,
    set_test_clock,
    validate_error,
    validate_success,
)


def test_an_uncleared_pitcher_is_refused_on_medical_clearance_not_injury_travel():
    """PRD 3.8: "the player's `clearance_status` must be `CAMP_CLEARED` (else
    `ERR_MEDICAL_CLEARANCE_REQUIRED`, HTTP 422); and the player's throwing
    program `requirement_status` must not be `UNMET`"
    PRD 3.8: "a strict-precursor phase — `PHASE_1`, `PHASE_2` or `PHASE_3` — on
    an away participation without that clearance is refused with
    `ERR_INJURY_TRAVEL_UNSAFE` (HTTP 422)."
    PRD 2.9: "Safety preconditions next: `ERR_MEDICAL_CLEARANCE_REQUIRED`
    (HTTP 422), then `ERR_INJURY_TRAVEL_UNSAFE` (HTTP 422)"

    Design: Difficulty/priority_pair_validation_conflict/clearing_and_clearance_pair_produces_injury_error_not_travel_error
    """
    set_test_clock()
    complex_ = create_complex()
    onboarded = onboard_player(complex_["id"], clear=False, invitation=False)
    player_id = onboarded["player"]["id"]
    failing = schedule_physical(player_id, "2026-01-02T00:00:00Z")
    validate_success(api_client.perform_physical(
        failing["id"], "FAILED", TEST_USERS["team_physician_headers"]))

    group, assignment = create_group_with_assignment(
        complex_["id"], player_id, assignment_kind="REHAB")
    program = validate_success(api_client.create_throw_program(
        assignment["id"],
        {"group_assignment_id": assignment["id"], "target_catch_play_throws": 120,
         "target_bullpen_sessions": 2},
        TEST_USERS["pitching_coordinator_headers"]), 201)

    game = create_game(
        complex_["id"], opponent_name="Arizona Diamondbacks", home_away="AWAY",
        game_datetime="2026-01-06T00:00:00Z", travel_radius_miles=180, duration_units=3)
    publish_game(game["id"])
    participation = validate_success(api_client.create_participation(
        game["id"],
        {"game_schedule_id": game["id"], "player_id": player_id,
         "squad_side": "AWAY_SQUAD", "throw_count": 0},
        TEST_USERS["field_coordinator_headers"]), 201)

    validate_error(
        api_client.confirm_participation(
            game["id"], participation["id"], fresh_game_version(game["id"]),
            TEST_USERS["field_coordinator_headers"]),
        ApiErrorId.ERR_MEDICAL_CLEARANCE_REQUIRED,
    )
    assert get_participation(participation["id"])["participation_status"] == "SCHEDULED"
    assert get_throw_program(program["id"])["program_phase"] == "PHASE_1"


def test_an_uncleared_pitcher_still_reports_the_clearance_error_first():
    """PRD 2.9: "The practical consequence is that a caller who is both
    unauthorized and would also violate a business rule sees `ERR_UNAUTHORIZED`,
    and a caller who names both a missing parent and a missing body reference
    sees `ERR_RESOURCE_NOT_FOUND`. Within the state families, a roster record
    with a terminal status is reported as `ERR_ROSTER_ALREADY_FINAL` only after
    the transition-legality check has already failed to apply."

    Design: Difficulty/priority_pair_validation_conflict/clearing_and_clearance_pair_produces_injury_error_not_travel_error
    """
    set_test_clock()
    complex_ = create_complex()
    onboarded = onboard_player(complex_["id"], clear=False, invitation=False)
    player_id = onboarded["player"]["id"]
    group, assignment = create_group_with_assignment(
        complex_["id"], player_id, assignment_kind="REHAB")
    program = validate_success(api_client.create_throw_program(
        assignment["id"],
        {"group_assignment_id": assignment["id"], "target_catch_play_throws": 120,
         "target_bullpen_sessions": 2},
        TEST_USERS["pitching_coordinator_headers"]), 201)

    # the player is uncleared (never examined) and still short of PHASE_2, so
    # both the clearance pairing and the injury-travel pairing would fire
    game = create_game(
        complex_["id"], opponent_name="San Diego Padres", home_away="AWAY",
        game_datetime="2026-01-06T00:00:00Z", travel_radius_miles=180, duration_units=3)
    publish_game(game["id"])
    participation = validate_success(api_client.create_participation(
        game["id"],
        {"game_schedule_id": game["id"], "player_id": player_id,
         "squad_side": "AWAY_SQUAD", "throw_count": 0},
        TEST_USERS["field_coordinator_headers"]), 201)

    resp = api_client.confirm_participation(
        game["id"], participation["id"], fresh_game_version(game["id"]), TEST_USERS["field_coordinator_headers"])
    assert resp.status_code == 422
    error_id = resp.json()["data"]["error_id"]
    assert error_id == ApiErrorId.ERR_MEDICAL_CLEARANCE_REQUIRED
    assert error_id != ApiErrorId.ERR_INJURY_TRAVEL_UNSAFE
    assert get_participation(participation["id"])["participation_status"] == "SCHEDULED"
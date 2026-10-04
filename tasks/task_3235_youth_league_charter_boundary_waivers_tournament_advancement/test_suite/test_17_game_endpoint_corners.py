"""Game-endpoint corners: tie-score rejection, roster membership for
appearances, and the pitch cap at recording."""
from test_helpers import (
    TEST_USERS, api_client, validate_success, validate_error,
    get_success_data, ApiErrorId,
    set_clock, register_and_verify_player, major_division, get_game,
    setup_tournament_entry, create_game, record_appearance,
)

LA = TEST_USERS["league_admin_headers"]
TD = TEST_USERS["tournament_director_headers"]
SCORER = TEST_USERS["official_scorer_headers"]


def test_tie_score_at_finalize_rejected(api):
    """PRD §3.7: "The two scores must differ; a tied score is rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/endpoints/finalize_with_tie_score_returns_invalid_request
    """
    ctx = setup_tournament_entry(league_name="Tie LL")
    set_clock("2027-06-01T00:00:00Z")
    game = create_game(ctx["entry"]["id"])
    record_appearance(ctx["entry"]["id"], game["id"], ctx["players"][0]["id"], 10)

    err = validate_error(api.finalize_game(
        ctx["entry"]["id"], game["id"],
        {"our_score": 3, "opponent_score": 3,
         "expected_game_version": game["version"] + 1}, TD),
        ApiErrorId.ERR_INVALID_REQUEST)
    assert err["error_id"] == "ERR_INVALID_REQUEST"
    game_after = get_game(game["id"])
    assert game_after["play_status"] == "IN_PROGRESS"
    assert game_after["result"] is None


def test_appearance_by_non_roster_player_rejected(api):
    """PRD §3.7: "the player must hold an `ACTIVE` selection on the roster of
    the entry the game belongs to, or the recording is rejected with
    `ERR_PLAYER_NOT_ON_ROSTER` (HTTP 422)."
    PRD §3.7: "The game starts itself: when an `OfficialScorer` records the
    first pitching appearance against a `SCHEDULED` game, the game moves to
    `IN_PROGRESS` and its `game_date` is set to the current clock date."

    Design: Corner/endpoints/appearance_by_non_roster_player_rejected
    """
    ctx = setup_tournament_entry(n=3, league_name="Off Roster LL")
    # A fourth ELIGIBLE MAJOR player who is never selected.
    set_clock("2027-02-01T00:00:00Z")
    outsider = register_and_verify_player(
        ctx["league"]["id"], birth_date="2015-06-13", last_name="Four")
    set_clock("2027-06-01T00:00:00Z")
    game = create_game(ctx["entry"]["id"])

    err = validate_error(api.record_pitching_appearance(
        ctx["entry"]["id"], game["id"],
        {"player_id": outsider["id"], "pitches_thrown": 10}, SCORER),
        ApiErrorId.ERR_PLAYER_NOT_ON_ROSTER)
    assert err["error_id"] == "ERR_PLAYER_NOT_ON_ROSTER"
    # The rejected appearance does not start the game.
    game_after = get_game(game["id"])
    assert game_after["play_status"] == "SCHEDULED"
    assert game_after["recorded_pitch_total"] == 0


def test_pitch_cap_exceeded_at_recording_but_inclusive_cap_succeeds(api):
    """PRD §3.7: "at recording time, the reported `pitches_thrown` must not
    exceed the pitch maximum of the player's division — 50 for `TEE_BALL`, 75
    for `MINOR`, 85 for `MAJOR`, 95 for `JUNIOR`, and 95 for `SENIOR` — or the
    recording is rejected with `ERR_PITCH_COUNT_EXCEEDED` (HTTP 422)."
    PRD §3.7: "66 pitches up to and including the division maximum require
    4 days."

    Design: Corner/errors/pitch_cap_exceeded_at_recording
    """
    ctx = setup_tournament_entry(league_name="Cap LL")
    set_clock("2027-06-01T00:00:00Z")
    game = create_game(ctx["entry"]["id"])
    record_appearance(ctx["entry"]["id"], game["id"], ctx["players"][0]["id"], 10)

    # 86 > 85 in MAJOR: rejected at recording.
    err = validate_error(api.record_pitching_appearance(
        ctx["entry"]["id"], game["id"],
        {"player_id": ctx["players"][1]["id"], "pitches_thrown": 86}, SCORER),
        ApiErrorId.ERR_PITCH_COUNT_EXCEEDED)
    assert err["error_id"] == "ERR_PITCH_COUNT_EXCEEDED"

    # 85 == MAJOR cap: the cap is inclusive.
    ok = validate_success(api.record_pitching_appearance(
        ctx["entry"]["id"], game["id"],
        {"player_id": ctx["players"][1]["id"], "pitches_thrown": 85}, SCORER),
        201)
    assert ok["rest_days_required"] == 4
    # The rejected 86 contributed nothing.
    assert get_game(game["id"])["recorded_pitch_total"] == 95

"""Peer-role exclusivity corners and immediate-consistency read-back."""
from test_helpers import (
    TEST_USERS, api_client, validate_success, validate_error,
    validate_paginated, ApiErrorId,
    set_clock, charter_league, major_division,
    register_and_verify_player, create_open_roster,
    setup_tournament_entry, create_game, record_appearance, get_game,
)

TD = TEST_USERS["tournament_director_headers"]
SCORER = TEST_USERS["official_scorer_headers"]
LA = TEST_USERS["league_admin_headers"]


def test_scorer_cannot_finalize_and_director_cannot_record_pitches(api):
    """PRD §2.1: "A request whose role is valid but not authorized for the
    target operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
    (HTTP 403)."
    PRD §4: "| POST | /tournament-entries/{entryId}/games/{gameId}/finalize |
    Finalize an IN_PROGRESS game with the official score (OCC via
    expected_game_version) | TournamentDirector |"
    PRD §4: "| POST
    | /tournament-entries/{entryId}/games/{gameId}/pitching-appearances |
    Record a pitching appearance; auto-starts the game; enforces safety rules
    | OfficialScorer |"

    Design: Corner/rbac/scorer_cannot_finalize_and_director_cannot_record_pitches
    """
    ctx = setup_tournament_entry(league_name="Peers LL")
    set_clock("2027-06-01T00:00:00Z")
    game = create_game(ctx["entry"]["id"])
    record_appearance(ctx["entry"]["id"], game["id"], ctx["players"][0]["id"], 10)

    err1 = validate_error(api.finalize_game(
        ctx["entry"]["id"], game["id"],
        {"our_score": 2, "opponent_score": 1,
         "expected_game_version": game["version"] + 1}, SCORER),
        ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    assert err1["error_id"] == "ERR_INSUFFICIENT_PERMISSIONS"

    err2 = validate_error(api.record_pitching_appearance(
        ctx["entry"]["id"], game["id"],
        {"player_id": ctx["players"][1]["id"], "pitches_thrown": 5}, TD),
        ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    assert err2["error_id"] == "ERR_INSUFFICIENT_PERMISSIONS"

    game_after = get_game(game["id"])
    assert game_after["play_status"] == "IN_PROGRESS"
    assert game_after["recorded_pitch_total"] == 10


def test_mutation_visible_in_response_and_immediate_reread(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.6: "A successful add appends a selection with status `ACTIVE` and
    recomputes `roster_size`."

    Design: Corner/consistency_model/mutation_visible_immediately_in_same_response_and_read
    """
    ctx = charter_league(league_name="Immediate LL")
    set_clock("2027-02-01T00:00:00Z")
    player = register_and_verify_player(
        ctx["league"]["id"], birth_date="2015-03-10", first_name="Im",
        last_name="Mediate")
    roster = create_open_roster(ctx["league"]["id"], major_division(ctx)["id"])

    after = validate_success(api.add_roster_selection(
        ctx["league"]["id"], roster["id"], {"player_id": player["id"]}, LA),
        201)
    # The mutation is visible in the same response.
    assert after["roster_size"] == 1

    rosters, meta = validate_paginated(api.list_all_star_rosters(
        ctx["league"]["id"], LA,
        params={"division_id": major_division(ctx)["id"]}))
    assert meta["total_count"] == 1
    # Immediately consistent on re-read — no lag.
    assert rosters[0]["roster_size"] == 1

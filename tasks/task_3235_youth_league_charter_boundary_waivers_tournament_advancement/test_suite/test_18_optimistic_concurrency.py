"""Optimistic concurrency: the two OCC-guarded write operations."""
from test_helpers import (
    TEST_USERS, api_client, validate_success, validate_error,
    get_success_data, ApiErrorId,
    set_clock, charter_league, register_player, patch_team_count,
    get_league, major_division,
    setup_tournament_entry, create_game, record_appearance, get_game,
)

LA = TEST_USERS["league_admin_headers"]
TD = TEST_USERS["tournament_director_headers"]
SCORER = TEST_USERS["official_scorer_headers"]


def test_stale_game_version_on_finalize_rejected_then_fresh_succeeds(api):
    """PRD §2.6: "Finalizing a tournament game requires the request to carry
    `expected_game_version`, holding the client-observed `version` of the game.
    Because every recorded pitching appearance advances the game's `version`, a
    client that reviewed the appearance set and then sends its finalization
    against an older `version` is rejected with `ERR_STALE_VERSION`
    (HTTP 412) — the official score may only be certified against the complete
    appearance set the client actually observed."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_game_version_rejected
    """
    ctx = setup_tournament_entry(league_name="OCC Game LL")
    set_clock("2027-06-01T00:00:00Z")
    game = create_game(ctx["entry"]["id"])
    observed_version = game["version"]
    # The appearance advances the game version past the observed one.
    record_appearance(ctx["entry"]["id"], game["id"], ctx["players"][0]["id"], 12)

    err = validate_error(api.finalize_game(
        ctx["entry"]["id"], game["id"],
        {"our_score": 2, "opponent_score": 1,
         "expected_game_version": observed_version}, TD),
        ApiErrorId.ERR_STALE_VERSION)
    assert err["error_id"] == "ERR_STALE_VERSION"

    finalized = validate_success(api.finalize_game(
        ctx["entry"]["id"], game["id"],
        {"our_score": 2, "opponent_score": 1,
         "expected_game_version": observed_version + 1}, TD), 200)
    assert finalized["play_status"] == "FINAL"


def test_stale_league_version_on_waiver_create_rejected_then_fresh_succeeds(api):
    """PRD §2.6: "Creating a boundary waiver requires the request to carry
    `expected_league_version`, holding the client-observed `version` of the
    parent league. If the league's current `version` has advanced past that
    value — because a charter renewal was decided, a suspension sweep fired, a
    team count was patched, or another waiver was created against the same
    league — the creation is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_league_version_rejected_on_waiver_create
    """
    ctx = charter_league(league_name="OCC League LL")
    set_clock("2027-02-01T00:00:00Z")
    player = register_player(ctx["league"]["id"], first_name="Oc",
                             last_name="Cee")
    observed_version = get_league(ctx["league"]["id"])["version"]
    # A division PATCH advances the league version between read and write.
    patch_team_count(ctx["league"]["id"], major_division(ctx)["id"], 2)

    payload = {"player_id": player["id"], "waiver_type": "RESIDENCY_BOUNDARY",
               "reason": "stale attempt", "valid_from": "2027-01-01",
               "valid_until": "2027-12-01",
               "expected_league_version": observed_version}
    err = validate_error(api.create_boundary_waiver(ctx["league"]["id"],
                                                    payload, LA),
                         ApiErrorId.ERR_STALE_VERSION)
    assert err["error_id"] == "ERR_STALE_VERSION"

    fresh_version = get_league(ctx["league"]["id"])["version"]
    payload["expected_league_version"] = fresh_version
    payload["reason"] = "fresh attempt"
    waiver = validate_success(api.create_boundary_waiver(
        ctx["league"]["id"], payload, LA), 201)
    assert waiver["id"]
    assert waiver["status"] == "PENDING"

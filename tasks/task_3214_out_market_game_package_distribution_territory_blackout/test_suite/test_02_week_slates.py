"""Weekly slate posture: national selections, finalize/reopen/lock, derived
field reconciliation, and immediate-consistency reads."""
from test_helpers import (
    ApiErrorId,
    assert_week_slate,
    create_game,
    create_grant,
    create_market,
    create_season,
    create_slate,
    set_clock,
    validate_error,
    validate_success,
)


def _slate_with_three_games(api, ops_headers):
    """Grant + season + NYC/DAL/LA markets + week-4 slate + three games."""
    set_clock("2026-09-01T00:00:00Z")
    grant = create_grant()
    season = create_season(grant["id"])
    create_market(code="NYC", name="New York", zip_prefixes=["100"],
                  home_team_codes=["NYC"])
    create_market(code="DAL", name="Dallas", zip_prefixes=["750"],
                  home_team_codes=["DAL"])
    create_market(code="LA", name="Los Angeles", zip_prefixes=["900"],
                  home_team_codes=["LAC"])
    slate = create_slate(season["id"], week_index=4)
    game_dal = create_game(season["id"], away_team_code="KC",
                           home_team_code="DAL",
                           kickoff_at="2026-08-30T17:00:00Z",
                           home_market_code="DAL")
    game_nyc = create_game(season["id"], away_team_code="BUF",
                           home_team_code="NYC",
                           kickoff_at="2026-08-30T17:00:00Z",
                           home_market_code="NYC")
    game_la = create_game(season["id"], away_team_code="LAC",
                          home_team_code="DEN",
                          kickoff_at="2026-08-30T20:00:00Z",
                          home_market_code="LA")
    return season, slate, game_dal, game_nyc, game_la


def test_package_count_tracks_posture_from_prelim_through_reopen(
    api, league_ops_headers
):
    """PRD §3.4: "the count of games in the package for the week, always the
    total number of games scheduled in that week minus the games currently
    carried as national selections." PRD §3.4: "reopening moves `FINALIZED` →
    `PRELIMINARY`, clears `finalized_game_ids` back to empty, recomputes
    `package_game_count` back to the live count, and increments `version`."

    Design: Difficulty/combinatorial_formula/game_availability_set_difference_across_postures
    """
    _, slate, game_dal, game_nyc, game_la = _slate_with_three_games(
        api, league_ops_headers
    )
    moved = validate_success(
        api.slate_selection(slate["id"], game_dal["id"], "ADD",
                            slate["version"], league_ops_headers)
    )
    assert moved["package_game_count"] == 2
    assert moved["finalized_game_ids"] == []

    finalized = validate_success(
        api.finalize_week_slate(slate["id"], moved["version"], league_ops_headers)
    )
    assert sorted(finalized["finalized_game_ids"]) == sorted(
        [game_nyc["id"], game_la["id"]]
    )
    assert finalized["package_game_count"] == 2

    late_move = validate_success(
        api.slate_selection(slate["id"], game_nyc["id"], "ADD",
                            finalized["version"], league_ops_headers)
    )
    assert late_move["package_game_count"] == 1
    assert late_move["finalized_game_ids"] == [game_la["id"]]

    reopened = validate_success(
        api.reopen_week_slate(slate["id"], league_ops_headers)
    )
    assert reopened["slate_status"] == "PRELIMINARY"
    assert reopened["finalized_game_ids"] == []
    assert reopened["package_game_count"] == 1


def test_finalized_snapshot_excludes_national_selections(
    api, league_ops_headers
):
    """PRD §3.4: "Finalization freezes the picture subscribers see.
    Finalizing a slate (OCC-guarded, §2.7) moves it `PRELIMINARY` →
    `FINALIZED`: the system computes `finalized_game_ids` as the
    package-eligible games at that instant — all games of the week minus the
    national selections, with per-subscriber blackout irrelevant at the slate
    level — stamps `finalized_at` with the logical clock, and increments
    `version`."

    Design: Difficulty/combinatorial_formula/game_availability_set_difference_across_postures
    """
    _, slate, game_dal, game_nyc, game_la = _slate_with_three_games(
        api, league_ops_headers
    )
    moved = validate_success(
        api.slate_selection(slate["id"], game_dal["id"], "ADD",
                            slate["version"], league_ops_headers)
    )
    finalized = validate_success(
        api.finalize_week_slate(slate["id"], moved["version"], league_ops_headers)
    )
    assert finalized["slate_status"] == "FINALIZED"
    assert sorted(finalized["finalized_game_ids"]) == sorted(
        [game_nyc["id"], game_la["id"]]
    )
    assert game_dal["id"] not in finalized["finalized_game_ids"]
    assert finalized["package_game_count"] == 2
    assert_week_slate(finalized)


def test_finalize_reopen_correction_loop_cycles_and_versions(
    api, league_ops_headers
):
    """PRD §3.4: "Corrections remain possible: reopening moves `FINALIZED` →
    `PRELIMINARY`, clears `finalized_game_ids` back to empty, recomputes
    `package_game_count` back to the live count, and increments `version`. The
    slate may then be re-finalized; this correction loop can cycle
    indefinitely."

    Design: Difficulty/non_linear_state_machine/week_slate_finalize_reopen_correction_loop
    """
    set_clock("2026-09-01T00:00:00Z")
    grant = create_grant()
    season = create_season(grant["id"])
    create_market(code="DAL", name="Dallas", zip_prefixes=["750"],
                  home_team_codes=["DAL"])
    create_market(code="NYC", name="New York", zip_prefixes=["100"],
                  home_team_codes=["NYC"])
    slate = create_slate(season["id"], week_index=4)
    game_dal = create_game(season["id"], away_team_code="KC",
                           home_team_code="DAL",
                           kickoff_at="2026-08-30T17:00:00Z",
                           home_market_code="DAL")
    game_nyc = create_game(season["id"], away_team_code="BUF",
                           home_team_code="NYC",
                           kickoff_at="2026-08-30T20:00:00Z",
                           home_market_code="NYC")
    v0 = slate["version"]

    fin1 = validate_success(
        api.finalize_week_slate(slate["id"], v0, league_ops_headers)
    )
    assert fin1["slate_status"] == "FINALIZED"

    reopened = validate_success(
        api.reopen_week_slate(slate["id"], league_ops_headers)
    )
    assert reopened["slate_status"] == "PRELIMINARY"
    assert reopened["finalized_game_ids"] == []

    fin2 = validate_success(
        api.finalize_week_slate(slate["id"], reopened["version"], league_ops_headers)
    )
    assert fin2["slate_status"] == "FINALIZED"
    assert sorted(fin2["finalized_game_ids"]) == sorted(
        [game_dal["id"], game_nyc["id"]]
    )
    assert fin2["version"] == v0 + 3


def test_reopen_then_refinalize_refreshes_snapshot_after_selection_change(
    api, league_ops_headers
):
    """PRD §3.4: "In `FINALIZED` the same move additionally recomputes the
    `finalized_game_ids` snapshot so the official view still excludes the
    newly national games."

    Design: Difficulty/non_linear_state_machine/week_slate_finalize_reopen_correction_loop
    """
    _, slate, game_dal, game_nyc, game_la = _slate_with_three_games(
        api, league_ops_headers
    )
    fin1 = validate_success(
        api.finalize_week_slate(slate["id"], slate["version"], league_ops_headers)
    )
    assert len(fin1["finalized_game_ids"]) == 3
    moved = validate_success(
        api.slate_selection(slate["id"], game_nyc["id"], "ADD",
                            fin1["version"], league_ops_headers)
    )
    assert sorted(moved["finalized_game_ids"]) == sorted(
        [game_dal["id"], game_la["id"]]
    )
    assert game_nyc["id"] not in moved["finalized_game_ids"]
    assert moved["package_game_count"] == 2


def test_wrong_week_game_selection_rejected_without_mutation(
    api, league_ops_headers
):
    """PRD §3.4: "The target game must exist, belong to the slate's season,
    and have a `week_index` equal to the slate's own — otherwise
    `ERR_GAME_WEEK_MISMATCH` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/selection_move_gated_by_game_week_membership
    """
    set_clock("2026-09-01T00:00:00Z")
    grant = create_grant()
    season = create_season(grant["id"])
    create_market(code="DAL", name="Dallas", zip_prefixes=["750"],
                  home_team_codes=["DAL"])
    slate4 = create_slate(season["id"], week_index=4)
    create_slate(season["id"], week_index=5)
    game4 = create_game(season["id"], week_index=4, away_team_code="KC",
                        home_team_code="DAL",
                        kickoff_at="2026-08-30T17:00:00Z",
                        home_market_code="DAL")
    game5 = create_game(season["id"], week_index=5, away_team_code="BUF",
                        home_team_code="DAL",
                        kickoff_at="2026-09-06T17:00:00Z",
                        home_market_code="DAL")

    err = validate_error(
        api.slate_selection(slate4["id"], game5["id"], "ADD",
                            slate4["version"], league_ops_headers),
        ApiErrorId.ERR_GAME_WEEK_MISMATCH,
    )
    assert err is not None
    slate_now = validate_success(
        api.get_week_slate(slate4["id"], league_ops_headers)
    )
    assert slate_now["national_game_ids"] == []

    moved = validate_success(
        api.slate_selection(slate4["id"], game4["id"], "ADD",
                            slate4["version"], league_ops_headers)
    )
    assert moved["package_game_count"] == 0
    assert moved["national_game_ids"] == [game4["id"]]


def test_selection_move_requires_matching_season_membership(
    api, league_ops_headers
):
    """PRD §3.4: "The target game must exist, belong to the slate's season,
    and have a `week_index` equal to the slate's own — otherwise
    `ERR_GAME_WEEK_MISMATCH` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/selection_move_gated_by_game_week_membership
    """
    set_clock("2026-09-01T00:00:00Z")
    grant = create_grant()
    season_a = create_season(grant["id"], label="2026-Regular")
    season_b = create_season(grant["id"], label="2026-Alt",
                             season_start_date="2026-08-05T00:00:00Z",
                             season_end_date="2026-12-09T00:00:00Z")
    create_market(code="DAL", name="Dallas", zip_prefixes=["750"],
                  home_team_codes=["DAL"])
    slate = create_slate(season_a["id"], week_index=4)
    other_season_game = create_game(
        season_b["id"], week_index=4, away_team_code="KC",
        home_team_code="DAL", kickoff_at="2026-08-30T17:00:00Z",
        home_market_code="DAL",
    )
    validate_error(
        api.slate_selection(slate["id"], other_season_game["id"], "ADD",
                            slate["version"], league_ops_headers),
        ApiErrorId.ERR_GAME_WEEK_MISMATCH,
    )
    slate_now = validate_success(
        api.get_week_slate(slate["id"], league_ops_headers)
    )
    assert slate_now["national_game_ids"] == []


def test_game_creation_reconciles_live_count_and_reopen_clears_snapshot(
    api, league_ops_headers
):
    """PRD §3.3: "When a game is created and a week slate already exists for
    that (season, week) pair, the slate's `package_game_count` is recomputed
    to absorb the new game." PRD §3.4: "reopening moves `FINALIZED` →
    `PRELIMINARY`, clears `finalized_game_ids` back to empty, recomputes
    `package_game_count` back to the live count, and increments `version`."

    Design: Corner/cross_cutting_layers/derived_slate_fields_reconciled_on_game_add_and_reopen
    """
    set_clock("2026-09-01T00:00:00Z")
    grant = create_grant()
    season = create_season(grant["id"])
    create_market(code="DAL", name="Dallas", zip_prefixes=["750"],
                  home_team_codes=["DAL"])
    slate = create_slate(season["id"], week_index=4)
    assert slate["package_game_count"] == 0

    game_a = create_game(season["id"], away_team_code="KC",
                         home_team_code="DAL",
                         kickoff_at="2026-08-30T17:00:00Z",
                         home_market_code="DAL")
    game_b = create_game(season["id"], away_team_code="BUF",
                         home_team_code="DAL",
                         kickoff_at="2026-08-30T20:00:00Z",
                         home_market_code="DAL")

    live = validate_success(api.get_week_slate(slate["id"], league_ops_headers))
    assert live["package_game_count"] == 2

    finalized = validate_success(
        api.finalize_week_slate(slate["id"], live["version"], league_ops_headers)
    )
    assert sorted(finalized["finalized_game_ids"]) == sorted(
        [game_a["id"], game_b["id"]]
    )

    reopened = validate_success(
        api.reopen_week_slate(slate["id"], league_ops_headers)
    )
    assert reopened["finalized_game_ids"] == []
    assert reopened["package_game_count"] == 2


def test_mutation_response_and_immediate_read_agree(
    api, league_ops_headers
):
    """PRD §3.4: "Every move recomputes `package_game_count` and increments
    the slate's `version`." PRD §2.4: "Whenever any mutating operation touches
    a resource, that resource's `updated_at` refreshes to the current
    logical-clock instant and, where the field exists, `version` advances by
    one."

    Design: Corner/consistency_model/immediate_consistency_mutation_visible_in_same_response_and_next_read
    """
    set_clock("2026-09-01T00:00:00Z")
    grant = create_grant()
    season = create_season(grant["id"])
    create_market(code="DAL", name="Dallas", zip_prefixes=["750"],
                  home_team_codes=["DAL"])
    slate = create_slate(season["id"], week_index=4)
    game_a = create_game(season["id"], away_team_code="KC",
                         home_team_code="DAL",
                         kickoff_at="2026-08-30T17:00:00Z",
                         home_market_code="DAL")
    create_game(season["id"], away_team_code="BUF", home_team_code="DAL",
                kickoff_at="2026-08-30T20:00:00Z", home_market_code="DAL")

    resp = validate_success(
        api.slate_selection(slate["id"], game_a["id"], "ADD",
                            slate["version"], league_ops_headers)
    )
    assert resp["package_game_count"] == 1
    assert resp["version"] == slate["version"] + 1

    reread = validate_success(api.get_week_slate(slate["id"], league_ops_headers))
    assert reread["package_game_count"] == 1
    assert reread["version"] == resp["version"]
    assert reread["national_game_ids"] == [game_a["id"]]


def test_lock_gated_on_first_kickoff_instant(api, league_ops_headers):
    """PRD §3.4: "Locking is the point of no return: once the logical clock
    has reached or passed the kickoff of the week's earliest game, locking
    moves `FINALIZED` → `LOCKED`, freezing `national_game_ids` and the
    finalized snapshot immutably. `LOCKED` is terminal — selection moves and
    reopen attempts against a locked slate are rejected with
    `ERR_SLATE_LOCKED` (HTTP 409), and a lock attempt before the week's first
    kickoff, or against a slate not in `FINALIZED`, is `ERR_INVALID_STATE`."

    Design: Corner/endpoints/slate_lock_requires_first_kickoff_reached
    """
    set_clock("2026-08-20T00:00:00Z")
    grant = create_grant()
    season = create_season(grant["id"])
    create_market(code="DAL", name="Dallas", zip_prefixes=["750"],
                  home_team_codes=["DAL"])
    slate = create_slate(season["id"], week_index=3)
    create_game(season["id"], week_index=3, away_team_code="KC",
                home_team_code="DAL", kickoff_at="2026-08-23T17:00:00Z",
                home_market_code="DAL")
    slate_now = validate_success(api.get_week_slate(slate["id"], league_ops_headers))
    validate_success(
        api.finalize_week_slate(slate["id"], slate_now["version"],
                                league_ops_headers)
    )

    validate_error(
        api.lock_week_slate(slate["id"], league_ops_headers),
        ApiErrorId.ERR_INVALID_STATE,
    )
    still_finalized = validate_success(
        api.get_week_slate(slate["id"], league_ops_headers)
    )
    assert still_finalized["slate_status"] == "FINALIZED"

    set_clock("2026-08-23T17:00:00Z")
    locked = validate_success(api.lock_week_slate(slate["id"], league_ops_headers))
    assert locked["slate_status"] == "LOCKED"

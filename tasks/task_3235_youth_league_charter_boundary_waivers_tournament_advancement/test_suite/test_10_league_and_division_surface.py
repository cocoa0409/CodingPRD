"""League and division surface: creation shape, auto-created divisions, team
count rollup."""
from test_helpers import (
    TEST_USERS, api_client, validate_success, validate_paginated,
    is_valid_uuid, is_iso8601_timestamp,
    set_clock, create_league_raw, patch_team_count, get_league,
    assert_league, assert_division,
)

DA = TEST_USERS["district_admin_headers"]
LA = TEST_USERS["league_admin_headers"]


def test_league_create_shape_and_five_auto_created_divisions(api):
    """PRD §3.1: "Creation does not grant a charter: the league's
    `charter_status` begins as `PROVISIONAL`. Creation does, however, build the
    league's entire competitive skeleton in one step — five divisions are
    auto-created in a fixed creation order: `TEE_BALL` first, then `MINOR`, then
    `MAJOR`, then `JUNIOR`, then `SENIOR`. Each division carries a standard
    league-age range: `TEE_BALL` spans ages 4 through 6 (`min_league_age` 4,
    `max_league_age` 6), `MINOR` spans 7 through 9, `MAJOR` spans 10 through 12,
    `JUNIOR` spans 13 through 14, and `SENIOR` spans 15 through 16. Every
    division starts with a `team_count` of 0 and `status` `ACTIVE`. When the
    league's divisions are listed, they come back in `created_at` ascending
    order with ties broken by that fixed creation order, so the first entry is
    always `TEE_BALL` and the fifth is always `SENIOR`. The league's
    `total_team_count` is initialized to 0 at creation."

    Design: Corner/entities/league_create_returns_all_fields_and_autocreates_five_divisions
    """
    set_clock("2026-10-15T00:00:00Z")
    league = validate_success(api.create_league(
        {"league_name": "Cedar Falls LL", "region_code": "CENTRAL",
         "season_year": 2027}, DA), 201)
    assert_league(league)
    assert league["charter_status"] == "PROVISIONAL"
    assert league["total_team_count"] == 0
    assert league["version"] == 1

    divisions, meta = validate_paginated(
        api.list_divisions(league["id"], DA))
    assert len(divisions) == 5
    assert meta["total_count"] == 5
    assert divisions[0]["division_code"] == "TEE_BALL"
    assert divisions[4]["division_code"] == "SENIOR"
    for division in divisions:
        assert_division(division)
        assert division["team_count"] == 0
        assert division["status"] == "ACTIVE"
    tee = divisions[0]
    senior = divisions[4]
    assert (tee["min_league_age"], tee["max_league_age"]) == (4, 6)
    assert (senior["min_league_age"], senior["max_league_age"]) == (15, 16)


def test_division_patch_recomputes_total_and_bumps_league_version(api):
    """PRD §3.1: "A `LeagueAdministrator` sets how many teams the league will
    field in each division by patching the division's `team_count`, which
    defaults to 0; this is allowed while the league is `PROVISIONAL` or
    `CHARTERED`. Every such patch recomputes the league's `total_team_count` as
    the sum of `team_count` across all five of the league's divisions, and bumps
    the league's `version` by 1 alongside the division's own."

    Design: Corner/entities/division_patch_updates_total_team_count
    """
    set_clock("2026-10-15T00:00:00Z")
    league, divisions = create_league_raw(league_name="Teams LL")
    by_code = {d["division_code"]: d for d in divisions}
    patch_team_count(league["id"], by_code["MINOR"]["id"], 2)
    patch_team_count(league["id"], by_code["MAJOR"]["id"], 3)

    league_after = get_league(league["id"])
    assert league_after["total_team_count"] == 5
    # create (1) + two PATCH bumps = 3.
    assert league_after["version"] == 3

"""Season construction: schedule, seat inventory and plan products."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_season,
    assert_season_plan,
    assert_seat,
    assert_service_rep,
    create_game,
    create_plan,
    create_published_plan,
    create_rep,
    create_season,
    create_season_payload,
    create_seats_payload,
    mint_seats,
    open_renewal,
    read_plan,
    read_season,
    setup_selling_world,
    validate_error,
    validate_paginated,
    validate_success,
    OPS_HEADERS,
    RM_HEADERS,
)


def test_new_season_starts_in_planning_with_zeroed_counters():
    """PRD 3.1: "A new season starts in `PLANNING`, with `dynamic_pricing_mode` `AGGRESSIVE`, `revenue_goal_met` false, `contracted_revenue_cents`, `secondary_market_volume_cents` and all four seat counters at 0, `renewal_opened_at_utc` and `last_ops_run_at_utc` null, and `version` 1."

    Design: Corner/entities/e_season_create_applies_declared_defaults
    """
    response = api_client.create_season(create_season_payload(), OPS_HEADERS)
    season = validate_success(response, 201)

    assert_season(season)
    assert season["season_status"] == "PLANNING"
    assert season["dynamic_pricing_mode"] == "AGGRESSIVE"
    assert season["revenue_goal_met"] is False
    assert season["contracted_revenue_cents"] == 0
    assert season["secondary_market_volume_cents"] == 0
    assert season["total_seat_count"] == 0
    assert season["available_seat_count"] == 0
    assert season["held_seat_count"] == 0
    assert season["assigned_seat_count"] == 0
    assert season["renewal_opened_at_utc"] is None
    assert season["last_ops_run_at_utc"] is None
    assert season["version"] == 1


def test_season_creation_without_revenue_goal_is_rejected():
    """PRD 2.9: "**Schema.** Required fields present, enum members valid, integers inside their declared ranges, ISO 8601 UTC timestamps parseable, `limit` inside 1 through 100, `offset` at least 0, `seat_ids` and `new_seat_ids` non-empty and free of duplicates, `installment_count` one of 1, 3 or 6, `hold_window_end_utc` strictly after `hold_window_start_utc`, and `service_window_end_utc` strictly after `service_window_start_utc` — otherwise `ERR_INVALID_REQUEST` (400). This applies to every endpoint."
    PRD 3.1: "A `TicketOpsAdmin` opens the books for a campaign by creating a season, supplying its franchise season `code` (a string of 1 to 16 characters, unique across all seasons), the `year` in which the season opens (2020 or later), the planned `total_home_games` count (at least 1), the `renewal_deadline_utc` instant at which the renewal priority window closes, and the `revenue_goal_cents` target (at least 1) that will eventually flip the pricing regime."

    Design: Corner/entities/e_season_create_missing_required_field_returns_invalid_request
    """
    payload = create_season_payload()
    payload.pop("revenue_goal_cents")

    response = api_client.create_season(payload, OPS_HEADERS)

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_bulk_seat_mint_creates_every_seat_in_the_range():
    """PRD 3.1: "The server creates one seat per number in that range, in ascending `seat_number` order, each with `seat_status` `AVAILABLE`, a null `assigned_account_id` and an empty `scanned_game_ids` array."
    PRD 2.7: "`total_seat_count` is the number of seats whose `season_id` is this season."

    Design: Corner/entities/e_seat_bulk_create_mints_the_whole_range_and_lists_by_season
    """
    season = create_season()

    response = api_client.create_seats(
        create_seats_payload(season["id"], seat_number_from=1, seat_number_to=4),
        OPS_HEADERS,
    )
    seats = validate_success(response, 201)

    assert len(seats) == 4, f"Expected 4 minted seats, got {len(seats)}"
    assert [s["seat_number"] for s in seats] == [1, 2, 3, 4]
    for seat in seats:
        assert_seat(seat)
        assert seat["seat_status"] == "AVAILABLE"
        assert seat["assigned_account_id"] is None
        assert seat["scanned_game_ids"] == []

    listed, meta = validate_paginated(
        api_client.list_seats(OPS_HEADERS, params={"season_id": season["id"]})
    )
    assert meta["total_count"] == 4

    refreshed = read_season(season["id"])
    assert refreshed["total_seat_count"] == 4
    assert refreshed["available_seat_count"] == 4


def test_game_listing_paginates_with_total_count_and_has_more():
    """PRD 2.3: "The `meta` object of a list response carries `limit`, `offset`, `total_count` and `has_more`; `total_count` is the number of rows matching the filters before pagination is applied, and `has_more` is true exactly when rows remain beyond the current page."
    PRD 2.3: "Games may be filtered by `season_id` and by `game_status`."

    Design: Corner/entities/e_game_list_pagination_reports_total_count_and_has_more
    """
    season = create_season(total_home_games=3)
    create_game(season["id"], opponent_code="AAA")
    create_game(
        season["id"],
        opponent_code="BBB",
        opponent_tier="STANDARD",
        day_bucket="WEEKDAY",
        demand_index=50,
        game_date_utc="2026-10-20T23:00:00Z",
    )
    create_game(
        season["id"],
        opponent_code="CCC",
        opponent_tier="VALUE",
        day_bucket="WEEKDAY",
        demand_index=20,
        game_date_utc="2026-10-30T23:00:00Z",
    )

    first_page, first_meta = validate_paginated(
        api_client.list_games(
            RM_HEADERS, params={"season_id": season["id"], "limit": 2, "offset": 0}
        )
    )
    assert len(first_page) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0

    second_page, second_meta = validate_paginated(
        api_client.list_games(
            RM_HEADERS, params={"season_id": season["id"], "limit": 2, "offset": 2}
        )
    )
    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert second_meta["offset"] == 2


def test_service_rep_status_defaults_to_active():
    """PRD 3.2: "Service representatives are created by a `TicketOpsAdmin` with a `rep_name`, the `territory_code` they service, a `book_capacity` of at least 1, and an optional `rep_status` of `ACTIVE` or `ON_LEAVE` that defaults to `ACTIVE`."
    PRD 3.2: "A rep starts with `assigned_account_count` and `touchpoints_logged_count` at 0."

    Design: Corner/entities/e_service_rep_status_defaults_to_active
    """
    defaulted = create_rep(rep_name="Rep Default", book_capacity=3)
    on_leave = create_rep(rep_name="Rep Leave", book_capacity=3, rep_status="ON_LEAVE")

    assert_service_rep(defaulted)
    assert defaulted["rep_status"] == "ACTIVE"
    assert defaulted["assigned_account_count"] == 0
    assert defaulted["touchpoints_logged_count"] == 0
    assert on_leave["rep_status"] == "ON_LEAVE"


def test_seat_mint_with_unknown_price_zone_is_rejected():
    """PRD 2.9: "**Schema.** Required fields present, enum members valid, integers inside their declared ranges, ISO 8601 UTC timestamps parseable, `limit` inside 1 through 100, `offset` at least 0, `seat_ids` and `new_seat_ids` non-empty and free of duplicates, `installment_count` one of 1, 3 or 6, `hold_window_end_utc` strictly after `hold_window_start_utc`, and `service_window_end_utc` strictly after `service_window_start_utc` — otherwise `ERR_INVALID_REQUEST` (400). This applies to every endpoint."
    PRD 3.1: "The request names the `season_id`, the `section_code` and `row_label` being minted, the `price_zone` — one of `ZONE_A`, `ZONE_B`, `ZONE_C` or `ZONE_D` — and the inclusive numeric bounds `seat_number_from` and `seat_number_to`."

    Design: Corner/entities/e_seat_create_with_invalid_enum_price_zone_rejected
    """
    season = create_season()

    response = api_client.create_seats(
        create_seats_payload(season["id"], price_zone="ZONE_Z"), OPS_HEADERS
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    assert read_season(season["id"])["total_seat_count"] == 0


def test_partial_plan_derives_from_a_published_full_season_plan():
    """PRD 3.1: "Plan construction integrity is the rule that makes partial products derivable rather than arbitrary: a `FULL_SEASON` plan carries a null `base_plan_id` and its `game_ids` count must equal the season's `total_home_games`; every other plan type must carry a `base_plan_id` naming a plan that is `PUBLISHED`, lives in the same season, and whose `game_ids` are a superset of the new plan's `game_ids`, and the derived plan must include at least two games."
    PRD 3.1: "On creation the plan is `DRAFT` and its `included_game_count` is set to the number of ids in `game_ids`."
    PRD 2.3: "Season plans may be filtered by `season_id`, `base_plan_id` and `plan_status`."

    Design: Corner/entities/e_partial_plan_derives_from_a_published_full_season_base_plan
    """
    season = create_season(total_home_games=3)
    g1 = create_game(season["id"], opponent_code="AAA")
    g2 = create_game(
        season["id"],
        opponent_code="BBB",
        opponent_tier="STANDARD",
        day_bucket="WEEKDAY",
        demand_index=50,
        game_date_utc="2026-10-20T23:00:00Z",
    )
    g3 = create_game(
        season["id"],
        opponent_code="CCC",
        opponent_tier="VALUE",
        day_bucket="WEEKDAY",
        demand_index=20,
        game_date_utc="2026-10-30T23:00:00Z",
    )
    base_plan = create_published_plan(season["id"], [g1["id"], g2["id"], g3["id"]])

    response = api_client.create_season_plan(
        {
            "season_id": season["id"],
            "plan_type": "PARTIAL",
            "game_ids": [g1["id"], g3["id"]],
            "min_seats": 1,
            "max_seats": 4,
            "base_plan_id": base_plan["id"],
        },
        RM_HEADERS,
    )
    partial = validate_success(response, 201)

    assert_season_plan(partial)
    assert partial["plan_status"] == "DRAFT"
    assert partial["included_game_count"] == 2
    assert partial["base_plan_id"] == base_plan["id"]

    _, meta = validate_paginated(
        api_client.list_season_plans(RM_HEADERS, params={"base_plan_id": base_plan["id"]})
    )
    assert meta["total_count"] == 1


def test_partial_plan_without_a_base_plan_is_rejected():
    """PRD 3.1: "Plan construction integrity is the rule that makes partial products derivable rather than arbitrary: a `FULL_SEASON` plan carries a null `base_plan_id` and its `game_ids` count must equal the season's `total_home_games`; every other plan type must carry a `base_plan_id` naming a plan that is `PUBLISHED`, lives in the same season, and whose `game_ids` are a superset of the new plan's `game_ids`, and the derived plan must include at least two games. Any of those conditions failing is `ERR_PLAN_GAMES_NOT_SUBSET`."

    Design: Corner/validations/val_partial_plan_without_a_base_plan_rejected
    """
    season = create_season(total_home_games=2)
    g1 = create_game(season["id"], opponent_code="AAA")
    g2 = create_game(
        season["id"],
        opponent_code="BBB",
        opponent_tier="STANDARD",
        day_bucket="WEEKDAY",
        demand_index=50,
        game_date_utc="2026-10-20T23:00:00Z",
    )
    create_published_plan(season["id"], [g1["id"], g2["id"]])

    response = api_client.create_season_plan(
        {
            "season_id": season["id"],
            "plan_type": "PARTIAL",
            "game_ids": [g1["id"], g2["id"]],
            "min_seats": 1,
            "max_seats": 4,
        },
        RM_HEADERS,
    )

    validate_error(response, ApiErrorId.ERR_PLAN_GAMES_NOT_SUBSET.value, 422)
    _, meta = validate_paginated(
        api_client.list_season_plans(RM_HEADERS, params={"season_id": season["id"]})
    )
    assert meta["total_count"] == 1, "the rejected plan must not be stored"


def test_opening_the_renewal_window_twice_is_rejected():
    """PRD 2.9: "A selling operation attempted outside `RENEWAL_OPEN` or `GENERAL_ONSALE` is `ERR_SEASON_NOT_SELLING`; a setup operation attempted in the wrong status — including opening renewal from a status other than `PLANNING`, and hospitality booking while `PLANNING` or `ARCHIVED` — is `ERR_SEASON_STATE_INVALID`."
    PRD 3.3: "On success the season's `renewal_opened_at_utc` is stamped with the current instant, the seat census is recomputed, and the season's `version` increments by 1."

    Design: Corner/state_machines/sm_open_renewal_twice_returns_season_state_invalid
    """
    season = create_season()
    game = create_game(season["id"])
    create_published_plan(season["id"], [game["id"]])
    opened = open_renewal(season["id"])
    assert opened["season_status"] == "RENEWAL_OPEN"

    response = api_client.open_renewal(season["id"], OPS_HEADERS)

    validate_error(response, ApiErrorId.ERR_SEASON_STATE_INVALID.value, 409)
    unchanged = read_season(season["id"])
    assert unchanged["season_status"] == "RENEWAL_OPEN"
    assert unchanged["renewal_opened_at_utc"] == "2026-08-01T00:00:00.000Z"


def test_opening_the_renewal_window_without_a_published_plan_is_rejected():
    """PRD 3.3: "It has an admission test with three parts, all of which must hold: the season must currently be in `PLANNING`, the number of games created for the season must be exactly `total_home_games`, and at least one plan for the season must be `PUBLISHED`."
    PRD 3.3: "A game-count mismatch or the absence of a published plan is `ERR_SEASON_SETUP_INCOMPLETE`."

    Design: Corner/errors/err_open_renewal_without_a_published_plan_returns_setup_incomplete
    """
    season = create_season()
    game = create_game(season["id"])
    plan = create_plan(season["id"], [game["id"]])
    assert read_plan(plan["id"])["plan_status"] == "DRAFT"

    response = api_client.open_renewal(season["id"], OPS_HEADERS)

    validate_error(response, ApiErrorId.ERR_SEASON_SETUP_INCOMPLETE.value, 422)
    unchanged = read_season(season["id"])
    assert unchanged["season_status"] == "PLANNING"
    assert unchanged["renewal_opened_at_utc"] is None


def test_logical_clock_starts_at_the_declared_default_instant():
    """PRD 2.5: "The server maintains a logical clock in UTC. On every server start the clock is initialised to `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time."
    PRD 2.4: "Every persisted resource also carries `created_at`, the logical-clock instant at which the row was minted, formatted as an ISO 8601 UTC timestamp with exactly three fractional-second digits."

    Design: Corner/endpoints/ep_logical_clock_starts_at_the_declared_default_instant
    """
    _, meta = validate_paginated(api_client.list_games(OPS_HEADERS))
    assert meta["total_count"] == 0, "the database starts empty"

    season = create_season()

    assert season["created_at"] == "2026-08-01T00:00:00.000Z"
    assert season["updated_at"] == "2026-08-01T00:00:00.000Z"
    assert season["season_status"] == "PLANNING"


def test_seat_listing_filters_by_status_and_zone():
    """PRD 2.3: "Seats may be filtered by `season_id`, `assigned_account_id`, `seat_status` and `price_zone`."
    PRD 2.7: "The rule is a three-way decision evaluated in order: a seat whose `assigned_account_id` is not null is `ASSIGNED`; otherwise, a seat is `HELD` when some seat hold on that seat is in `ACTIVE` status and its occupation window covers the current instant — that is, the hold's `hold_window_start_utc` is at or before the current instant and its `hold_window_end_utc` is strictly after it, a half-open interval; otherwise the seat is `AVAILABLE`."

    Design: Corner/endpoints/ep_seat_list_filters_by_status_and_zone_together
    """
    from test_helpers import place_hold

    world = setup_selling_world(
        seat_ranges=[
            {"section_code": "104", "row_label": "A", "price_zone": "ZONE_C",
             "seat_number_from": 1, "seat_number_to": 2},
            {"section_code": "310", "row_label": "C", "price_zone": "ZONE_D",
             "seat_number_from": 1, "seat_number_to": 2},
        ],
        account={"account_type": "GROUP"},
    )
    zone_c_seat = world["seat_groups"][0][0]
    place_hold(
        zone_c_seat["id"],
        world["account_id"],
        world["rep_headers"],
        hold_type="GROUP_HOLD",
        hold_window_start_utc="2026-08-01T00:00:00Z",
        hold_window_end_utc="2026-09-01T00:00:00Z",
    )

    held_rows, held_meta = validate_paginated(
        api_client.list_seats(
            OPS_HEADERS, params={"season_id": world["season_id"], "seat_status": "HELD"}
        )
    )
    assert held_meta["total_count"] == 1
    assert held_rows[0]["id"] == zone_c_seat["id"]

    _, zone_meta = validate_paginated(
        api_client.list_seats(
            OPS_HEADERS, params={"season_id": world["season_id"], "price_zone": "ZONE_D"}
        )
    )
    assert zone_meta["total_count"] == 2

    season = read_season(world["season_id"])
    assert season["total_seat_count"] == 4
    assert season["held_seat_count"] == 1
    assert season["available_seat_count"] == 3

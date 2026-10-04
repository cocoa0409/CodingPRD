"""Foundations: resource creation defaults, envelope shape, existence, listing
pagination, payload validation, auth context, and site-approval gates."""
from test_helpers import (
    ApiErrorId,
    PA,
    RM,
    add_recipe,
    assert_order,
    assert_recipe,
    assert_region,
    assert_stand,
    create_loyalty_account,
    create_region,
    create_stand,
    create_stand_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_crew_member_headers,
    make_stand_operator_headers,
    setup_open_stand_with_menu,
    setup_stand_with_agreement,
    stand_version,
    validate_error,
    validate_paginated,
    validate_success,
)

GHOST_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


class TestRegionCreation:
    def test_region_create_returns_system_fields_and_initial_version(
        self, api, platform_admin_headers
    ):
        """PRD §2.4: "Every resource in the system — regions, stands, crew members,
        operator agreements, recipes, recipe distributions, loyalty accounts, shifts,
        shift assignments, orders, order items, payments, and throughput windows —
        carries a standard set of system-managed fields: `id` (string): a unique,
        server-minted identifier formatted as a UUID, with no type prefix."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
        the request that starts with `req_`."

        Design: Corner/entities/region_create_returns_system_fields_and_initial_version
        """
        resp = api.create_region({"name": "High Desert", "code": "HD"}, platform_admin_headers)
        body = resp.json()
        region = validate_success(resp, 201)
        assert_region(region)
        assert region["name"] == "High Desert"
        assert region["code"] == "HD"
        assert region["version"] == 1, f"new region must start at version 1, got {region['version']}"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"

    def test_region_create_round_trips_via_get(self, api, platform_admin_headers):
        """PRD §2.4: "`created_at` (string): an ISO 8601 UTC timestamp with three
        fractional digits recording when the resource was created."

        Design: Corner/entities/region_create_returns_system_fields_and_initial_version
        """
        region = create_region(name="High Desert", code="HD")
        fetched = validate_success(api.get_region(region["id"], platform_admin_headers), 200)
        assert fetched["id"] == region["id"]
        assert fetched["name"] == "High Desert"
        assert fetched["code"] == "HD"
        assert fetched["version"] == 1


class TestStandCreationDefaults:
    def test_stand_create_defaults_proposed_and_zero_breach_counter(
        self, api, platform_admin_headers
    ):
        """PRD §3.1: "The stand is born `PROPOSED` with `consecutive_breach_windows`
        at zero."

        Design: Corner/entities/stand_create_defaults_proposed_and_zero_breach_counter
        """
        region = create_region()
        resp = api.create_stand(
            create_stand_payload(
                region["id"],
                name="Corner Lot",
                lane_configs=[
                    {"lane_code": "A", "max_stack_cars": 5},
                    {"lane_code": "B", "max_stack_cars": 5},
                ],
            ),
            platform_admin_headers,
        )
        stand = validate_success(resp, 201)
        assert_stand(stand)
        assert stand["status"] == "PROPOSED"
        assert stand["consecutive_breach_windows"] == 0
        assert stand["lane_occupancy"] == {}, (
            f"no cars yet: lane_occupancy must be empty, got {stand['lane_occupancy']}"
        )

    def test_stand_create_defaults_visible_on_reread(self, api, platform_admin_headers):
        """PRD §3.1: "The stand is born `PROPOSED` with `consecutive_breach_windows`
        at zero."

        Design: Corner/entities/stand_create_defaults_proposed_and_zero_breach_counter
        """
        region = create_region()
        stand = create_stand(region["id"], name="Corner Lot")
        fetched = validate_success(api.get_stand(stand["id"], platform_admin_headers), 200)
        assert fetched["status"] == "PROPOSED"
        assert fetched["consecutive_breach_windows"] == 0
        assert fetched["lane_occupancy"] == {}


class TestLoyaltyAccountComputedFields:
    def test_loyalty_account_computed_tier_and_points_ignores_client_input(
        self, api, platform_admin_headers
    ):
        """PRD §3.4: "Accounts begin with `points` at zero and `tier` at `NONE`."
        PRD §3.4: "A `PlatformAdmin` enrolls a loyalty account with the holder's
        `full_name` and a `home_stand_id`."

        Design: Corner/entities/loyalty_account_computed_tier_and_points_ignores_client_input
        """
        ctx = setup_open_stand_with_menu()
        sneaky = api.create_loyalty_account(
            {
                "full_name": "Sneaky Sam",
                "home_stand_id": ctx["stand"]["id"],
                "points": 999,
                "tier": "GOLD",
            },
            platform_admin_headers,
        )
        validate_error(sneaky, ApiErrorId.ERR_INVALID_PAYLOAD, 400)
        honest = validate_success(
            api.create_loyalty_account(
                {"full_name": "Honest Hal", "home_stand_id": ctx["stand"]["id"]},
                platform_admin_headers,
            ),
            201,
        )
        assert honest["points"] == 0
        assert honest["tier"] == "NONE"

    def test_loyalty_account_computed_fields_start_at_zero_and_none(self, api):
        """PRD §3.4: "Accounts begin with `points` at zero and `tier` at `NONE`."

        Design: Corner/entities/loyalty_account_computed_tier_and_points_ignores_client_input
        """
        ctx = setup_open_stand_with_menu()
        account = create_loyalty_account(ctx["stand"]["id"], full_name="Honest Hal")
        fetched = validate_success(
            api.get_loyalty_account(account["id"], ctx["operator_headers"]), 200
        )
        assert fetched["points"] == 0
        assert fetched["tier"] == "NONE"
        assert fetched["lifetime_captured_cents"] == 0


class TestSeasonalRecipeShape:
    def test_recipe_seasonal_requires_season_window(self, api, platform_admin_headers):
        """PRD §3.3: "Seasonal recipes carry a `season_start` (inclusive) and a
        `season_end` (exclusive, and strictly after `season_start`); both are
        required exactly when the channel is `SEASONAL` and must be absent-shaped
        otherwise — malformed combinations fail payload validation with
        `ERR_INVALID_PAYLOAD`."

        Design: Corner/entities/recipe_seasonal_requires_season_window
        """
        base = {
            "base_price_cents": 525,
            "base_build_seconds": 70,
            "temperature_class": "HOT",
        }
        missing = api.create_recipe(
            {"name": "Pumpkin Cloud", "channel": "SEASONAL", **base},
            platform_admin_headers,
        )
        validate_error(missing, ApiErrorId.ERR_INVALID_PAYLOAD, 400)
        inverted = api.create_recipe(
            {
                "name": "Backwards Brew",
                "channel": "SEASONAL",
                "season_start": "2026-12-01",
                "season_end": "2026-09-01",
                **base,
            },
            platform_admin_headers,
        )
        validate_error(inverted, ApiErrorId.ERR_INVALID_PAYLOAD, 400)
        good = api.create_recipe(
            {
                "name": "Autumn Gold",
                "channel": "SEASONAL",
                "season_start": "2026-09-01",
                "season_end": "2026-12-01",
                **base,
            },
            platform_admin_headers,
        )
        recipe = validate_success(good, 201)
        assert_recipe(recipe)
        assert recipe["status"] == "ACTIVE"

    def test_recipe_seasonal_wellformed_window_accepted(self, api, platform_admin_headers):
        """PRD §3.3: "Recipes are born `ACTIVE`."

        Design: Corner/entities/recipe_seasonal_requires_season_window
        """
        resp = api.create_recipe(
            {
                "name": "Autumn Gold",
                "channel": "SEASONAL",
                "base_price_cents": 525,
                "base_build_seconds": 70,
                "temperature_class": "HOT",
                "season_start": "2026-09-01",
                "season_end": "2026-12-01",
            },
            platform_admin_headers,
        )
        recipe = validate_success(resp, 201)
        assert recipe["season_start"] == "2026-09-01"
        assert recipe["season_end"] == "2026-12-01"
        assert recipe["status"] == "ACTIVE"


class TestOrderRetrieval:
    def test_order_get_returns_all_three_status_dimensions(self, api):
        """PRD §3.6: "A `WINDOW` order is taken by a `CrewMember` or `ShiftLead`
        on a tablet ahead of the window: it requires a `lane_code` naming one of
        the stand's configured lanes, enters that lane immediately with
        `queue_status` `MERGED`, reserves a stacking slot, and receives its
        `lane_seq`."
        PRD §3.7: "an order's `payment_status` begins `UNPAID` and tracks its
        payment's own status throughout."

        Design: Corner/entities/order_get_returns_all_three_status_dimensions
        """
        ctx = setup_open_stand_with_menu()
        version = stand_version(ctx)
        resp = api.create_order(
            {
                "stand_id": ctx["stand"]["id"],
                "source": "WINDOW",
                "lane_code": "A",
                "items": [
                    {
                        "recipe_id": ctx["recipe"]["id"],
                        "quantity": 2,
                        "modifier_names": ["EXTRA_SHOT"],
                    }
                ],
                "expected_stand_version": version,
            },
            make_crew_member_headers(ctx["taker"]["id"]),
        )
        created = validate_success(resp, 201)
        order = validate_success(
            api.get_order(created["id"], make_crew_member_headers(ctx["taker"]["id"])), 200
        )
        assert_order(order)
        assert order["queue_status"] == "MERGED"
        assert order["payment_status"] == "UNPAID"
        assert order["build_status"] == "QUEUED"
        assert order["lane_code"] == "A"
        assert order["lane_seq"] == 1
        assert order["subtotal_cents"] == 1000, (
            f"(450+50)*2 = 1000, got {order['subtotal_cents']}"
        )
        assert order["discount_cents"] == 0
        assert order["total_cents"] == 1000
        assert order["outstanding_build_seconds"] == 70, (
            f"60+10 at default staffing must give 70, got {order['outstanding_build_seconds']}"
        )

    def test_order_get_round_trips_created_order(self, api):
        """PRD §3.6: "Every item is born `PENDING`, and the order's `build_status`
        begins `QUEUED`."

        Design: Corner/entities/order_get_returns_all_three_status_dimensions
        """
        from test_helpers import place_window_order

        ctx = setup_open_stand_with_menu()
        created = place_window_order(ctx, ctx["recipe"]["id"])
        order = validate_success(
            api.get_order(created["id"], make_crew_member_headers(ctx["taker"]["id"])), 200
        )
        assert order["id"] == created["id"]
        assert order["stand_id"] == ctx["stand"]["id"]
        assert order["source"] == "WINDOW"
        assert order["queue_status"] == "MERGED"
        assert order["build_status"] == "QUEUED"


class TestStandListingPagination:
    def test_stands_list_paginates_with_total_count_and_has_more(
        self, api, regional_manager_headers
    ):
        """PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the response envelope."

        Design: Corner/entities/stands_list_paginates_with_total_count_and_has_more
        """
        region = create_region()
        for name in ("S1", "S2", "S3"):
            create_stand(region["id"], name=name)

        page1, meta1 = validate_paginated(
            api.list_stands(
                regional_manager_headers,
                params={"region_id": region["id"], "limit": 2, "offset": 0},
            )
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_stands(
                regional_manager_headers,
                params={"region_id": region["id"], "limit": 2, "offset": 2},
            )
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_stands_list_second_page_carries_same_total_count(
        self, api, regional_manager_headers
    ):
        """PRD §2.3: "The `offset` parameter skips that many items from the front
        of the result set and defaults to 0."

        Design: Corner/entities/stands_list_paginates_with_total_count_and_has_more
        """
        region = create_region()
        created = [create_stand(region["id"], name=f"S{i}") for i in range(3)]
        page1, _ = validate_paginated(
            api.list_stands(
                regional_manager_headers,
                params={"region_id": region["id"], "limit": 2, "offset": 0},
            )
        )
        page2, _ = validate_paginated(
            api.list_stands(
                regional_manager_headers,
                params={"region_id": region["id"], "limit": 2, "offset": 2},
            )
        )
        seen_ids = {row["id"] for row in page1 + page2}
        assert seen_ids == {s["id"] for s in created}, (
            "two pages must cover exactly the three stands with no overlap"
        )


class TestExistenceAndAuthContext:
    def test_nonexistent_stand_get_returns_404(self, api, platform_admin_headers):
        """PRD §2.6: "The system confirms the existence of each path identifier in
        order — region, stand, crew member, agreement, recipe, distribution, account,
        shift, assignment, order, item, payment, window — and rejects the request
        immediately with the `404 Not Found` error corresponding to the first
        identifier that does not exist."

        Design: Corner/entities/nonexistent_stand_get_returns_404
        """
        resp = api.get_stand(GHOST_ID, platform_admin_headers)
        body = resp.json()
        validate_error(resp, ApiErrorId.ERR_STAND_NOT_FOUND, 404)
        assert body["response_type"] == "error"
        assert body["meta"]["api_request_id"].startswith("req_")

    def test_missing_auth_headers_rejected_on_any_endpoint(self, api):
        """PRD §2.1: "A request in which either header is missing or empty is
        rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."
        PRD §2.9: "**Authentication context** — presence and non-emptiness of
        `X-User-ID` and `X-User-Role` (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`)."

        Design: Corner/errors/missing_auth_headers_rejected_on_any_endpoint
        """
        # No auth headers at all — even against a non-existent resource id,
        # the auth check (priority 1) fires before existence (priority 3).
        resp = api.get_stand(GHOST_ID, headers={"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)

    def test_missing_auth_headers_rejected_before_existence_check(self, api):
        """PRD §2.9: "When a single request could trip several rules, the system
        evaluates checks in a fixed priority order so that the surfaced error is
        deterministic: 1. **Authentication context** ..."

        Design: Corner/errors/missing_auth_headers_rejected_on_any_endpoint
        """
        resp = api.get_stand(GHOST_ID, headers={"X-User-Role": "PlatformAdmin"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)


class TestOrderPayloadValidation:
    def test_order_missing_required_source_field_rejected(self, api):
        """PRD §2.9: "**Payload shape** — required fields, types, enum membership,
        well-formed lane configurations, a revenue share strictly between zero and
        one, and a valid season window on seasonal recipes (`ERR_INVALID_PAYLOAD`)."

        Design: Corner/entities/order_missing_required_source_field_rejected
        """
        ctx = setup_open_stand_with_menu()
        version = stand_version(ctx)
        resp = api.create_order(
            {
                "stand_id": ctx["stand"]["id"],
                "lane_code": "A",
                "items": [
                    {"recipe_id": ctx["recipe"]["id"], "quantity": 1, "modifier_names": []}
                ],
                "expected_stand_version": version,
            },
            make_crew_member_headers(ctx["taker"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PAYLOAD, 400)

    def test_order_quantity_zero_rejected(self, api):
        """PRD §3.6: "Each item in the `items` array names a `recipe_id`, a
        `quantity` of at least one (`ERR_INVALID_QUANTITY`), and optionally
        `modifier_names`, a subset of the names declared on the recipe."

        Design: Corner/entities/order_quantity_zero_rejected
        """
        ctx = setup_open_stand_with_menu()
        version = stand_version(ctx)
        resp = api.create_order(
            {
                "stand_id": ctx["stand"]["id"],
                "source": "WINDOW",
                "lane_code": "A",
                "items": [
                    {"recipe_id": ctx["recipe"]["id"], "quantity": 0, "modifier_names": []}
                ],
                "expected_stand_version": version,
            },
            make_crew_member_headers(ctx["taker"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_QUANTITY, 422)

    def test_unknown_modifier_name_rejected(self, api):
        """PRD §3.6: "optionally `modifier_names`, a subset of the names declared
        on the recipe — any unknown name is rejected with `ERR_MODIFIER_UNKNOWN`."

        Design: Corner/errors/unknown_modifier_name_rejected
        """
        ctx = setup_open_stand_with_menu()
        version = stand_version(ctx)
        resp = api.create_order(
            {
                "stand_id": ctx["stand"]["id"],
                "source": "WINDOW",
                "lane_code": "A",
                "items": [
                    {
                        "recipe_id": ctx["recipe"]["id"],
                        "quantity": 1,
                        "modifier_names": ["OAT_MILK"],
                    }
                ],
                "expected_stand_version": version,
            },
            make_crew_member_headers(ctx["taker"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MODIFIER_UNKNOWN, 422)


class TestSiteApprovalGates:
    def test_site_approval_enforces_stacking_and_ingress(self, api, platform_admin_headers):
        """PRD §3.1: "Site approval by a `PlatformAdmin` enforces two hard
        real-estate constraints, and both must hold: the sum of `max_stack_cars`
        across the stand's lane configurations must be at least ten cars (otherwise
        `ERR_SITE_STACKING_INSUFFICIENT`), and `min_ingress_gap_seconds` must be at
        least thirty seconds (otherwise `ERR_INGRESS_GAP_INSUFFICIENT`)."

        Design: Corner/validations/site_approval_enforces_stacking_and_ingress
        """
        region = create_region()
        tiny = create_stand(
            region["id"],
            name="Tiny",
            lane_configs=[
                {"lane_code": "A", "max_stack_cars": 4},
                {"lane_code": "B", "max_stack_cars": 4},
            ],
        )
        cramped = create_stand(
            region["id"], name="Cramped Entry", min_ingress_gap_seconds=20
        )
        good = create_stand(region["id"], name="Compliant", min_ingress_gap_seconds=30)

        resp_tiny = api.approve_stand(tiny["id"], platform_admin_headers)
        validate_error(resp_tiny, ApiErrorId.ERR_SITE_STACKING_INSUFFICIENT, 422)

        resp_cramped = api.approve_stand(cramped["id"], platform_admin_headers)
        validate_error(resp_cramped, ApiErrorId.ERR_INGRESS_GAP_INSUFFICIENT, 422)

        approved = validate_success(api.approve_stand(good["id"], platform_admin_headers), 200)
        assert approved["status"] == "APPROVED"

    def test_site_approval_minimum_boundaries_are_inclusive(
        self, api, platform_admin_headers
    ):
        """PRD §3.1: "the sum of `max_stack_cars` across the stand's lane
        configurations must be at least ten cars (otherwise
        `ERR_SITE_STACKING_INSUFFICIENT`), and `min_ingress_gap_seconds` must be at
        least thirty seconds (otherwise `ERR_INGRESS_GAP_INSUFFICIENT`)."

        Design: Corner/validations/site_approval_enforces_stacking_and_ingress
        """
        region = create_region()
        boundary = create_stand(
            region["id"],
            name="Boundary",
            min_ingress_gap_seconds=30,
            lane_configs=[
                {"lane_code": "A", "max_stack_cars": 5},
                {"lane_code": "B", "max_stack_cars": 5},
            ],
        )
        approved = validate_success(api.approve_stand(boundary["id"], platform_admin_headers), 200)
        assert approved["status"] == "APPROVED", (
            "stacking 10 and ingress 30 are the inclusive minimums and must approve"
        )


class TestInitialStates:
    def test_initial_states_on_creation(self, api):
        """PRD §3.6: "A `LOYALTY_APP` order is placed by a `LoyaltyCustomer`
        against their own account: it requires `loyalty_account_id`, ignores any
        `lane_code`, and starts `QUEUED`, outside the lanes, waiting to be merged
        on arrival."
        PRD §3.3: "A `PlatformAdmin` stages a `RecipeDistribution` pairing a
        `recipe_id` with a `stand_id` (born `STAGED`)"
        PRD §3.5: "A `StandOperator` creates a shift for a stand with `starts_at`,
        `ends_at`, and an `is_peak` flag; the shift is born `DRAFT`."

        Design: Corner/state_machines/initial_states_on_creation
        """
        ctx = setup_open_stand_with_menu()
        account = create_loyalty_account(ctx["stand"]["id"], full_name="Init Ivy")

        # The distribution from the boot chain was ACTIVATED; stage a fresh one
        # to observe the STAGED birth state on a second recipe.
        recipe2, dist2 = add_recipe(ctx, activate=False, name="Decaf Dusk")
        assert dist2["status"] == "STAGED"

        version = stand_version(ctx)
        resp = api.create_order(
            {
                "stand_id": ctx["stand"]["id"],
                "source": "LOYALTY_APP",
                "loyalty_account_id": account["id"],
                "items": [
                    {"recipe_id": ctx["recipe"]["id"], "quantity": 1, "modifier_names": []}
                ],
                "expected_stand_version": version,
            },
            {"X-User-ID": account["id"], "X-User-Role": "LoyaltyCustomer"},
        )
        order = validate_success(resp, 201)
        assert order["queue_status"] == "QUEUED"
        assert order["lane_code"] is None
        assert order["lane_seq"] is None

        shift = validate_success(
            api.create_shift(
                {
                    "stand_id": ctx["stand"]["id"],
                    "starts_at": "2026-09-02T07:00:00Z",
                    "ends_at": "2026-09-02T09:00:00Z",
                    "is_peak": False,
                },
                ctx["operator_headers"],
            ),
            201,
        )
        assert shift["status"] == "DRAFT"

    def test_app_order_starts_queued_outside_lanes(self, api):
        """PRD §3.6: "it requires `loyalty_account_id`, ignores any `lane_code`,
        and starts `QUEUED`, outside the lanes, waiting to be merged on arrival."

        Design: Corner/state_machines/initial_states_on_creation
        """
        from test_helpers import make_loyalty_customer_headers, place_app_order

        ctx = setup_open_stand_with_menu()
        account = create_loyalty_account(ctx["stand"]["id"], full_name="Init Ivy")
        order = place_app_order(ctx, ctx["recipe"]["id"], account["id"])
        assert order["queue_status"] == "QUEUED"
        fetched = validate_success(
            api.get_order(order["id"], make_loyalty_customer_headers(account["id"])), 200
        )
        assert fetched["queue_status"] == "QUEUED"
        assert fetched["lane_code"] is None


class TestLogicalClock:
    def test_logical_clock_default_and_set_drive_time_rules(self, api):
        """PRD §2.4: "At server startup, before any request has been processed,
        the logical clock reads exactly `2026-09-01T00:00:00Z`."
        PRD §3.5: "The `starts_at` must lie after the current logical clock at
        creation (`ERR_SHIFT_IN_PAST`)"

        Design: Corner/cross_cutting_complexity_layers/logical_clock_default_and_set_drive_time_rules
        """
        # No clock-set call: default clock is 2026-09-01T00:00:00Z.
        ctx = setup_open_stand_with_menu(clock="2026-09-01T00:00:00Z")
        early = api.create_shift(
            {
                "stand_id": ctx["stand"]["id"],
                "starts_at": "2026-08-31T07:00:00Z",
                "ends_at": "2026-08-31T09:00:00Z",
                "is_peak": False,
            },
            ctx["operator_headers"],
        )
        validate_error(early, ApiErrorId.ERR_SHIFT_IN_PAST, 422)

        from test_helpers import set_clock

        set_clock("2026-08-30T00:00:00Z")
        ok = validate_success(
            api.create_shift(
                {
                    "stand_id": ctx["stand"]["id"],
                    "starts_at": "2026-08-31T07:00:00Z",
                    "ends_at": "2026-08-31T09:00:00Z",
                    "is_peak": False,
                },
                ctx["operator_headers"],
            ),
            201,
        )
        assert ok["status"] == "DRAFT", (
            "after moving the clock back, the same payload must succeed"
        )

    def test_clock_set_returns_resulting_current_utc(self, api, platform_admin_headers):
        """PRD §2.4: "A `PlatformAdmin` may advance it by supplying a `to_iso8601`
        instant; the server responds with the resulting `current_utc`."

        Design: Corner/cross_cutting_complexity_layers/logical_clock_default_and_set_drive_time_rules
        """
        resp = api.set_clock("2026-08-30T00:00:00Z", platform_admin_headers)
        data = validate_success(resp, 200)
        assert data["current_utc"] == "2026-08-30T00:00:00Z"


class TestOrderCreateImmediateConsistency:
    def test_order_create_response_reflects_all_writes_immediately(self, api):
        """PRD §3.6: "The snapshot price, `unit_price_cents`, is the recipe's
        `base_price_cents` plus the `price_cents` of every chosen modifier"

        Design: Corner/consistency_model/order_create_response_reflects_all_writes_immediately
        """
        ctx = setup_open_stand_with_menu()
        version = stand_version(ctx)
        resp = api.create_order(
            {
                "stand_id": ctx["stand"]["id"],
                "source": "WINDOW",
                "lane_code": "A",
                "items": [
                    {
                        "recipe_id": ctx["recipe"]["id"],
                        "quantity": 1,
                        "modifier_names": ["EXTRA_SHOT"],
                    }
                ],
                "expected_stand_version": version,
            },
            make_crew_member_headers(ctx["taker"]["id"]),
        )
        order = validate_success(resp, 201)
        # No follow-up GET: the create response itself must carry every write.
        assert order["total_cents"] == 500, f"450+50 must total 500, got {order['total_cents']}"
        assert order["lane_seq"] == 1
        assert order["queue_status"] == "MERGED"
        assert order["payment_status"] == "UNPAID"
        assert order["build_status"] == "QUEUED"

    def test_order_create_response_carries_lane_and_status_dimensions(self, api):
        """PRD §3.6: "enters that lane immediately with `queue_status` `MERGED`,
        reserves a stacking slot, and receives its `lane_seq` — the per-lane
        monotonic sequence assigned as one more than the highest `lane_seq` ever
        assigned in that lane, or one for the lane's first order."

        Design: Corner/consistency_model/order_create_response_reflects_all_writes_immediately
        """
        ctx = setup_open_stand_with_menu()
        version = stand_version(ctx)
        order = validate_success(
            api.create_order(
                {
                    "stand_id": ctx["stand"]["id"],
                    "source": "WINDOW",
                    "lane_code": "A",
                    "items": [
                        {"recipe_id": ctx["recipe"]["id"], "quantity": 1, "modifier_names": []}
                    ],
                    "expected_stand_version": version,
                },
                make_crew_member_headers(ctx["taker"]["id"]),
            ),
            201,
        )
        assert order["lane_code"] == "A"
        assert order["lane_seq"] == 1
        assert order["queue_status"] == "MERGED"

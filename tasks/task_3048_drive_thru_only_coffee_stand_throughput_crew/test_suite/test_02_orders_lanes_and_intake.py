"""Order intake: stand posture gating, lane stacking capacity, lane-merge
selector ranking/tie-breaks, lane occupancy bookkeeping, and OCC on creates."""
from test_helpers import (
    ApiErrorId,
    add_recipe,
    build_item_ready,
    capture_order_payment,
    create_loyalty_account,
    list_items_of_order,
    make_crew_member_headers,
    make_loyalty_customer_headers,
    make_shift_lead_headers,
    make_stand_operator_headers,
    place_app_order,
    place_window_order,
    serve_window_order,
    setup_open_stand_with_menu,
    stand_version,
    validate_error,
    validate_success,
)


class TestStandPostureGating:
    def test_app_order_gated_on_stand_posture_but_window_order_passes_throttled(
        self, api
    ):
        """PRD §2.5: "While it is `THROTTLED`, only window orders are accepted and
        new app-ahead orders are rejected; merging an already-placed app order into
        a lane remains possible in either `OPEN` or `THROTTLED` posture."
        PRD §2.5: "Order intake of either kind against a stand whose posture forbids
        it is rejected with `ERR_STAND_NOT_ACCEPTING_ORDERS`."

        Design: Difficulty/cross_entity_state_dependency/app_order_gated_on_stand_posture_but_window_order_passes_throttled
        """
        ctx = setup_open_stand_with_menu()
        account = create_loyalty_account(ctx["stand"]["id"], full_name="App Amy")
        lead = make_shift_lead_headers(ctx["lead"]["id"])
        validate_success(api.throttle_stand(ctx["stand"]["id"], lead), 200)
        ctx["stand"] = validate_success(
            api.get_stand(ctx["stand"]["id"], ctx["operator_headers"]), 200
        )
        assert ctx["stand"]["status"] == "THROTTLED"
        version = ctx["stand"]["version"]

        app_resp = api.create_order(
            {
                "stand_id": ctx["stand"]["id"],
                "source": "LOYALTY_APP",
                "loyalty_account_id": account["id"],
                "items": [
                    {"recipe_id": ctx["recipe"]["id"], "quantity": 1, "modifier_names": []}
                ],
                "expected_stand_version": version,
            },
            make_loyalty_customer_headers(account["id"]),
        )
        validate_error(app_resp, ApiErrorId.ERR_STAND_NOT_ACCEPTING_ORDERS, 409)

        window_resp = api.create_order(
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
        )
        window_order = validate_success(window_resp, 201)
        assert window_order["queue_status"] == "MERGED"

    def test_throttled_stand_still_accepts_window_orders(self, api):
        """PRD §2.5: "While a stand is `OPEN`, both window-tablet orders and
        loyalty app-ahead orders are accepted. While it is `THROTTLED`, only
        window orders are accepted and new app-ahead orders are rejected."

        Design: Difficulty/cross_entity_state_dependency/app_order_gated_on_stand_posture_but_window_order_passes_throttled
        """
        ctx = setup_open_stand_with_menu()
        lead = make_shift_lead_headers(ctx["lead"]["id"])
        validate_success(api.throttle_stand(ctx["stand"]["id"], lead), 200)
        order = place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        assert order["queue_status"] == "MERGED"
        stand = validate_success(
            api.get_stand(ctx["stand"]["id"], ctx["operator_headers"]), 200
        )
        assert stand["status"] == "THROTTLED"


class TestEmptyOrderBoundary:
    def test_order_with_empty_items_array_rejected(self, api):
        """PRD §3.6: "Either way, the create payload carries the `stand_id` and a
        non-empty `items` array (an empty array is `ERR_EMPTY_ORDER`)"

        Design: Difficulty/boundary_precision_check/order_with_empty_items_array_rejected
        """
        ctx = setup_open_stand_with_menu()
        version = stand_version(ctx)
        resp = api.create_order(
            {
                "stand_id": ctx["stand"]["id"],
                "source": "WINDOW",
                "lane_code": "A",
                "items": [],
                "expected_stand_version": version,
            },
            make_crew_member_headers(ctx["taker"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_EMPTY_ORDER, 422)
        stand = validate_success(
            api.get_stand(ctx["stand"]["id"], ctx["operator_headers"]), 200
        )
        assert stand["version"] == version, (
            "a rejected create must not bump the stand's version"
        )

    def test_empty_items_rejection_creates_no_order(self, api):
        """PRD §3.6: "an empty array is `ERR_EMPTY_ORDER`"

        Design: Difficulty/boundary_precision_check/order_with_empty_items_array_rejected
        """
        from test_helpers import validate_paginated

        ctx = setup_open_stand_with_menu()
        version = stand_version(ctx)
        resp = api.create_order(
            {
                "stand_id": ctx["stand"]["id"],
                "source": "WINDOW",
                "lane_code": "A",
                "items": [],
                "expected_stand_version": version,
            },
            make_crew_member_headers(ctx["taker"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_EMPTY_ORDER, 422)
        orders, meta = validate_paginated(
            api.list_orders(
                ctx["operator_headers"], params={"stand_id": ctx["stand"]["id"]}
            )
        )
        assert orders == [], "no order may be created by a rejected payload"


class TestPerLineDiscountRounding:
    def test_order_total_rounds_discount_per_line_then_sums(self, api):
        """PRD §2.8: "Rounding order matters and is pinned: per-line loyalty
        discounts are rounded half-up per line item first, and only then summed
        into the order-level discount — computing the discount on the summed gross
        is a rejected variant because it diverges by a cent whenever two lines'
        fractional parts straddle a half-cent boundary."
        PRD §3.4: "at least 500 points earns `GOLD` (a ten-percent line discount)"

        Design: Difficulty/combinatorial_formula/order_total_rounds_discount_per_line_then_sums
        """
        ctx = setup_open_stand_with_menu()
        recipe, dist = add_recipe(
            ctx,
            name="Penny Split",
            base_price_cents=333,
            base_build_seconds=30,
            temperature_class="HOT",
        )
        account = create_loyalty_account(ctx["stand"]["id"], full_name="Goldie")
        validate_success(
            api.adjust_points(
                account["id"], {"delta_points": 500, "reason": "goodwill"},
                headers={"X-User-ID": "pa-1", "X-User-Role": "PlatformAdmin"},
            ),
            200,
        )
        version = stand_version(ctx)
        resp = api.create_order(
            {
                "stand_id": ctx["stand"]["id"],
                "source": "WINDOW",
                "lane_code": "A",
                "loyalty_account_id": account["id"],
                "items": [
                    {"recipe_id": recipe["id"], "quantity": 1, "modifier_names": []},
                    {"recipe_id": recipe["id"], "quantity": 1, "modifier_names": []},
                ],
                "expected_stand_version": version,
            },
            make_crew_member_headers(ctx["taker"]["id"]),
        )
        order = validate_success(resp, 201)
        assert order["subtotal_cents"] == 666
        assert order["discount_cents"] == 66, (
            f"per-line round_half_up(33.3)=33 each, summed 66; got {order['discount_cents']}"
        )
        assert order["total_cents"] == 600, (
            f"aggregate-then-round would give 599; pinned order gives 600, got {order['total_cents']}"
        )

    def test_per_line_rounding_visible_on_each_item(self, api):
        """PRD §3.6: "The loyalty discount is computed **per line, rounded first**:
        `line_discount_cents` is the line gross multiplied by the account's tier
        percentage — ten percent for `GOLD`, five percent for `SILVER`, zero
        otherwise and always zero when the order has no loyalty account — rounded
        half-up to a whole cent"

        Design: Difficulty/combinatorial_formula/order_total_rounds_discount_per_line_then_sums
        """
        ctx = setup_open_stand_with_menu()
        recipe, dist = add_recipe(
            ctx,
            name="Penny Split",
            base_price_cents=333,
            base_build_seconds=30,
            temperature_class="HOT",
        )
        account = create_loyalty_account(ctx["stand"]["id"], full_name="Goldie")
        validate_success(
            api.adjust_points(account["id"], {"delta_points": 500, "reason": "goodwill"},
                              headers={"X-User-ID": "pa-1", "X-User-Role": "PlatformAdmin"}),
            200,
        )
        order = place_window_order(
            ctx,
            recipe["id"],
            items=[
                {"recipe_id": recipe["id"], "quantity": 1, "modifier_names": []},
                {"recipe_id": recipe["id"], "quantity": 1, "modifier_names": []},
            ],
            loyalty_account_id=account["id"],
        )
        items = list_items_of_order(ctx, order["id"])
        assert len(items) == 2
        for item in items:
            assert item["line_gross_cents"] == 333
            assert item["line_discount_cents"] == 33, (
                f"round_half_up(333*0.10)=round_half_up(33.3)=33, got {item['line_discount_cents']}"
            )
            assert item["line_net_cents"] == 300


class TestBuildTimeFormula:
    def test_build_time_combines_recipe_modifier_class_and_staffing_multiplier(
        self, api
    ):
        """PRD §3.6: "That base is then scaled by bar staffing at the current
        logical clock: count the crew with role `BAR` whose assignment status is
        `CHECKED_IN` on the stand's `IN_PROGRESS` shift — if no shift is in
        progress, treat the count as two. With three or more on bar the multiplier
        is eight-tenths; with exactly two it is one; with fewer than two it is
        thirteen-tenths."
        PRD §3.6: "a `BLENDED` drink adds fifteen seconds on top."

        Design: Difficulty/combinatorial_formula/build_time_combines_recipe_modifier_class_and_staffing_multiplier
        """
        from test_helpers import (
            add_assignment,
            create_draft_shift,
            set_clock,
            setup_in_progress_shift,
        )

        ctx = setup_open_stand_with_menu()
        recipe, dist = add_recipe(
            ctx,
            name="Frost",
            base_price_cents=500,
            base_build_seconds=90,
            temperature_class="BLENDED",
            modifiers=[{"name": "WHIP", "price_cents": 25, "build_seconds_adder": 10}],
        )

        # Order 1: no IN_PROGRESS shift -> crew_on_bar defaults to 2 -> x1.0
        order1 = place_window_order(
            ctx,
            recipe["id"],
            items=[{"recipe_id": recipe["id"], "quantity": 1, "modifier_names": ["WHIP"]}],
        )
        item1 = list_items_of_order(ctx, order1["id"])[0]
        assert item1["build_time_seconds"] == 115, (
            f"(90 + 10 + 15) * 1.0 = 115 at default staffing, got {item1['build_time_seconds']}"
        )

        # Shift IN_PROGRESS with exactly one CHECKED_IN BAR crew -> x1.3
        shift, assignments = setup_in_progress_shift(ctx, [(ctx["lead"], "BAR")])
        validate_success(
            api.check_in_assignment(
                assignments[0]["id"], make_crew_member_headers(ctx["lead"]["id"])
            ),
            200,
        )
        order2 = place_window_order(
            ctx,
            recipe["id"],
            lane_code="B",
            items=[{"recipe_id": recipe["id"], "quantity": 1, "modifier_names": ["WHIP"]}],
        )
        item2 = list_items_of_order(ctx, order2["id"])[0]
        assert item2["build_time_seconds"] == 150, (
            f"round_half_up(115 * 1.3) = round_half_up(149.5) = 150, got {item2['build_time_seconds']}"
        )

    def test_build_time_defaults_to_neutral_multiplier_without_active_shift(self, api):
        """PRD §3.6: "if no shift is in progress, treat the count as two. With
        three or more on bar the multiplier is eight-tenths; with exactly two it
        is one; with fewer than two it is thirteen-tenths."

        Design: Difficulty/combinatorial_formula/build_time_combines_recipe_modifier_class_and_staffing_multiplier
        """
        ctx = setup_open_stand_with_menu()
        recipe, dist = add_recipe(
            ctx,
            name="Frost",
            base_price_cents=500,
            base_build_seconds=90,
            temperature_class="BLENDED",
            modifiers=[{"name": "WHIP", "price_cents": 25, "build_seconds_adder": 10}],
        )
        order = place_window_order(
            ctx,
            recipe["id"],
            items=[{"recipe_id": recipe["id"], "quantity": 1, "modifier_names": ["WHIP"]}],
        )
        item = list_items_of_order(ctx, order["id"])[0]
        assert item["build_time_seconds"] == 115, (
            f"with no IN_PROGRESS shift the multiplier is 1.0: 115, got {item['build_time_seconds']}"
        )
        assert item["unit_price_cents"] == 525, (
            f"500 + 25 modifier = 525, got {item['unit_price_cents']}"
        )

    def test_build_time_cap_and_fast_crew_branches(self, api):
        """PRD §3.6: "With three or more on bar the multiplier is eight-tenths;
        with exactly two it is one; with fewer than two it is thirteen-tenths. The
        product of base and multiplier is rounded half-up to a whole second, and
        the result is capped at 240 seconds."

        Design: Corner/calculations/build_time_cap_and_fast_crew_branches
        """
        from test_helpers import setup_in_progress_shift

        ctx = setup_open_stand_with_menu()
        frost, dist_f = add_recipe(
            ctx,
            name="Frost",
            base_price_cents=500,
            base_build_seconds=90,
            temperature_class="BLENDED",
            modifiers=[{"name": "WHIP", "price_cents": 25, "build_seconds_adder": 10}],
        )
        slow, dist_s = add_recipe(
            ctx,
            name="Slow Drip",
            base_price_cents=300,
            base_build_seconds=300,
            temperature_class="HOT",
        )
        shift, assignments = setup_in_progress_shift(
            ctx, [(ctx["op"], "BAR"), (ctx["taker"], "BAR"), (ctx["lead"], "BAR")]
        )
        for assignment, crew in zip(assignments, (ctx["op"], ctx["taker"], ctx["lead"])):
            validate_success(
                api.check_in_assignment(
                    assignment["id"], make_crew_member_headers(crew["id"])
                ),
                200,
            )
        order = place_window_order(
            ctx,
            frost["id"],
            items=[
                {"recipe_id": frost["id"], "quantity": 1, "modifier_names": ["WHIP"]},
                {"recipe_id": slow["id"], "quantity": 1, "modifier_names": []},
            ],
        )
        items = list_items_of_order(ctx, order["id"])
        by_recipe = {item["recipe_id"]: item for item in items}
        frost_item = by_recipe[frost["id"]]
        slow_item = by_recipe[slow["id"]]
        assert frost_item["build_time_seconds"] == 92, (
            f"round_half_up(115 * 0.8) = 92 with 3 BAR crew, got {frost_item['build_time_seconds']}"
        )
        assert slow_item["build_time_seconds"] == 240, (
            f"min(240, round_half_up(300 * 0.8)) = 240 (cap binds), got {slow_item['build_time_seconds']}"
        )
        refreshed = validate_success(
            api.get_order(order["id"], make_crew_member_headers(ctx["taker"]["id"])), 200
        )
        assert refreshed["outstanding_build_seconds"] == 332


class TestLaneMergeSelector:
    def test_lane_selector_tie_break_and_ranking(self, api):
        """PRD §3.6: "The selector considers only lanes with a free stacking slot
        — those whose occupied count (orders in the lane with `queue_status` of
        `MERGED` or `AT_WINDOW`) is below that lane's `max_stack_cars` — ranks
        eligible lanes by ascending projected clear time (the sum of
        `outstanding_build_seconds` over the lane's `MERGED` and `AT_WINDOW`
        orders), breaks ties toward the lane with fewer occupied slots, and breaks
        remaining ties by `lane_code` in ascending lexicographic order."

        Design: Corner/calculations/lane_selector_tie_break_and_ranking
        """
        ctx = setup_open_stand_with_menu()
        acct1 = create_loyalty_account(ctx["stand"]["id"], full_name="App One")
        acct2 = create_loyalty_account(ctx["stand"]["id"], full_name="App Two")
        order1 = place_app_order(ctx, ctx["recipe"]["id"], acct1["id"])
        order2 = place_app_order(ctx, ctx["recipe"]["id"], acct2["id"])

        merged1 = validate_success(
            api.merge_order(
                order1["id"],
                {"expected_stand_version": stand_version(ctx)},
                make_loyalty_customer_headers(acct1["id"]),
            ),
            200,
        )
        assert merged1["lane_code"] == "A", (
            f"empty-pool tie breaks by lane_code ascending, got {merged1['lane_code']}"
        )
        assert merged1["lane_seq"] == 1

        merged2 = validate_success(
            api.merge_order(
                order2["id"],
                {"expected_stand_version": stand_version(ctx)},
                make_loyalty_customer_headers(acct2["id"]),
            ),
            200,
        )
        assert merged2["lane_code"] == "B", (
            f"lane A carries 60s projected clear vs B's 0; ranking beats tie-break, got {merged2['lane_code']}"
        )
        assert merged2["lane_seq"] == 1, "each lane sequences independently"

    def test_selector_ranks_by_projected_clear_time_before_ties(self, api):
        """PRD §3.6: "ranks eligible lanes by ascending projected clear time (the
        sum of `outstanding_build_seconds` over the lane's `MERGED` and
        `AT_WINDOW` orders), breaks ties toward the lane with fewer occupied
        slots, and breaks remaining ties by `lane_code` in ascending lexicographic
        order."

        Design: Corner/calculations/lane_selector_tie_break_and_ranking
        """
        ctx = setup_open_stand_with_menu()
        # Occupy lane B first with a window order: B now has outstanding build
        # seconds; an app merge must prefer the empty lane A.
        place_window_order(ctx, ctx["recipe"]["id"], lane_code="B")
        account = create_loyalty_account(ctx["stand"]["id"], full_name="App Amy")
        order = place_app_order(ctx, ctx["recipe"]["id"], account["id"])
        merged = validate_success(
            api.merge_order(
                order["id"],
                {"expected_stand_version": stand_version(ctx)},
                make_loyalty_customer_headers(account["id"]),
            ),
            200,
        )
        assert merged["lane_code"] == "A", (
            f"lane B carries 60s projected clear vs A's 0, got {merged['lane_code']}"
        )

    def test_selector_skips_full_lane_and_uses_remaining_capacity(self, api):
        """PRD §3.6: "The selector considers only lanes with a free stacking slot
        — those whose occupied count (orders in the lane with `queue_status` of
        `MERGED` or `AT_WINDOW`) is below that lane's `max_stack_cars`"

        Design: Corner/cross_cutting_complexity_layers/selector_skips_full_lane_and_uses_remaining_capacity
        """
        ctx = setup_open_stand_with_menu(
            stand_overrides={
                "lane_configs": [
                    {"lane_code": "A", "max_stack_cars": 1},
                    {"lane_code": "B", "max_stack_cars": 9},
                ]
            }
        )
        # Fill lane A's single slot with a MERGED window order.
        place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        account = create_loyalty_account(ctx["stand"]["id"], full_name="Deferred Deb")
        order = place_app_order(ctx, ctx["recipe"]["id"], account["id"])
        merged = validate_success(
            api.merge_order(
                order["id"],
                {"expected_stand_version": stand_version(ctx)},
                make_loyalty_customer_headers(account["id"]),
            ),
            200,
        )
        assert merged["lane_code"] == "B", (
            f"lane A is full (1/1); eligibility is per-lane capacity, got {merged['lane_code']}"
        )


class TestLaneSlotConservation:
    def test_lane_slot_reserve_and_release_conserve_stacking_capacity(self, api):
        """PRD §3.6: "The same capacity ceiling applies to window-order creation:
        a window order naming a lane with no free slot is likewise rejected with
        `ERR_LANE_STACKING_FULL`."
        PRD §3.8: "A successful handoff stamps `handoff_at` with the current
        logical clock — the timestamp that later feeds throughput windows and
        royalty attribution — moves `build_status` to `HANDED_OFF`, and releases
        the lane slot, decrementing the stand's `lane_occupancy` for that lane."

        Design: Difficulty/compensating_invariant/lane_slot_reserve_and_release_conserve_stacking_capacity
        """
        ctx = setup_open_stand_with_menu(
            stand_overrides={
                "lane_configs": [
                    {"lane_code": "A", "max_stack_cars": 1},
                    {"lane_code": "B", "max_stack_cars": 9},
                ]
            }
        )
        order1 = place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        stand = validate_success(
            api.get_stand(ctx["stand"]["id"], ctx["operator_headers"]), 200
        )
        assert stand["lane_occupancy"]["A"] == 1, "the single lane-A slot is reserved"

        # Second lane-A window order must fail even though lane B has free slots.
        version2 = stand_version(ctx)
        resp = api.create_order(
            {
                "stand_id": ctx["stand"]["id"],
                "source": "WINDOW",
                "lane_code": "A",
                "items": [
                    {"recipe_id": ctx["recipe"]["id"], "quantity": 1, "modifier_names": []}
                ],
                "expected_stand_version": version2,
            },
            make_crew_member_headers(ctx["taker"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LANE_STACKING_FULL, 409)

        # Serve order 1: handoff releases the slot (compensating release).
        items = list_items_of_order(ctx, order1["id"])
        build_item_ready(ctx, items[0]["id"])
        payment = None
        from test_helpers import authorize_order

        payment = authorize_order(ctx, order1["id"])
        lead = make_shift_lead_headers(ctx["lead"]["id"])
        validate_success(api.call_to_window(order1["id"], lead), 200)
        validate_success(api.capture_payment(payment["id"], lead), 200)
        validate_success(api.handoff_order(order1["id"], lead), 200)
        stand = validate_success(
            api.get_stand(ctx["stand"]["id"], ctx["operator_headers"]), 200
        )
        assert stand["lane_occupancy"].get("A", 0) == 0, (
            f"handoff must release the slot, got {stand['lane_occupancy']}"
        )

        # Third lane-A window order now succeeds.
        version3 = stand_version(ctx)
        resp3 = api.create_order(
            {
                "stand_id": ctx["stand"]["id"],
                "source": "WINDOW",
                "lane_code": "A",
                "items": [
                    {"recipe_id": ctx["recipe"]["id"], "quantity": 1, "modifier_names": []}
                ],
                "expected_stand_version": version3,
            },
            make_crew_member_headers(ctx["taker"]["id"]),
        )
        order3 = validate_success(resp3, 201)
        assert order3["queue_status"] == "MERGED"

    def test_lane_occupancy_returns_to_zero_after_handoff(self, api):
        """PRD §3.6: "The stand's `lane_occupancy` is, at all times, the per-lane
        count of orders `MERGED` or `AT_WINDOW`."

        Design: Difficulty/compensating_invariant/lane_slot_reserve_and_release_conserve_stacking_capacity
        """
        ctx = setup_open_stand_with_menu(
            stand_overrides={
                "lane_configs": [
                    {"lane_code": "A", "max_stack_cars": 1},
                    {"lane_code": "B", "max_stack_cars": 9},
                ]
            }
        )
        served = serve_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        assert served["order"]["queue_status"] == "SERVED"
        stand = validate_success(
            api.get_stand(ctx["stand"]["id"], ctx["operator_headers"]), 200
        )
        assert stand["lane_occupancy"].get("A", 0) == 0
        # occupied + free == max_stack_cars throughout: with occupancy 0, lane A
        # accepts a fresh window order again.
        order = place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        assert order["queue_status"] == "MERGED"


class TestOrderCreateVersionAndLaneSeq:
    def test_order_create_increments_stand_version_and_assigns_lane_seq(self, api):
        """PRD §2.7: "Creating an order requires `expected_stand_version` matching
        the stand's current `version`. Order creation legitimately mutates the
        stand — allocating `lane_seq`, reserving a lane slot for window orders,
        and bumping the stand's `version`"
        PRD §3.6: "receives its `lane_seq` — the per-lane monotonic sequence
        assigned as one more than the highest `lane_seq` ever assigned in that
        lane, or one for the lane's first order."

        Design: Corner/endpoints/order_create_increments_stand_version_and_assigns_lane_seq
        """
        ctx = setup_open_stand_with_menu()
        version_before = stand_version(ctx)
        order1 = place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        stand = validate_success(
            api.get_stand(ctx["stand"]["id"], ctx["operator_headers"]), 200
        )
        assert stand["version"] == version_before + 1, (
            f"create must bump stand version by exactly 1: {version_before} -> {stand['version']}"
        )
        assert order1["lane_seq"] == 1
        order2 = place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        assert order2["lane_seq"] == 2, (
            f"per-lane monotonic sequence: 1 then 2, got {order2['lane_seq']}"
        )

    def test_second_create_uses_fresh_version_after_first_bump(self, api):
        """PRD §3.6: "Both creates are OCC-protected writes requiring
        `expected_stand_version` (§2.7), and a successful create increments the
        stand's `version` by one."

        Design: Corner/endpoints/order_create_increments_stand_version_and_assigns_lane_seq
        """
        ctx = setup_open_stand_with_menu()
        order1 = place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        order2 = place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        assert order1["lane_seq"] == 1
        assert order2["lane_seq"] == 2
        stand = validate_success(
            api.get_stand(ctx["stand"]["id"], ctx["operator_headers"]), 200
        )
        assert stand["lane_occupancy"]["A"] == 2

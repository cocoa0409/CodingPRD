"""Cascades that reach entities the trigger never names.

One price publication walks ingredient to price row to sub-recipe to plated
parent to menu item to margin class.  One specification approval walks component
to recipe to menu item to promotion, ending on a reverse state-machine edge.
Both are written so that a cascade which stops one hop short, or which rewrites
a figure instead of a state, is visible.
"""

from test_helpers import (
    ApiClient,
    CostBasis,
    CostState,
    IngredientPriceStatus,
    LtoStatus,
    MarginClass,
    MenuItemStatus,
    PriceFeedStatus,
    RecipeStatus,
    ReviewBasis,
    SyncState,
    assert_fields,
    assert_ingredient_price,
    assert_lto_campaign,
    assert_menu_item,
    assert_mix_line,
    assert_prep_guide,
    assert_price_feed,
    assert_recipe,
    assert_recipe_component,
    fixtures,
    get_success_data,
    round_half_up,
    single_row,
    validate_paginated,
)


class TestPriceFeedPublicationFiveHopCascade:
    """A cheddar price moves a mac-and-cheese margin class.

    The plated recipe references the ingredient nowhere: it reaches it only
    through the sub-recipe, so the recipe-graph edge has to be walked.
    """

    @staticmethod
    def _mac_world(api: ApiClient):
        """SUB-CHEESE under PLATE-MAC, one live item, one classified review."""
        stack = fixtures.cheese_stack_active(
            api,
            child_ep=500,
            parent_ep=200,
            parent_overrides={
                "code": "PLATE-MAC",
                "name": "Mac and Cheese Plate",
                "batch_yield_base_units": 5,
                "portions_per_batch": 5,
            },
            child_overrides={
                "code": "SUB-CHEESE",
                "name": "Cheese Sauce Base",
                "batch_yield_base_units": 1000,
                "portions_per_batch": 10,
            },
        )
        item = fixtures.create_menu_item(
            api, stack["parent"]["id"], code="MI-MAC-MW", name="Mac and Cheese"
        )
        item = fixtures.plate_cost(api, item["id"])
        item = fixtures.activate_menu_item(api, item["id"])
        unit = fixtures.create_unit(api, code="UNIT-MW-01", name="Downtown MW")
        review = fixtures.open_review(api, unit["id"])
        mix_line = fixtures.load_mix_line(
            api, review["id"], item["id"], units_sold=50, gross_sales_cents=20_000
        )
        fixtures.classify_review(api, review["id"])
        staged = fixtures.stage_price_feed(
            api,
            stack["cheddar"]["id"],
            25_000_000,
            effective_from="2026-07-15T00:00:00.000Z",
        )
        stack.update(
            {
                "menu_item": item,
                "review": review,
                "mix_line": mix_line,
                "staged_feed": staged,
            }
        )
        return stack

    def test_the_two_levels_cost_up_from_the_child_batch_and_its_yield(
        self, api: ApiClient
    ) -> None:
        """4850088 in the child becomes 970018 in the parent.

        PRD 3.3: "the extended cost is then `ep_quantity_base_units` multiplied
        by the child's `batch_cost_micros`, divided by the child's
        `batch_yield_base_units`, rounded half up"

        Design: Difficulty/transitive_cascade/price_feed_publication_five_hop_invalidation_from_ingredient_to_margin_class
        """
        world = self._mac_world(api)

        assert_recipe(
            world["child"],
            status=RecipeStatus.ACTIVE,
            batch_cost_micros=round_half_up(500 * 22_000_000, 2268),
            portion_cost_micros=round_half_up(
                round_half_up(500 * 22_000_000, 2268), 10
            ),
        )
        assert_fields(
            world["child"], batch_cost_micros=4_850_088, portion_cost_micros=485_009
        )
        assert_recipe(
            world["parent"],
            batch_cost_micros=round_half_up(200 * 4_850_088, 1000),
            portion_cost_micros=round_half_up(970_018, 5),
            depth=1,
        )
        assert_fields(
            world["parent"], batch_cost_micros=970_018, portion_cost_micros=194_004
        )

    def test_the_garnish_allowance_is_clamped_up_to_its_flat_floor(
        self, api: ApiClient
    ) -> None:
        """2968 micro-dollars of proportional garnish loses to the 8000 floor.

        PRD 3.5: "compute the garnish allowance as 150 basis points of the
        waste-adjusted figure — multiply by 150 and divide by 10000 — and then
        take whichever is larger, that proportional amount or the flat garnish
        floor of 8000 micro-dollars"

        Design: Difficulty/transitive_cascade/price_feed_publication_five_hop_invalidation_from_ingredient_to_margin_class
        """
        world = self._mac_world(api)

        freighted = round_half_up(194_004 * 10_000, 10_000)
        wasted = round_half_up(freighted * 10_200, 10_000)
        assert (freighted, wasted) == (194_004, 197_884)
        assert round_half_up(wasted * 150, 10_000) == 2968

        assert_menu_item(
            world["menu_item"],
            plate_cost_state=CostState.FRESH,
            cost_basis=CostBasis.LATEST_PUBLISHED,
            plate_cost_micros=wasted + 8000,
            plate_cost_cents=round_half_up(205_884, 10_000),
            food_cost_bps=round_half_up(21 * 10_000, 400),
            contribution_margin_cents=400 - 21,
        )
        assert_fields(
            world["menu_item"],
            plate_cost_micros=205_884,
            plate_cost_cents=21,
            food_cost_bps=525,
            contribution_margin_cents=379,
        )

    def test_the_publication_truncates_the_open_ended_predecessor(
        self, api: ApiClient
    ) -> None:
        """The 2026-07-01 row is closed at 2026-07-15 and superseded.

        PRD 3.2: "any existing `PUBLISHED` row covering the same ingredient and
        region whose `effective_to` is null and whose `effective_from` is earlier
        than the new line's `effective_from` is truncated in place: its
        `effective_to` becomes the new line's `effective_from` and its `status`
        becomes `SUPERSEDED`."

        Design: Difficulty/transitive_cascade/price_feed_publication_five_hop_invalidation_from_ingredient_to_margin_class
        """
        world = self._mac_world(api)

        published = fixtures.publish_price_feed(api, world["staged_feed"]["id"])

        assert_price_feed(
            published,
            status=PriceFeedStatus.PUBLISHED,
            superseded_price_count=1,
        )
        rows, meta = validate_paginated(
            api.list_ingredient_prices(world["cheddar"]["id"])
        )
        assert meta["total_count"] == 2, (
            "both the truncated row and its successor survive"
        )
        assert_ingredient_price(
            rows[0],
            pack_cost_micros=22_000_000,
            effective_from="2026-07-01T00:00:00.000Z",
            effective_to="2026-07-15T00:00:00.000Z",
            status=IngredientPriceStatus.SUPERSEDED,
        )
        assert_ingredient_price(
            rows[1],
            pack_cost_micros=25_000_000,
            effective_from="2026-07-15T00:00:00.000Z",
            effective_to=None,
            status=IngredientPriceStatus.PUBLISHED,
        )

    def test_the_recipe_counter_adds_the_dag_edge_to_the_ingredient_edge(
        self, api: ApiClient
    ) -> None:
        """Two recipes and one item, from a feed naming only an ingredient.

        PRD 3.2: "The feed's `affected_recipe_count` records the number of
        distinct recipes flipped across the second and third hops together"

        Design: Difficulty/transitive_cascade/price_feed_publication_five_hop_invalidation_from_ingredient_to_margin_class
        """
        world = self._mac_world(api)

        published = fixtures.publish_price_feed(api, world["staged_feed"]["id"])

        assert_price_feed(
            published, affected_recipe_count=2, affected_menu_item_count=1
        )

    def test_both_recipes_go_stale_with_every_figure_frozen(
        self, api: ApiClient
    ) -> None:
        """The plated parent is invalidated purely because its child moved.

        PRD 3.2: "Every recipe holding an active sub-recipe component whose child
        is one of the newly stale recipes also flips its `cost_state` to `STALE`,
        and that reasoning repeats transitively up the recipe graph until no
        further parent changes."

        Design: Difficulty/transitive_cascade/price_feed_publication_five_hop_invalidation_from_ingredient_to_margin_class
        """
        world = self._mac_world(api)

        fixtures.publish_price_feed(api, world["staged_feed"]["id"])

        assert_recipe(
            get_success_data(api.get_recipe(world["child"]["id"])),
            cost_state=CostState.STALE,
            batch_cost_micros=4_850_088,
            portion_cost_micros=485_009,
        )
        assert_recipe(
            get_success_data(api.get_recipe(world["parent"]["id"])),
            cost_state=CostState.STALE,
            batch_cost_micros=970_018,
            portion_cost_micros=194_004,
        )
        assert_recipe_component(
            get_success_data(
                api.get_recipe_component(world["parent_component"]["id"])
            ),
            unit_cost_micros_used=4_850_088,
            pack_base_units_snapshot=1000,
            extended_cost_micros=970_018,
        )

    def test_the_item_loses_its_state_and_its_class_but_not_its_figures(
        self, api: ApiClient
    ) -> None:
        """Hop four flips the state and hop five clears the class.

        PRD 3.2: "The **fifth hop** exists because those menu items' plate costs
        went stale: each of them has its `margin_class` reset to
        `UNCLASSIFIED`."

        Design: Difficulty/transitive_cascade/price_feed_publication_five_hop_invalidation_from_ingredient_to_margin_class
        """
        world = self._mac_world(api)
        assert world["menu_item"]["margin_class"] == MarginClass.UNCLASSIFIED

        fixtures.publish_price_feed(api, world["staged_feed"]["id"])

        assert_menu_item(
            get_success_data(api.get_menu_item(world["menu_item"]["id"])),
            status=MenuItemStatus.ACTIVE,
            plate_cost_state=CostState.STALE,
            plate_cost_cents=21,
            plate_cost_micros=205_884,
            margin_class=MarginClass.UNCLASSIFIED,
        )

    def test_the_classified_mix_history_is_never_rewritten(
        self, api: ApiClient
    ) -> None:
        """The line keeps its 21-cent snapshot and its STAR verdict.

        PRD 3.8: "The line freezes `plate_cost_cents_snapshot` from the item's
        `plate_cost_cents` at the moment of loading, and every later
        classification and close values that line with the snapshot rather than
        with the item's live plate cost."

        Design: Difficulty/transitive_cascade/price_feed_publication_five_hop_invalidation_from_ingredient_to_margin_class
        """
        world = self._mac_world(api)
        classified = single_row(fixtures.mix_line_rows(api, world["review"]["id"]))
        assert_mix_line(
            classified,
            plate_cost_cents_snapshot=21,
            margin_class=MarginClass.STAR,
        )

        fixtures.publish_price_feed(api, world["staged_feed"]["id"])

        assert_mix_line(
            single_row(fixtures.mix_line_rows(api, world["review"]["id"])),
            plate_cost_cents_snapshot=21,
            cm_per_unit_cents=379,
            margin_class=MarginClass.STAR,
        )


class TestSpecChangeApprovalCascadeToPromotion:
    """A component quantity moves a promotion back into planning."""

    @staticmethod
    def _promoted_world(api: ApiClient):
        """A live item with a COSTED promotion, an open review and a PENDING order."""
        world = fixtures.grill_world_active_item(api)
        campaign = fixtures.costed_lto(
            api,
            world["menu_item"]["id"],
            window_start="2026-08-10T00:00:00.000Z",
            window_end="2026-08-20T00:00:00.000Z",
            promo_price_cents=380,
            forecast_units=500,
        )
        unit = fixtures.create_unit(api, code="UNIT-MW-01", name="Downtown MW")
        review = fixtures.open_review(
            api, unit["id"], basis=ReviewBasis.USAGE_BASED
        )
        fixtures.load_mix_line(
            api,
            review["id"],
            world["menu_item"]["id"],
            units_sold=50,
            gross_sales_cents=20_000,
        )
        count_line = fixtures.record_count_line(
            api,
            review["id"],
            world["cheddar"]["id"],
            opening_base_units=5300,
            received_base_units=0,
            counted_base_units=41,
        )
        order = fixtures.open_qty_change(
            api,
            world["recipe"]["id"],
            world["component"]["id"],
            new_ep_quantity_base_units=600,
        )
        fixtures.submit_change_order(api, order["id"])
        world.update(
            {
                "campaign": campaign,
                "review": review,
                "count_line": count_line,
                "order": order,
            }
        )
        return world

    def test_the_campaign_is_costed_from_the_items_frozen_plate_cost(
        self, api: ApiClient
    ) -> None:
        """100 cents over a 380-cent promo price is 2632 basis points.

        PRD 3.9: "The run freezes `promo_plate_cost_cents` from the item's
        `plate_cost_cents`; computes `promo_food_cost_bps` as
        `promo_plate_cost_cents` multiplied by 10000, divided by
        `promo_price_cents`, rounded half up; and computes
        `forecast_contribution_cents` as `forecast_units` multiplied by the
        difference between `promo_price_cents` and `promo_plate_cost_cents`."

        Design: Difficulty/transitive_cascade/spec_change_approval_cascade_from_component_to_lto_campaign
        """
        world = self._promoted_world(api)

        assert_lto_campaign(
            world["campaign"],
            status=LtoStatus.COSTED,
            promo_plate_cost_cents=100,
            promo_food_cost_bps=round_half_up(100 * 10_000, 380),
            forecast_contribution_cents=500 * (380 - 100),
        )
        assert_fields(
            world["campaign"],
            promo_food_cost_bps=2632,
            forecast_contribution_cents=140_000,
        )

    def test_the_approval_rides_the_costed_to_planned_reverse_edge(
        self, api: ApiClient
    ) -> None:
        """The promotion is returned to planning with its figures cleared.

        PRD 3.9: "It clears `promo_plate_cost_cents`, `promo_food_cost_bps` and
        `forecast_contribution_cents` back to 0 and increments the campaign's
        `version`, so a campaign can never be launched on figures nobody has
        recomputed."

        Design: Difficulty/transitive_cascade/spec_change_approval_cascade_from_component_to_lto_campaign
        """
        world = self._promoted_world(api)

        fixtures.approve_change_order(api, world["order"]["id"])

        assert_lto_campaign(
            get_success_data(api.get_lto_campaign(world["campaign"]["id"])),
            status=LtoStatus.PLANNED,
            promo_plate_cost_cents=0,
            promo_food_cost_bps=0,
            forecast_contribution_cents=0,
        )

    def test_the_nutrition_rollup_moves_while_the_batch_cost_stands_still(
        self, api: ApiClient
    ) -> None:
        """Sodium rises from 620000 to 930000; 3880071 micros do not move.

        PRD 3.6: "the owning recipe recomputes `component_count`,
        `allergen_mask`, `kcal_per_portion_micros`, `sodium_mcg_per_portion` and
        `depth` from the new component set, flips `cost_state` to `STALE`"

        Design: Difficulty/transitive_cascade/spec_change_approval_cascade_from_component_to_lto_campaign
        """
        world = self._promoted_world(api)
        assert_recipe(
            world["recipe"],
            kcal_per_portion_micros=400_000_000,
            sodium_mcg_per_portion=620_000,
        )

        approved = fixtures.approve_change_order(api, world["order"]["id"])

        assert_fields(
            approved,
            pre_change_batch_cost_micros=3_880_071,
            pre_change_ep_quantity_base_units=400,
            pre_change_allergen_mask=1,
        )
        assert_recipe(
            get_success_data(api.get_recipe(world["recipe"]["id"])),
            cost_state=CostState.STALE,
            batch_cost_micros=3_880_071,
            kcal_per_portion_micros=600_000_000,
            sodium_mcg_per_portion=930_000,
            allergen_mask=1,
            component_count=1,
        )
        assert_recipe_component(
            get_success_data(api.get_recipe_component(world["component"]["id"])),
            ep_quantity_base_units=600,
            ap_quantity_base_units=600,
            extended_cost_micros=3_880_071,
        )

    def test_the_menu_item_copies_the_new_sodium_down_the_chain(
        self, api: ApiClient
    ) -> None:
        """The item republishes the recipe's sodium while keeping 100 cents.

        PRD 3.6: "every menu item whose `recipe_id` is this recipe copies the
        recipe's new `allergen_mask` and new `sodium_mcg_per_portion`, flips
        `plate_cost_state` to `STALE`, resets `margin_class` to `UNCLASSIFIED`
        and increments `version`"

        Design: Difficulty/transitive_cascade/spec_change_approval_cascade_from_component_to_lto_campaign
        """
        world = self._promoted_world(api)
        assert world["menu_item"]["sodium_mcg_per_portion"] == 620_000

        fixtures.approve_change_order(api, world["order"]["id"])

        assert_menu_item(
            get_success_data(api.get_menu_item(world["menu_item"]["id"])),
            status=MenuItemStatus.ACTIVE,
            plate_cost_state=CostState.STALE,
            plate_cost_cents=100,
            margin_class=MarginClass.UNCLASSIFIED,
            sodium_mcg_per_portion=930_000,
            allergen_mask=1,
        )

    def test_the_documents_are_enqueued_for_propagation_not_drained(
        self, api: ApiClient
    ) -> None:
        """Both the prep guide and the open count sheet go out of date in place.

        PRD 3.6: "Hop 2 also enqueues the propagation work: it flips the recipe's
        prep guide `sync_state` to `OUT_OF_DATE`, and it flips `sync_state` to
        `OUT_OF_DATE` on every count sheet line that belongs to a period review
        whose `status` is not `CLOSED`"

        Design: Difficulty/transitive_cascade/spec_change_approval_cascade_from_component_to_lto_campaign
        """
        world = self._promoted_world(api)
        assert world["count_line"]["expected_base_units"] == 5000

        fixtures.approve_change_order(api, world["order"]["id"])

        assert_prep_guide(
            fixtures.sole_prep_guide(api, world["recipe"]["id"]),
            revision_no=1,
            sync_state=SyncState.OUT_OF_DATE,
        )
        assert_fields(
            single_row(fixtures.count_line_rows(api, world["review"]["id"])),
            sync_state=SyncState.OUT_OF_DATE,
            expected_base_units=5000,
            used_base_units=5259,
        )

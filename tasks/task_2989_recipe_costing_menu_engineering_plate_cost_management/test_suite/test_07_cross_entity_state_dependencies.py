"""Transitions blocked by state that lives on a different entity.

In both scenarios the requested entity is already in the exact state its own
state machine demands; the refusal comes from a neighbour.  Each is then
unblocked by writing only to that neighbour and re-issuing the identical
request, which is what separates a genuine cross-entity gate from a
self-referential one.
"""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    CULINARY_DIRECTOR,
    COST_ANALYST,
    CostState,
    LtoStatus,
    MenuItemStatus,
    RecipeStatus,
    assert_lto_campaign,
    assert_menu_item,
    assert_price_feed,
    assert_recipe,
    fixtures,
    get_success_data,
    round_half_up,
    validate_error,
)


class TestMenuItemActivationWaitsOnTheRecipeLifecycle:
    """A flawless item held back by an UNDER_REVIEW recipe."""

    @staticmethod
    def _item_ready_but_recipe_not(api: ApiClient):
        """A plate-costed DRAFT item hanging off a recipe still in review."""
        world = fixtures.grill_world_under_review(api)
        item = fixtures.create_menu_item(api, world["recipe"]["id"])
        world["created_item"] = item
        world["menu_item"] = fixtures.plate_cost(api, item["id"])
        return world

    def test_the_recipe_is_costed_and_masked_but_only_under_review(
        self, api: ApiClient
    ) -> None:
        """FRESH at allergen mask 1, and one step short of ACTIVE.

        PRD 3.4: "Submitting a recipe for review moves it from `DRAFT` to
        `UNDER_REVIEW`"

        Design: Difficulty/cross_entity_state_dependency/menu_item_activation_requires_backing_recipe_active
        """
        world = self._item_ready_but_recipe_not(api)

        assert_recipe(
            world["recipe"],
            status=RecipeStatus.UNDER_REVIEW,
            cost_state=CostState.FRESH,
            allergen_mask=1,
        )

    def test_every_condition_belonging_to_the_item_itself_is_satisfied(
        self, api: ApiClient
    ) -> None:
        """DRAFT, 100 cents, FRESH, and a declared mask that covers the recipe.

        PRD 3.5: "Every allergen bit set in the backing recipe's rolled-up
        `allergen_mask` must also be set in the item's `declared_allergen_mask`"

        Design: Difficulty/cross_entity_state_dependency/menu_item_activation_requires_backing_recipe_active
        """
        world = self._item_ready_but_recipe_not(api)

        assert_menu_item(world["created_item"], status=MenuItemStatus.DRAFT)
        assert_menu_item(
            world["menu_item"],
            status=MenuItemStatus.DRAFT,
            plate_cost_cents=100,
            plate_cost_state=CostState.FRESH,
            allergen_mask=1,
            declared_allergen_mask=1,
        )

    def test_the_activation_reports_the_neighbours_lifecycle_error(
        self, api: ApiClient
    ) -> None:
        """A recipe-state 409, not a staleness or allergen complaint.

        PRD 3.5: "The backing recipe's `status` must be `ACTIVE`, otherwise
        `ERR_RECIPE_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/menu_item_activation_requires_backing_recipe_active
        """
        world = self._item_ready_but_recipe_not(api)

        response = api.activate_menu_item(world["menu_item"]["id"], CULINARY_DIRECTOR)

        validate_error(response, ApiErrorId.RECIPE_INVALID_STATE)

    def test_the_refused_activation_leaves_the_item_exactly_as_it_was(
        self, api: ApiClient
    ) -> None:
        """Still DRAFT, still holding its 100-cent plate cost.

        PRD 2.10: "no later rule is evaluated and no partial mutation is
        persisted"

        Design: Difficulty/cross_entity_state_dependency/menu_item_activation_requires_backing_recipe_active
        """
        world = self._item_ready_but_recipe_not(api)

        api.activate_menu_item(world["menu_item"]["id"], CULINARY_DIRECTOR)

        assert_menu_item(
            get_success_data(api.get_menu_item(world["menu_item"]["id"])),
            status=MenuItemStatus.DRAFT,
            plate_cost_cents=100,
            plate_cost_state=CostState.FRESH,
        )

    def test_activating_the_recipe_alone_unblocks_the_identical_request(
        self, api: ApiClient
    ) -> None:
        """A write to a different entity is the whole repair.

        PRD 3.5: "A successful activation increments the item's `version` and
        changes nothing else."

        Design: Difficulty/cross_entity_state_dependency/menu_item_activation_requires_backing_recipe_active
        """
        world = self._item_ready_but_recipe_not(api)
        api.activate_menu_item(world["menu_item"]["id"], CULINARY_DIRECTOR)

        activated_recipe = fixtures.activate_recipe(api, world["recipe"]["id"])
        activated_item = fixtures.activate_menu_item(api, world["menu_item"]["id"])

        assert_recipe(activated_recipe, status=RecipeStatus.ACTIVE)
        assert_menu_item(
            activated_item,
            status=MenuItemStatus.ACTIVE,
            plate_cost_cents=100,
            plate_cost_state=CostState.FRESH,
        )


class TestPromotionCostingWaitsOnADerivedFreshnessFlag:
    """A PLANNED campaign blocked by a feed two hops away."""

    @staticmethod
    def _campaign_behind_a_stale_item(api: ApiClient):
        """A PLANNED promotion whose item went stale after it was planned."""
        world = fixtures.grill_world_active_item(api)
        planned = fixtures.plan_lto(
            api,
            world["menu_item"]["id"],
            window_start="2026-08-10T00:00:00.000Z",
            window_end="2026-08-20T00:00:00.000Z",
            promo_price_cents=380,
            forecast_units=500,
        )
        second_feed = fixtures.publish_price(
            api,
            world["cheddar"]["id"],
            25_000_000,
            effective_from="2026-07-15T00:00:00.000Z",
        )
        world.update({"planned": planned, "second_feed": second_feed})
        return world

    def test_the_campaign_is_planned_on_a_hundred_cent_plate_cost(
        self, api: ApiClient
    ) -> None:
        """The item was FRESH at 100 cents when the promotion was planned.

        PRD 3.9: "It opens in `PLANNED` with `verdict` `PENDING`, a null
        `reviewed_at`, and `promo_plate_cost_cents`, `promo_food_cost_bps`,
        `forecast_contribution_cents`, `actual_units`,
        `actual_gross_sales_cents`, `promo_support_cost_cents`,
        `promo_contribution_cents` and `forecast_attainment_bps` all 0."

        Design: Difficulty/cross_entity_state_dependency/lto_costing_requires_menu_item_plate_cost_fresh
        """
        world = self._campaign_behind_a_stale_item(api)

        assert world["menu_item"]["plate_cost_cents"] == 100
        assert_lto_campaign(
            world["planned"],
            status=LtoStatus.PLANNED,
            promo_plate_cost_cents=0,
            promo_food_cost_bps=0,
            forecast_contribution_cents=0,
        )
        assert_price_feed(world["second_feed"], affected_menu_item_count=1)

    def test_the_costing_run_is_refused_on_the_items_freshness_alone(
        self, api: ApiClient
    ) -> None:
        """Both statuses are already the required ones; only the flag is wrong.

        PRD 3.9: "The backing menu item's `status` must be `ACTIVE`, otherwise
        `ERR_MENU_ITEM_INVALID_STATE`, and its `plate_cost_state` must be
        `FRESH`, otherwise `ERR_COST_STALE`."

        Design: Difficulty/cross_entity_state_dependency/lto_costing_requires_menu_item_plate_cost_fresh
        """
        world = self._campaign_behind_a_stale_item(api)
        assert_menu_item(
            get_success_data(api.get_menu_item(world["menu_item"]["id"])),
            status=MenuItemStatus.ACTIVE,
            plate_cost_state=CostState.STALE,
        )

        response = api.cost_lto_campaign(world["planned"]["id"], COST_ANALYST)

        validate_error(response, ApiErrorId.COST_STALE)

    def test_the_refused_costing_leaves_the_campaign_uncosted_and_planned(
        self, api: ApiClient
    ) -> None:
        """No figure is written and the item stays on the menu.

        PRD 3.9: "so a campaign can never be launched on figures nobody has
        recomputed"

        Design: Difficulty/cross_entity_state_dependency/lto_costing_requires_menu_item_plate_cost_fresh
        """
        world = self._campaign_behind_a_stale_item(api)

        api.cost_lto_campaign(world["planned"]["id"], COST_ANALYST)

        assert_lto_campaign(
            get_success_data(api.get_lto_campaign(world["planned"]["id"])),
            status=LtoStatus.PLANNED,
            promo_plate_cost_cents=0,
        )
        assert_menu_item(
            get_success_data(api.get_menu_item(world["menu_item"]["id"])),
            status=MenuItemStatus.ACTIVE,
        )

    def test_repairing_the_flag_moves_the_figure_the_campaign_will_snapshot(
        self, api: ApiClient
    ) -> None:
        """The roll-up and re-cost carry the plate cost from 100 to 114.

        PRD 3.9: "Recovering means recomputing the recipe's cost, recomputing the
        item's plate cost, and costing the campaign again."

        Design: Difficulty/cross_entity_state_dependency/lto_costing_requires_menu_item_plate_cost_fresh
        """
        world = self._campaign_behind_a_stale_item(api)
        api.cost_lto_campaign(world["planned"]["id"], COST_ANALYST)

        rolled = fixtures.rollup(api, world["recipe"]["id"])
        recosted = fixtures.plate_cost(api, world["menu_item"]["id"])

        assert_recipe(
            rolled,
            cost_state=CostState.FRESH,
            portion_cost_micros=round_half_up(
                round_half_up(400 * 25_000_000, 2268), 4
            ),
        )
        assert rolled["portion_cost_micros"] == 1_102_293
        assert_menu_item(
            recosted, plate_cost_state=CostState.FRESH, plate_cost_cents=114
        )

    def test_the_promotion_is_costed_on_the_recomputed_figure(
        self, api: ApiClient
    ) -> None:
        """114 cents, not the 100 that was current at planning time.

        PRD 3.9: "The run freezes `promo_plate_cost_cents` from the item's
        `plate_cost_cents`"

        Design: Difficulty/cross_entity_state_dependency/lto_costing_requires_menu_item_plate_cost_fresh
        """
        world = self._campaign_behind_a_stale_item(api)
        api.cost_lto_campaign(world["planned"]["id"], COST_ANALYST)
        fixtures.rollup(api, world["recipe"]["id"])
        fixtures.plate_cost(api, world["menu_item"]["id"])

        costed = fixtures.cost_lto(api, world["planned"]["id"])

        assert_lto_campaign(
            costed,
            status=LtoStatus.COSTED,
            promo_plate_cost_cents=114,
            promo_food_cost_bps=round_half_up(114 * 10_000, 380),
            forecast_contribution_cents=500 * (380 - 114),
        )
        assert costed["promo_food_cost_bps"] == 3000
        assert costed["forecast_contribution_cents"] == 133_000
        assert costed["promo_plate_cost_cents"] != 100, (
            "the gate exists so the promotion cannot snapshot the pre-repair figure"
        )

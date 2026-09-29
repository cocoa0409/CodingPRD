"""Formulas whose internal evaluation order changes the answer.

One aggregation is pinned to round-then-sum, and one projection is pinned to
food-cost-then-relief.  Both are written here so that a collapsed expression —
a single division at the end of the sum, or a cap evaluated before the food
cost — produces a visibly different number rather than a plausible one.
"""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    BaseUom,
    CostBasis,
    CostState,
    MenuItemStatus,
    ProposalStatus,
    RECIPE_DEVELOPER,
    RecipeType,
    assert_fields,
    assert_menu_item,
    assert_projections_unset,
    assert_proposal,
    assert_recipe,
    assert_recipe_component,
    ceil_div,
    factories,
    fixtures,
    get_success_data,
    round_half_up,
    validate_error,
)


class TestRoundThenSumOnTheBatchCost:
    """Three components with fractional remainders summed under one rule."""

    @staticmethod
    def _patty_melt(api: ApiClient):
        """Four priced ingredients, an ACTIVE sauce sub-recipe, a DRAFT melt."""
        sauce = fixtures.create_ingredient(
            api,
            sku="TOMATO-SAUCE",
            name="Tomato Sauce",
            base_uom=BaseUom.GRAM,
            pack_base_units=3785,
            trim_yield_bps=10000,
            cook_shrink_bps=500,
            allergen_mask=0,
            kcal_per_base_unit_micros=300_000,
            sodium_mcg_per_base_unit=4100,
        )
        oil = fixtures.create_ingredient(
            api,
            sku="PEANUT-OIL",
            name="Peanut Oil",
            base_uom=BaseUom.GRAM,
            pack_base_units=946,
            allergen_mask=8,
            kcal_per_base_unit_micros=8_000_000,
            sodium_mcg_per_base_unit=0,
        )
        beef = fixtures.create_ingredient(
            api,
            sku="BEEF-CHUCK",
            name="Beef Chuck",
            base_uom=BaseUom.GRAM,
            pack_base_units=4536,
            trim_yield_bps=8500,
            cook_shrink_bps=2000,
            allergen_mask=0,
            kcal_per_base_unit_micros=2_500_000,
            sodium_mcg_per_base_unit=700,
        )
        cheddar = fixtures.create_cheddar(api)

        feed = fixtures.open_price_feed(
            api, feed_date="2026-07-01T00:00:00.000Z"
        )
        for ingredient, pack_cost in (
            (sauce, 9_500_000),
            (oil, 12_000_000),
            (beef, 38_500_000),
            (cheddar, 22_000_000),
        ):
            fixtures.add_price_line(
                api,
                feed["id"],
                ingredient["id"],
                pack_cost_micros=pack_cost,
                effective_from="2026-07-01T00:00:00.000Z",
            )
        published_feed = fixtures.publish_price_feed(api, feed["id"])

        sauce_recipe = fixtures.create_sub_recipe(
            api,
            code="SUB-SAUCE",
            name="House Sauce",
            batch_yield_base_units=2000,
            portions_per_batch=40,
        )
        sauce_component = fixtures.add_ingredient_component(
            api,
            sauce_recipe["id"],
            sauce["id"],
            ep_quantity_base_units=1900,
            sequence_no=1,
        )
        fixtures.add_ingredient_component(
            api,
            sauce_recipe["id"],
            oil["id"],
            ep_quantity_base_units=100,
            sequence_no=2,
        )
        sauce_recipe = fixtures.rollup(api, sauce_recipe["id"])
        fixtures.review_and_activate_recipe(api, sauce_recipe["id"])

        melt = fixtures.create_recipe(
            api,
            code="PLATE-MELT",
            name="Patty Melt",
            recipe_type=RecipeType.PLATED,
            base_uom=BaseUom.EACH,
            batch_yield_base_units=5,
            portions_per_batch=5,
        )
        beef_component = fixtures.add_ingredient_component(
            api, melt["id"], beef["id"], ep_quantity_base_units=1000, sequence_no=1
        )
        cheddar_component = fixtures.add_ingredient_component(
            api, melt["id"], cheddar["id"], ep_quantity_base_units=100, sequence_no=2
        )
        sauce_line = fixtures.add_sub_recipe_component(
            api,
            melt["id"],
            sauce_recipe["id"],
            ep_quantity_base_units=500,
            sequence_no=3,
        )
        return {
            "feed": published_feed,
            "sauce_recipe": sauce_recipe,
            "sauce_component": sauce_component,
            "melt": melt,
            "beef_component": beef_component,
            "cheddar_component": cheddar_component,
            "sauce_line": sauce_line,
        }

    def test_trim_and_shrink_chain_rounds_the_purchase_quantity_up(
        self, api: ApiClient
    ) -> None:
        """A 1000-gram specification on a 6800 net yield buys 1471 grams.

        PRD 3.3: "multiply `ep_quantity_base_units` by 10000, divide by the
        ingredient's `net_yield_bps`, and round the quotient *up* to the next
        whole base unit whenever there is any remainder"

        Design: Difficulty/combinatorial_formula/component_extended_costs_rounded_then_summed_on_plate_melt_rollup
        """
        world = self._patty_melt(api)

        assert_recipe_component(
            world["beef_component"],
            ep_quantity_base_units=1000,
            ap_quantity_base_units=ceil_div(1000 * 10000, 6800),
        )
        assert_fields(world["beef_component"], ap_quantity_base_units=1471)
        assert_recipe_component(
            world["sauce_component"],
            ep_quantity_base_units=1900,
            ap_quantity_base_units=2000,
        )
        assert_fields(world["feed"], line_count=4)

    def test_each_extended_cost_is_rounded_before_it_is_summed(
        self, api: ApiClient
    ) -> None:
        """The three components round to 12485340, 970018 and 1572079.

        PRD 3.3: "each component's extended cost is rounded to whole
        micro-dollars first, and the already-rounded values are then added"

        Design: Difficulty/combinatorial_formula/component_extended_costs_rounded_then_summed_on_plate_melt_rollup
        """
        world = self._patty_melt(api)

        fixtures.rollup(api, world["melt"]["id"], basis=CostBasis.LATEST_PUBLISHED)

        assert_recipe_component(
            get_success_data(api.get_recipe_component(world["beef_component"]["id"])),
            extended_cost_micros=round_half_up(1471 * 38_500_000, 4536),
            unit_cost_micros_used=38_500_000,
            pack_base_units_snapshot=4536,
        )
        assert_recipe_component(
            get_success_data(
                api.get_recipe_component(world["cheddar_component"]["id"])
            ),
            extended_cost_micros=970_018,
        )
        assert_fields(
            get_success_data(api.get_recipe_component(world["beef_component"]["id"])),
            extended_cost_micros=12_485_340,
        )

    def test_sub_recipe_line_costs_from_the_child_batch_and_its_yield(
        self, api: ApiClient
    ) -> None:
        """The sauce line's exact 1572078.5 rounds away from zero.

        PRD 3.3: "the extended cost is then `ep_quantity_base_units`
        multiplied by the child's `batch_cost_micros`, divided by the child's
        `batch_yield_base_units`, rounded half up"

        Design: Difficulty/combinatorial_formula/component_extended_costs_rounded_then_summed_on_plate_melt_rollup
        """
        world = self._patty_melt(api)
        assert world["sauce_recipe"]["batch_cost_micros"] == 6_288_314

        fixtures.rollup(api, world["melt"]["id"])

        assert_recipe_component(
            get_success_data(api.get_recipe_component(world["sauce_line"]["id"])),
            unit_cost_micros_used=6_288_314,
            pack_base_units_snapshot=2000,
            extended_cost_micros=round_half_up(500 * 6_288_314, 2000),
        )
        assert_fields(
            get_success_data(api.get_recipe_component(world["sauce_line"]["id"])),
            extended_cost_micros=1_572_079,
        )

    def test_batch_cost_is_the_sum_of_rounded_extended_costs(
        self, api: ApiClient
    ) -> None:
        """15027437, one micro above the round-once-at-the-end total.

        PRD 3.3: "Accumulating the exact fractional products and rounding once
        at the end is explicitly *not* the specification, and the two orders
        disagree whenever two or more components leave fractional remainders."

        Design: Difficulty/combinatorial_formula/component_extended_costs_rounded_then_summed_on_plate_melt_rollup
        """
        world = self._patty_melt(api)

        rolled = fixtures.rollup(api, world["melt"]["id"])

        assert_recipe(
            rolled,
            cost_state=CostState.FRESH,
            batch_cost_micros=12_485_340 + 970_018 + 1_572_079,
            portion_cost_micros=round_half_up(15_027_437, 5),
        )
        assert_fields(
            rolled, batch_cost_micros=15_027_437, portion_cost_micros=3_005_487
        )
        assert rolled["batch_cost_micros"] != 15_027_436, (
            "the exact rational total rounded once is one micro lower"
        )

    def test_allergens_and_depth_arrive_through_the_sub_recipe(
        self, api: ApiClient
    ) -> None:
        """Peanut reaches the plate only via the sauce; depth is one.

        PRD 3.3: "The `allergen_mask` is the bitwise union of every active
        ingredient component's own `allergen_mask` and every active sub-recipe
        component's child `allergen_mask`"

        Design: Difficulty/combinatorial_formula/component_extended_costs_rounded_then_summed_on_plate_melt_rollup
        """
        world = self._patty_melt(api)

        rolled = fixtures.rollup(api, world["melt"]["id"])

        assert_recipe(rolled, allergen_mask=1 | 8, depth=1, component_count=3)
        assert_fields(rolled, allergen_mask=9)


class TestCapReliefStepOrder:
    """The relief widens the cap only after the food cost has been measured."""

    @staticmethod
    def _two_targets(api: ApiClient):
        """Two live items, identical but for their food-cost ambition."""
        world = fixtures.grill_world_active_item(
            api, code="MI-GRILL-A", name="Grilled Cheese A", target_food_cost_bps=2000
        )
        item_b = fixtures.add_menu_item_to_world(
            api,
            world,
            code="MI-GRILL-B",
            name="Grilled Cheese B",
            target_food_cost_bps=3000,
        )
        return world["menu_item"], item_b

    def test_the_lower_target_earns_relief_and_the_proposal_is_accepted(
        self, api: ApiClient
    ) -> None:
        """2198 basis points beats a 2000 target, so the cap widens to 461.

        PRD 3.7: "**Step six** computes `effective_cap_price_cents`: the relief
        is 300 basis points when `projected_food_cost_bps` is strictly greater
        than the item's `target_food_cost_bps` and zero otherwise, and the
        effective cap is `market_cap_price_cents` multiplied by the sum of 10000
        and that relief, divided by 10000, rounded half up."

        Design: Difficulty/combinatorial_formula/market_cap_relief_applied_only_after_projected_food_cost_step
        """
        item_a, _ = self._two_targets(api)
        assert item_a["plate_cost_cents"] == 100

        proposal = fixtures.open_proposal(
            api, item_a["id"], proposed_price_cents=455
        )
        submitted = fixtures.submit_proposal(api, proposal["id"])

        assert_proposal(
            submitted,
            status=ProposalStatus.SUBMITTED,
            price_delta_bps=1375,
            projected_unit_delta_bps=-1650,
            baseline_units=1000,
            projected_units=835,
            projected_food_cost_bps=2198,
            market_cap_price_cents=448,
            effective_cap_price_cents=round_half_up(448 * 10_300, 10_000),
            projected_contribution_delta_cents=835 * 355 - 1000 * 300,
        )
        assert_fields(
            submitted,
            effective_cap_price_cents=461,
            projected_contribution_delta_cents=-3575,
        )

    def test_the_higher_target_keeps_the_unrelieved_cap_and_is_refused(
        self, api: ApiClient
    ) -> None:
        """The same 455-cent proposal breaches the 448-cent cap.

        PRD 3.7: "the cap comparison at submission is made against the relieved
        `effective_cap_price_cents`, never against the un-relieved
        `market_cap_price_cents`"

        Design: Difficulty/combinatorial_formula/market_cap_relief_applied_only_after_projected_food_cost_step
        """
        _, item_b = self._two_targets(api)

        proposal = get_success_data(
            api.create_proposal(
                factories.proposal_payload(
                    item_b["id"], proposed_price_cents=455
                ),
                RECIPE_DEVELOPER,
            ),
            201,
        )
        response = api.submit_proposal(proposal["id"], RECIPE_DEVELOPER)

        validate_error(response, ApiErrorId.MARKET_CAP_EXCEEDED)

    def test_the_food_cost_is_measured_against_the_proposed_price(
        self, api: ApiClient
    ) -> None:
        """2198 is 100 cents over 455, not over the 448-cent cap.

        PRD 3.7: "**Step five** computes `projected_food_cost_bps` as the item's
        `plate_cost_cents` multiplied by 10000, divided by `proposed_price_cents`,
        rounded half up — computed from the **proposed** price and never from any
        capped price."

        Design: Difficulty/combinatorial_formula/market_cap_relief_applied_only_after_projected_food_cost_step
        """
        item_a, _ = self._two_targets(api)

        submitted = fixtures.submitted_proposal(
            api, item_a["id"], proposed_price_cents=455
        )

        assert submitted["projected_food_cost_bps"] == round_half_up(
            100 * 10_000, 455
        )
        assert submitted["projected_food_cost_bps"] != round_half_up(
            100 * 10_000, 448
        )

    def test_the_refused_submission_writes_no_projection_and_no_price(
        self, api: ApiClient
    ) -> None:
        """A rejected submit leaves the proposal DRAFT and the item at 400.

        PRD 3.7: "The new proposal opens in `DRAFT` with `revision_round` 0,
        null `submitted_by_user_id`, `approved_by_user_id`,
        `last_revision_reason` and `applied_at`, and no projection at all —
        every projection field stays unset until submission."

        Design: Difficulty/combinatorial_formula/market_cap_relief_applied_only_after_projected_food_cost_step
        """
        _, item_b = self._two_targets(api)
        proposal = fixtures.open_proposal(
            api, item_b["id"], proposed_price_cents=455
        )

        api.submit_proposal(proposal["id"], RECIPE_DEVELOPER)

        after = get_success_data(api.get_proposal(proposal["id"]))
        assert_proposal(after, status=ProposalStatus.DRAFT, revision_round=0)
        assert_projections_unset(after)
        assert_menu_item(
            get_success_data(api.get_menu_item(item_b["id"])),
            current_price_cents=400,
            status=MenuItemStatus.ACTIVE,
        )

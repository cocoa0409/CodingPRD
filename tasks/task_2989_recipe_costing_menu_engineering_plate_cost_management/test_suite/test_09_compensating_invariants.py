"""Quantities that a paired operation is required to restore exactly.

The first pair restores money figures from explicit snapshots taken before the
change, with a deliberate roll-up in between so the restore is not a no-op; the
second conserves a bitmask and an energy roll-up with no snapshot anywhere.  In
both, the window in which the batch-cost identity is broken is marked by
`cost_state` and by nothing else.
"""

from test_helpers import (
    ApiClient,
    ApprovalStatus,
    BaseUom,
    ComponentStatus,
    CostState,
    MarginClass,
    MenuItemStatus,
    PropagationStatus,
    RecipeStatus,
    assert_fields,
    assert_menu_item,
    assert_recipe,
    assert_recipe_component,
    assert_spec_change_order,
    ceil_div,
    fixtures,
    get_success_data,
    round_half_up,
)


class TestSpecChangeRollbackRestoresTheBatchCostIdentity:
    """A quantity change, a roll-up, then the compensating rollback."""

    @staticmethod
    def _approved_and_rerolled(api: ApiClient):
        """An APPROVED order whose new specification has already been costed."""
        world = fixtures.grill_world_active_item(api)
        approved = fixtures.approved_qty_change(
            api,
            world["recipe"]["id"],
            world["component"]["id"],
            new_ep_quantity_base_units=600,
        )
        rerolled = fixtures.rollup(api, world["recipe"]["id"])
        world.update({"approved": approved, "rerolled": rerolled})
        return world

    def test_the_pre_change_identity_is_recorded_before_anything_moves(
        self, api: ApiClient
    ) -> None:
        """3880071 in the batch, 970018 per portion, 100 cents on the plate.

        PRD 3.6: "Before it changes anything, approval takes its snapshots:
        `pre_change_batch_cost_micros` from the recipe's `batch_cost_micros`,
        `pre_change_allergen_mask` from the recipe's `allergen_mask`,
        `pre_change_recipe_version` from the recipe's `version`, and
        `pre_change_ep_quantity_base_units` from the target component's
        `ep_quantity_base_units`"

        Design: Difficulty/compensating_invariant/spec_change_rollback_restores_the_batch_cost_identity_exactly
        """
        world = self._approved_and_rerolled(api)

        assert_recipe(
            world["recipe"],
            status=RecipeStatus.ACTIVE,
            batch_cost_micros=3_880_071,
            portion_cost_micros=970_018,
        )
        assert_menu_item(world["menu_item"], plate_cost_cents=100)
        assert_spec_change_order(
            world["approved"],
            approval_status=ApprovalStatus.APPROVED,
            pre_change_batch_cost_micros=3_880_071,
            pre_change_ep_quantity_base_units=400,
            pre_change_allergen_mask=1,
        )

    def test_the_roll_up_between_approve_and_rollback_moves_the_money(
        self, api: ApiClient
    ) -> None:
        """The new 600-gram specification costs 5820106 micros per batch.

        PRD 3.3: "For an `INGREDIENT` component, take `ap_quantity_base_units`
        (recomputed as the ceiling of `ep_quantity_base_units` multiplied by 10000
        and divided by the ingredient's `net_yield_bps`), multiply by
        `unit_cost_micros_used`, divide by `pack_base_units_snapshot`, and round
        half up to whole micro-dollars."

        Design: Difficulty/compensating_invariant/spec_change_rollback_restores_the_batch_cost_identity_exactly
        """
        world = self._approved_and_rerolled(api)

        assert_recipe(
            world["rerolled"],
            cost_state=CostState.FRESH,
            batch_cost_micros=round_half_up(600 * 22_000_000, 2268),
            portion_cost_micros=round_half_up(5_820_106, 4),
        )
        assert_fields(
            world["rerolled"],
            batch_cost_micros=5_820_106,
            portion_cost_micros=1_455_027,
        )

    def test_the_rollback_restores_the_specification_but_not_the_line_cost(
        self, api: ApiClient
    ) -> None:
        """The component goes back to 400 while keeping the 5820106 it was given.

        PRD 3.6: "For `COMPONENT_QTY` it writes `pre_change_ep_quantity_base_units`
        back onto the target component and recomputes `ap_quantity_base_units`
        from it."

        Design: Difficulty/compensating_invariant/spec_change_rollback_restores_the_batch_cost_identity_exactly
        """
        world = self._approved_and_rerolled(api)

        rolled_back = fixtures.rollback_change_order(api, world["approved"]["id"])

        assert_spec_change_order(
            rolled_back,
            approval_status=ApprovalStatus.ROLLED_BACK,
            propagation_status=PropagationStatus.NOT_STARTED,
        )
        assert_recipe_component(
            get_success_data(api.get_recipe_component(world["component"]["id"])),
            ep_quantity_base_units=400,
            ap_quantity_base_units=ceil_div(400 * 10_000, 10_000),
            extended_cost_micros=5_820_106,
            status=ComponentStatus.ACTIVE,
        )

    def test_the_restored_batch_cost_leaves_the_identity_broken_and_flagged(
        self, api: ApiClient
    ) -> None:
        """3880071 against a 5820106 component, with STALE as the only marker.

        PRD 3.6: "What rollback does *not* restore is the recipe's `cost_state`:
        the recipe is left `STALE`, because the version history it has been
        through means nobody has recomputed the figures since."

        Design: Difficulty/compensating_invariant/spec_change_rollback_restores_the_batch_cost_identity_exactly
        """
        world = self._approved_and_rerolled(api)

        fixtures.rollback_change_order(api, world["approved"]["id"])

        recipe = get_success_data(api.get_recipe(world["recipe"]["id"]))
        assert_recipe(
            recipe,
            cost_state=CostState.STALE,
            batch_cost_micros=3_880_071,
            portion_cost_micros=1_455_027,
            open_spec_change_count=0,
        )
        component = get_success_data(
            api.get_recipe_component(world["component"]["id"])
        )
        assert recipe["batch_cost_micros"] != component["extended_cost_micros"], (
            "the identity is unreconciled for exactly this window"
        )

    def test_the_nutrition_roll_up_is_recomputed_rather_than_restored(
        self, api: ApiClient
    ) -> None:
        """Energy and sodium come back from the component set, not a snapshot.

        PRD 3.6: "recomputes `component_count`, `kcal_per_portion_micros`,
        `sodium_mcg_per_portion` and `depth` from the restored component set"

        Design: Difficulty/compensating_invariant/spec_change_rollback_restores_the_batch_cost_identity_exactly
        """
        world = self._approved_and_rerolled(api)

        fixtures.rollback_change_order(api, world["approved"]["id"])

        assert_recipe(
            get_success_data(api.get_recipe(world["recipe"]["id"])),
            kcal_per_portion_micros=round_half_up(400 * 4_000_000, 4),
            sodium_mcg_per_portion=round_half_up(400 * 6200, 4),
            allergen_mask=1,
            component_count=1,
        )
        assert_fields(
            get_success_data(api.get_recipe(world["recipe"]["id"])),
            kcal_per_portion_micros=400_000_000,
            sodium_mcg_per_portion=620_000,
        )

    def test_the_menu_item_takes_the_restored_figures_and_goes_stale(
        self, api: ApiClient
    ) -> None:
        """Still 100 cents on the plate, but no longer trusted.

        PRD 3.6: "Every menu item of the rolled-back recipe has its
        `allergen_mask` and `sodium_mcg_per_portion` copied back from the restored
        recipe and flips `plate_cost_state` to `STALE`, `margin_class` to
        `UNCLASSIFIED` and `version` up by one"

        Design: Difficulty/compensating_invariant/spec_change_rollback_restores_the_batch_cost_identity_exactly
        """
        world = self._approved_and_rerolled(api)

        fixtures.rollback_change_order(api, world["approved"]["id"])

        assert_menu_item(
            get_success_data(api.get_menu_item(world["menu_item"]["id"])),
            status=MenuItemStatus.ACTIVE,
            plate_cost_state=CostState.STALE,
            plate_cost_cents=100,
            margin_class=MarginClass.UNCLASSIFIED,
            allergen_mask=1,
            sodium_mcg_per_portion=620_000,
        )

    def test_a_compensating_roll_up_closes_the_identity_with_no_drift(
        self, api: ApiClient
    ) -> None:
        """Every figure returns to precisely its pre-change value.

        PRD 3.6: "Rollback returns the cost basis to precisely the state the last
        roll-up produced; it does not invent one."

        Design: Difficulty/compensating_invariant/spec_change_rollback_restores_the_batch_cost_identity_exactly
        """
        world = self._approved_and_rerolled(api)
        fixtures.rollback_change_order(api, world["approved"]["id"])

        final = fixtures.rollup(api, world["recipe"]["id"])

        assert_recipe(
            final,
            cost_state=CostState.FRESH,
            batch_cost_micros=3_880_071,
            portion_cost_micros=970_018,
        )
        assert_recipe_component(
            get_success_data(api.get_recipe_component(world["component"]["id"])),
            extended_cost_micros=3_880_071,
        )
        assert final["batch_cost_micros"] == world["recipe"]["batch_cost_micros"]


class TestComponentAddThenDeleteConservesTheAllergenBitmask:
    """A peanut bit that arrives and leaves without a snapshot."""

    @staticmethod
    def _draft_grill_with_two_prices(api: ApiClient):
        """A DRAFT recipe carrying cheddar only, with oil priced and waiting."""
        cheddar = fixtures.create_cheddar(api)
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
        feed = fixtures.open_price_feed(api, feed_date="2026-07-01T00:00:00.000Z")
        for ingredient, pack_cost in ((cheddar, 22_000_000), (oil, 12_000_000)):
            fixtures.add_price_line(
                api,
                feed["id"],
                ingredient["id"],
                pack_cost_micros=pack_cost,
                effective_from="2026-07-01T00:00:00.000Z",
            )
        fixtures.publish_price_feed(api, feed["id"])
        recipe = fixtures.create_recipe(api)
        cheddar_component = fixtures.add_ingredient_component(
            api, recipe["id"], cheddar["id"], ep_quantity_base_units=400
        )
        recipe = fixtures.rollup(api, recipe["id"])
        return {
            "cheddar": cheddar,
            "oil": oil,
            "recipe": recipe,
            "cheddar_component": cheddar_component,
        }

    def test_the_starting_roll_up_carries_one_allergen_bit(
        self, api: ApiClient
    ) -> None:
        """Milk only, at 400000000 micro-kcal and 620000 micrograms per portion.

        PRD 3.3: "The reported `kcal_per_portion_micros` is the batch energy total
        divided by `portions_per_batch`, rounded half up, and
        `sodium_mcg_per_portion` is the batch sodium total divided by
        `portions_per_batch`, rounded half up."

        Design: Difficulty/compensating_invariant/component_add_then_delete_conserves_the_recipe_allergen_bitmask
        """
        world = self._draft_grill_with_two_prices(api)

        assert_recipe(
            world["recipe"],
            status=RecipeStatus.DRAFT,
            batch_cost_micros=3_880_071,
            allergen_mask=1,
            kcal_per_portion_micros=round_half_up(400 * 4_000_000, 4),
            sodium_mcg_per_portion=round_half_up(400 * 6200, 4),
            component_count=1,
        )
        assert_fields(
            world["recipe"],
            kcal_per_portion_micros=400_000_000,
            sodium_mcg_per_portion=620_000,
        )

    def test_the_add_unions_the_bitmask_without_any_cost_roll_up(
        self, api: ApiClient
    ) -> None:
        """Milk becomes milk-and-peanut, and the energy rises immediately.

        PRD 3.3: "Adding a component is a specification change, so it invalidates
        costs: the owning recipe recomputes `component_count`, `allergen_mask`,
        `kcal_per_portion_micros`, `sodium_mcg_per_portion` and `depth` from the
        new component set, sets its `cost_state` to `STALE` and increments its
        `version`"

        Design: Difficulty/compensating_invariant/component_add_then_delete_conserves_the_recipe_allergen_bitmask
        """
        world = self._draft_grill_with_two_prices(api)

        oil_component = fixtures.add_ingredient_component(
            api,
            world["recipe"]["id"],
            world["oil"]["id"],
            ep_quantity_base_units=50,
            sequence_no=2,
        )

        assert_recipe_component(oil_component, ap_quantity_base_units=50)
        assert_recipe(
            get_success_data(api.get_recipe(world["recipe"]["id"])),
            cost_state=CostState.STALE,
            allergen_mask=1 | 8,
            kcal_per_portion_micros=round_half_up(
                400 * 4_000_000 + 50 * 8_000_000, 4
            ),
            sodium_mcg_per_portion=620_000,
            component_count=2,
        )
        assert_fields(
            get_success_data(api.get_recipe(world["recipe"]["id"])),
            allergen_mask=9,
            kcal_per_portion_micros=500_000_000,
        )

    def test_the_two_component_roll_up_sums_to_the_larger_batch_cost(
        self, api: ApiClient
    ) -> None:
        """3880071 plus the oil line's 634249.

        PRD 3.3: "each component's extended cost is rounded to whole
        micro-dollars first, and the already-rounded values are then added"

        Design: Difficulty/compensating_invariant/component_add_then_delete_conserves_the_recipe_allergen_bitmask
        """
        world = self._draft_grill_with_two_prices(api)
        fixtures.add_ingredient_component(
            api,
            world["recipe"]["id"],
            world["oil"]["id"],
            ep_quantity_base_units=50,
            sequence_no=2,
        )

        rolled = fixtures.rollup(api, world["recipe"]["id"])

        assert_recipe(
            rolled,
            cost_state=CostState.FRESH,
            batch_cost_micros=3_880_071 + round_half_up(50 * 12_000_000, 946),
        )
        assert_fields(rolled, batch_cost_micros=4_514_320)

    def test_the_soft_delete_keeps_the_removed_lines_historical_cost(
        self, api: ApiClient
    ) -> None:
        """634249 survives on a REMOVED row instead of being zeroed.

        PRD 3.3: "A removed line keeps its historical `extended_cost_micros` for
        audit and contributes nothing to any future roll-up."

        Design: Difficulty/compensating_invariant/component_add_then_delete_conserves_the_recipe_allergen_bitmask
        """
        world = self._draft_grill_with_two_prices(api)
        oil_component = fixtures.add_ingredient_component(
            api,
            world["recipe"]["id"],
            world["oil"]["id"],
            ep_quantity_base_units=50,
            sequence_no=2,
        )
        fixtures.rollup(api, world["recipe"]["id"])

        removed = fixtures.remove_component(
            api, world["recipe"]["id"], oil_component["id"]
        )

        assert_recipe_component(
            removed,
            status=ComponentStatus.REMOVED,
            extended_cost_micros=round_half_up(50 * 12_000_000, 946),
        )
        assert_fields(removed, extended_cost_micros=634_249)
        assert removed["removed_at"] is not None

    def test_the_delete_recomputes_the_bitmask_from_the_survivors(
        self, api: ApiClient
    ) -> None:
        """Back to milk alone, while the money figure waits for a roll-up.

        PRD 3.3: "The owning recipe recomputes the same five derived fields from
        the remaining active components, goes `STALE` and bumps its `version`"

        Design: Difficulty/compensating_invariant/component_add_then_delete_conserves_the_recipe_allergen_bitmask
        """
        world = self._draft_grill_with_two_prices(api)
        oil_component = fixtures.add_ingredient_component(
            api,
            world["recipe"]["id"],
            world["oil"]["id"],
            ep_quantity_base_units=50,
            sequence_no=2,
        )
        fixtures.rollup(api, world["recipe"]["id"])

        fixtures.remove_component(api, world["recipe"]["id"], oil_component["id"])

        after = get_success_data(api.get_recipe(world["recipe"]["id"]))
        assert_recipe(
            after,
            cost_state=CostState.STALE,
            allergen_mask=1,
            kcal_per_portion_micros=400_000_000,
            sodium_mcg_per_portion=620_000,
            component_count=1,
            batch_cost_micros=4_514_320,
        )
        assert after["allergen_mask"] != 9, "the peanut bit is gone"

    def test_the_final_roll_up_returns_every_figure_to_its_pre_add_value(
        self, api: ApiClient
    ) -> None:
        """3880071 and 970018 again, with the REMOVED row contributing nothing.

        PRD 3.3: "`component_count` is by definition the number of components of
        the recipe whose `status` is `ACTIVE`."

        Design: Difficulty/compensating_invariant/component_add_then_delete_conserves_the_recipe_allergen_bitmask
        """
        world = self._draft_grill_with_two_prices(api)
        oil_component = fixtures.add_ingredient_component(
            api,
            world["recipe"]["id"],
            world["oil"]["id"],
            ep_quantity_base_units=50,
            sequence_no=2,
        )
        fixtures.rollup(api, world["recipe"]["id"])
        fixtures.remove_component(api, world["recipe"]["id"], oil_component["id"])

        final = fixtures.rollup(api, world["recipe"]["id"])

        assert_recipe(
            final,
            cost_state=CostState.FRESH,
            batch_cost_micros=3_880_071,
            portion_cost_micros=970_018,
            component_count=1,
        )
        assert_recipe_component(
            get_success_data(
                api.get_recipe_component(world["cheddar_component"]["id"])
            ),
            status=ComponentStatus.ACTIVE,
            extended_cost_micros=3_880_071,
        )
        assert_recipe_component(
            get_success_data(api.get_recipe_component(oil_component["id"])),
            status=ComponentStatus.REMOVED,
            extended_cost_micros=634_249,
        )

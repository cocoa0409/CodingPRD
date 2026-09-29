"""Endpoints whose interest is the shape of the operation itself.

A delete that is not a delete, a read that computes and persists nothing, one
collection under four orthogonal filters, an action legal from exactly one state
on one of two dimensions, and a link row that carries a frozen value copy.
"""

from test_helpers import (
    ALLERGEN_GLUTEN,
    ALLERGEN_MILK,
    ALLERGEN_PEANUT,
    CLOCK_EPOCH,
    MISSING_UUID,
    MISSING_UUID_BEEF,
    ApiClient,
    ApiErrorId,
    ApprovalStatus,
    BaseUom,
    ComponentStatus,
    ComponentType,
    CostBasis,
    CostState,
    MarginClass,
    MenuItemStatus,
    PropagationStatus,
    PropagationTarget,
    RecipeStatus,
    RegionCode,
    ReviewBasis,
    ReviewStatus,
    SyncState,
    assert_fields,
    assert_instant_equals,
    assert_menu_item,
    assert_mix_line,
    assert_page_meta,
    assert_period_review,
    assert_prep_guide,
    assert_recipe,
    assert_recipe_component,
    assert_spec_change_order,
    factories,
    fixtures,
    get_success_data,
    ids_of,
    micros_to_cents,
    plate_cost_micros,
    round_half_up,
    single_row,
    validate_error,
    validate_paginated,
    COST_ANALYST,
    RECIPE_DEVELOPER,
)

WHEAT_FLOUR = {
    "sku": "WHEAT-FLOUR",
    "name": "Bread Flour",
    "base_uom": BaseUom.GRAM,
    "pack_base_units": 22680,
    "trim_yield_bps": 10_000,
    "cook_shrink_bps": 0,
    "allergen_mask": ALLERGEN_GLUTEN,
    "kcal_per_base_unit_micros": 3_500_000,
    "sodium_mcg_per_base_unit": 20,
}
FLOUR_PACK_COST_MICROS = 12_000_000


class TestComponentRemovalIsASoftDelete:
    """The D of CRUD keeps the row, the history and the stale batch cost."""

    @staticmethod
    def _two_component_plate(api: ApiClient):
        """PLATE-TWO with cheddar and flour rolled up, plus an ACTIVE PLATE-ONE."""
        cheddar = fixtures.create_cheddar(api)
        flour = fixtures.create_ingredient(api, **WHEAT_FLOUR)
        feed = fixtures.open_price_feed(api)
        fixtures.add_price_line(
            api, feed["id"], cheddar["id"], pack_cost_micros=22_000_000
        )
        fixtures.add_price_line(
            api, feed["id"], flour["id"], pack_cost_micros=FLOUR_PACK_COST_MICROS
        )
        fixtures.publish_price_feed(api, feed["id"])

        recipe = fixtures.create_recipe(
            api, code="PLATE-TWO", name="Two Component Plate"
        )
        cheddar_component = fixtures.add_ingredient_component(
            api, recipe["id"], cheddar["id"], ep_quantity_base_units=400, sequence_no=1
        )
        flour_component = fixtures.add_ingredient_component(
            api, recipe["id"], flour["id"], ep_quantity_base_units=200, sequence_no=2
        )
        recipe = fixtures.rollup(api, recipe["id"])
        item = fixtures.create_menu_item(
            api,
            recipe["id"],
            code="MI-TWO",
            name="Two Component Dish",
            declared_allergen_mask=ALLERGEN_MILK | ALLERGEN_GLUTEN,
        )
        item = fixtures.plate_cost(api, item["id"])

        live = fixtures.create_recipe(
            api, code="PLATE-ONE", name="One Component Plate"
        )
        live_component = fixtures.add_ingredient_component(
            api, live["id"], cheddar["id"], ep_quantity_base_units=400, sequence_no=1
        )
        fixtures.rollup(api, live["id"])
        fixtures.review_and_activate_recipe(api, live["id"])
        return {
            "cheddar": cheddar,
            "flour": flour,
            "recipe": recipe,
            "cheddar_component": cheddar_component,
            "flour_component": flour_component,
            "menu_item": item,
            "live_recipe": live,
            "live_component": live_component,
        }

    CHEDDAR_EXTENDED_MICROS = 3_880_071
    FLOUR_EXTENDED_MICROS = 105_820

    def test_the_two_component_rollup_rounds_each_line_before_it_sums(
        self, api: ApiClient
    ) -> None:
        """Two remainders, and the contract pins the rounding order.

        PRD 3.3: "**The rounding order here is pinned to round-then-sum and is
        part of the contract:** each component's extended cost is rounded to whole
        micro-dollars first, and the already-rounded values are then added."

        Design: Corner/endpoints/component_delete_is_a_soft_remove_guarded_by_three_different_gates
        """
        world = self._two_component_plate(api)

        assert_recipe(
            world["recipe"],
            cost_state=CostState.FRESH,
            component_count=2,
            batch_cost_micros=round_half_up(400 * 22_000_000, 2268)
            + round_half_up(200 * FLOUR_PACK_COST_MICROS, 22680),
            portion_cost_micros=round_half_up(
                self.CHEDDAR_EXTENDED_MICROS + self.FLOUR_EXTENDED_MICROS, 4
            ),
        )
        assert_fields(
            world["recipe"], batch_cost_micros=3_985_891, portion_cost_micros=996_473
        )
        assert_recipe_component(
            get_success_data(api.get_recipe_component(world["flour_component"]["id"])),
            ap_quantity_base_units=200,
            unit_cost_micros_used=FLOUR_PACK_COST_MICROS,
            pack_base_units_snapshot=22680,
            extended_cost_micros=self.FLOUR_EXTENDED_MICROS,
        )

    def test_the_two_component_recipe_carries_both_allergens_and_both_nutrients(
        self, api: ApiClient
    ) -> None:
        """Milk from the cheddar, gluten from the flour, both per portion.

        PRD 3.3: "The reported `kcal_per_portion_micros` is the batch energy total
        divided by `portions_per_batch`, rounded half up, and
        `sodium_mcg_per_portion` is the batch sodium total divided by
        `portions_per_batch`, rounded half up."

        Design: Corner/endpoints/component_delete_is_a_soft_remove_guarded_by_three_different_gates
        """
        world = self._two_component_plate(api)

        assert_recipe(
            world["recipe"],
            allergen_mask=ALLERGEN_MILK | ALLERGEN_GLUTEN,
            kcal_per_portion_micros=round_half_up(
                400 * 4_000_000 + 200 * 3_500_000, 4
            ),
            sodium_mcg_per_portion=round_half_up(400 * 6200 + 200 * 20, 4),
        )
        assert_fields(
            world["recipe"],
            allergen_mask=5,
            kcal_per_portion_micros=575_000_000,
            sodium_mcg_per_portion=621_000,
        )

    def test_the_menu_item_prices_the_two_component_plate(
        self, api: ApiClient
    ) -> None:
        """103 cents of plate against a 400-cent price.

        PRD 3.5: "`plate_cost_cents` is `plate_cost_micros` divided by 10000,
        rounded half up. `food_cost_bps` is `plate_cost_cents` multiplied by 10000
        and divided by `current_price_cents`, rounded half up."

        Design: Corner/endpoints/component_delete_is_a_soft_remove_guarded_by_three_different_gates
        """
        world = self._two_component_plate(api)

        assert_menu_item(
            world["menu_item"],
            plate_cost_state=CostState.FRESH,
            plate_cost_micros=plate_cost_micros(996_473, RegionCode.MW),
            plate_cost_cents=micros_to_cents(1_031_648),
            food_cost_bps=round_half_up(103 * 10_000, 400),
            contribution_margin_cents=400 - 103,
        )
        assert_fields(
            world["menu_item"],
            plate_cost_cents=103,
            food_cost_bps=2_575,
            contribution_margin_cents=297,
        )

    def test_the_removed_row_survives_with_its_history(
        self, api: ApiClient
    ) -> None:
        """The response is the row itself, still holding its last extended cost.

        PRD 3.3: "The targeted line's `status` becomes `REMOVED` and its
        `removed_at` is stamped from the logical clock; the removed row is
        returned in the response. A removed line keeps its historical
        `extended_cost_micros` for audit and contributes nothing to any future
        roll-up."

        Design: Corner/endpoints/component_delete_is_a_soft_remove_guarded_by_three_different_gates
        """
        world = self._two_component_plate(api)

        removed = fixtures.remove_component(
            api, world["recipe"]["id"], world["flour_component"]["id"]
        )

        assert_recipe_component(
            removed,
            id=world["flour_component"]["id"],
            status=ComponentStatus.REMOVED,
            sequence_no=2,
            extended_cost_micros=self.FLOUR_EXTENDED_MICROS,
        )
        assert_instant_equals(removed["removed_at"], CLOCK_EPOCH, "removed_at")

    def test_the_removal_recomputes_the_counters_but_never_the_cost(
        self, api: ApiClient
    ) -> None:
        """Gluten drops out, the batch cost keeps a figure nothing now matches.

        PRD 3.3: "The owning recipe recomputes the same five derived fields from
        the remaining active components, goes `STALE` and bumps its `version`, and
        the same menu-item invalidation follows."

        Design: Corner/endpoints/component_delete_is_a_soft_remove_guarded_by_three_different_gates
        """
        world = self._two_component_plate(api)
        fixtures.remove_component(
            api, world["recipe"]["id"], world["flour_component"]["id"]
        )

        after = get_success_data(api.get_recipe(world["recipe"]["id"]))

        assert_recipe(
            after,
            component_count=1,
            allergen_mask=ALLERGEN_MILK,
            kcal_per_portion_micros=round_half_up(400 * 4_000_000, 4),
            sodium_mcg_per_portion=round_half_up(400 * 6200, 4),
            cost_state=CostState.STALE,
            batch_cost_micros=3_985_891,
        )
        assert_fields(
            after, kcal_per_portion_micros=400_000_000, sodium_mcg_per_portion=620_000
        )
        assert after["version"] > world["recipe"]["version"]

    def test_the_menu_item_is_invalidated_and_not_recomputed(
        self, api: ApiClient
    ) -> None:
        """The cascade marks the plate cost unknown; it does not price it again.

        PRD 3.3: "every menu item backed by that recipe flips its
        `plate_cost_state` to `STALE` with `margin_class` reset to
        `UNCLASSIFIED`."

        Design: Corner/endpoints/component_delete_is_a_soft_remove_guarded_by_three_different_gates
        """
        world = self._two_component_plate(api)
        fixtures.remove_component(
            api, world["recipe"]["id"], world["flour_component"]["id"]
        )

        item = get_success_data(api.get_menu_item(world["menu_item"]["id"]))

        assert_menu_item(
            item,
            plate_cost_state=CostState.STALE,
            margin_class=MarginClass.UNCLASSIFIED,
            plate_cost_cents=103,
            plate_cost_micros=1_031_648,
        )

    def test_removing_the_same_row_twice_is_a_conflict_not_a_second_delete(
        self, api: ApiClient
    ) -> None:
        """The row exists; it is simply no longer ACTIVE.

        PRD 3.3: "Targeting a line that is already `REMOVED` is refused with
        `ERR_COMPONENT_ALREADY_REMOVED`."

        Design: Corner/endpoints/component_delete_is_a_soft_remove_guarded_by_three_different_gates
        """
        world = self._two_component_plate(api)
        fixtures.remove_component(
            api, world["recipe"]["id"], world["flour_component"]["id"]
        )

        response = api.delete_recipe_component(
            world["flour_component"]["id"],
            factories.component_delete_params(
                fixtures.recipe_version(api, world["recipe"]["id"])
            ),
            RECIPE_DEVELOPER,
        )

        validate_error(response, ApiErrorId.COMPONENT_ALREADY_REMOVED, 409)

    def test_an_identifier_that_was_never_minted_is_a_not_found(
        self, api: ApiClient
    ) -> None:
        """A 404 rather than the 409 an existing removed row would earn.

        PRD 2.10: "A `recipe_component_id` in the path, or a
        `target_component_id` in the body, identifies an existing component —
        `ERR_COMPONENT_NOT_FOUND`, 404, on the component read, the component
        removal and specification-change-order creation."

        Design: Corner/endpoints/component_delete_is_a_soft_remove_guarded_by_three_different_gates
        """
        world = self._two_component_plate(api)

        response = api.delete_recipe_component(
            MISSING_UUID_BEEF,
            factories.component_delete_params(
                fixtures.recipe_version(api, world["recipe"]["id"])
            ),
            RECIPE_DEVELOPER,
        )

        validate_error(response, ApiErrorId.COMPONENT_NOT_FOUND, 404)

    def test_a_live_recipes_component_cannot_be_deleted_at_all(
        self, api: ApiClient
    ) -> None:
        """An ACTIVE recipe's specification is frozen against direct edits.

        PRD 3.3: "an attempt against an `ACTIVE` or `RETIRED` recipe is refused
        with `ERR_RECIPE_NOT_MUTABLE`"

        Design: Corner/endpoints/component_delete_is_a_soft_remove_guarded_by_three_different_gates
        """
        world = self._two_component_plate(api)
        live = get_success_data(api.get_recipe(world["live_recipe"]["id"]))
        assert_recipe(live, status=RecipeStatus.ACTIVE)

        response = api.delete_recipe_component(
            world["live_component"]["id"],
            factories.component_delete_params(live["version"]),
            RECIPE_DEVELOPER,
        )

        validate_error(response, ApiErrorId.RECIPE_NOT_MUTABLE, 409)
        assert_recipe_component(
            get_success_data(api.get_recipe_component(world["live_component"]["id"])),
            status=ComponentStatus.ACTIVE,
            removed_at=None,
        )

    def test_only_the_next_rollup_reconciles_the_cost_with_the_survivors(
        self, api: ApiClient
    ) -> None:
        """The single-component figure appears only when somebody re-costs.

        PRD 3.3: "The recipe's `batch_cost_micros` is the sum of
        `extended_cost_micros` over its active components, and
        `portion_cost_micros` is `batch_cost_micros` divided by
        `portions_per_batch`, rounded half up."

        Design: Corner/endpoints/component_delete_is_a_soft_remove_guarded_by_three_different_gates
        """
        world = self._two_component_plate(api)
        fixtures.remove_component(
            api, world["recipe"]["id"], world["flour_component"]["id"]
        )

        recosted = fixtures.rollup(api, world["recipe"]["id"])

        assert_recipe(
            recosted,
            cost_state=CostState.FRESH,
            batch_cost_micros=self.CHEDDAR_EXTENDED_MICROS,
            portion_cost_micros=round_half_up(self.CHEDDAR_EXTENDED_MICROS, 4),
        )
        assert_fields(
            recosted, batch_cost_micros=3_880_071, portion_cost_micros=970_018
        )


class TestTheAllergenNutritionReadRecomputesLive:
    """A computed read is the only live view of a parent nobody notified."""

    CHILD_BATCH_COST_MICROS = 1_268_499
    SUB_COMPONENT_EXTENDED_MICROS = 634_250
    PARENT_BATCH_COST_MICROS = 4_514_321

    @staticmethod
    def _a_parent_over_its_child(api: ApiClient):
        """PLATE-DEEP over SUB-OIL, both DRAFT and both freshly rolled up."""
        oil = fixtures.create_peanut_oil(api)
        cheddar = fixtures.create_cheddar(api)
        flour = fixtures.create_ingredient(api, **WHEAT_FLOUR)
        feed = fixtures.open_price_feed(api)
        for ingredient_id, pack_cost_micros in (
            (oil["id"], 12_000_000),
            (cheddar["id"], 22_000_000),
            (flour["id"], FLOUR_PACK_COST_MICROS),
        ):
            fixtures.add_price_line(
                api, feed["id"], ingredient_id, pack_cost_micros=pack_cost_micros
            )
        fixtures.publish_price_feed(api, feed["id"])

        child = fixtures.create_sub_recipe(
            api,
            code="SUB-OIL",
            name="Fry Oil Base",
            base_uom=BaseUom.MILLILITER,
            batch_yield_base_units=1000,
            portions_per_batch=10,
        )
        fixtures.add_ingredient_component(
            api, child["id"], oil["id"], ep_quantity_base_units=100, sequence_no=1
        )
        child = fixtures.rollup(api, child["id"])

        parent = fixtures.create_recipe(
            api, code="PLATE-DEEP", name="Deep Fried Plate"
        )
        fixtures.add_ingredient_component(
            api, parent["id"], cheddar["id"], ep_quantity_base_units=400, sequence_no=1
        )
        sub_component = fixtures.add_sub_recipe_component(
            api, parent["id"], child["id"], ep_quantity_base_units=500, sequence_no=2
        )
        parent = fixtures.rollup(api, parent["id"])
        return {
            "oil": oil,
            "cheddar": cheddar,
            "flour": flour,
            "child": child,
            "parent": parent,
            "sub_component": sub_component,
        }

    @staticmethod
    def _widen_the_childs_allergens(api: ApiClient, world):
        """Add gluten to the child, which is the edit the parent never hears of."""
        return fixtures.add_ingredient_component(
            api,
            world["child"]["id"],
            world["flour"]["id"],
            ep_quantity_base_units=200,
            sequence_no=2,
        )

    def test_the_sub_recipe_line_costs_from_the_childs_batch(
        self, api: ApiClient
    ) -> None:
        """The child's batch cost becomes the parent line's unit cost.

        PRD 3.3: "For a `SUB_RECIPE` component, `ap_quantity_base_units` equals
        `ep_quantity_base_units`, `unit_cost_micros_used` is set to the child
        recipe's `batch_cost_micros` and `pack_base_units_snapshot` to the child's
        `batch_yield_base_units`; the extended cost is then
        `ep_quantity_base_units` multiplied by the child's `batch_cost_micros`,
        divided by the child's `batch_yield_base_units`, rounded half up."

        Design: Corner/endpoints/the_allergen_nutrition_read_recomputes_live_and_persists_nothing
        """
        world = self._a_parent_over_its_child(api)

        assert_recipe(
            world["child"],
            cost_state=CostState.FRESH,
            batch_cost_micros=round_half_up(100 * 12_000_000, 946),
            allergen_mask=ALLERGEN_PEANUT,
            kcal_per_portion_micros=round_half_up(100 * 8_000_000, 10),
        )
        assert_fields(
            world["child"],
            batch_cost_micros=self.CHILD_BATCH_COST_MICROS,
            kcal_per_portion_micros=80_000_000,
        )
        assert_recipe_component(
            get_success_data(api.get_recipe_component(world["sub_component"]["id"])),
            component_type=ComponentType.SUB_RECIPE,
            ingredient_id=None,
            ap_quantity_base_units=500,
            unit_cost_micros_used=self.CHILD_BATCH_COST_MICROS,
            pack_base_units_snapshot=1000,
            extended_cost_micros=round_half_up(
                500 * self.CHILD_BATCH_COST_MICROS, 1000
            ),
        )
        assert_fields(
            get_success_data(api.get_recipe_component(world["sub_component"]["id"])),
            extended_cost_micros=self.SUB_COMPONENT_EXTENDED_MICROS,
        )

    def test_the_parent_inherits_an_allergen_it_never_references(
        self, api: ApiClient
    ) -> None:
        """Peanut arrives through the sub-recipe and nowhere else.

        PRD 3.3: "The `allergen_mask` is the bitwise union of every active
        ingredient component's own `allergen_mask` and every active sub-recipe
        component's child `allergen_mask` — which means a plated recipe inherits
        allergens it never references directly"

        Design: Corner/endpoints/the_allergen_nutrition_read_recomputes_live_and_persists_nothing
        """
        world = self._a_parent_over_its_child(api)

        assert_recipe(
            world["parent"],
            cost_state=CostState.FRESH,
            depth=1,
            component_count=2,
            allergen_mask=ALLERGEN_MILK | ALLERGEN_PEANUT,
            batch_cost_micros=self.CHEDDAR_PLUS_SUB,
            portion_cost_micros=round_half_up(self.PARENT_BATCH_COST_MICROS, 4),
            kcal_per_portion_micros=round_half_up(
                400 * 4_000_000 + round_half_up(500 * 800_000_000, 1000), 4
            ),
            sodium_mcg_per_portion=round_half_up(400 * 6200, 4),
        )
        assert_fields(
            world["parent"],
            allergen_mask=9,
            batch_cost_micros=4_514_321,
            portion_cost_micros=1_128_580,
            kcal_per_portion_micros=500_000_000,
            sodium_mcg_per_portion=620_000,
        )

    CHEDDAR_PLUS_SUB = 3_880_071 + 634_250

    def test_the_child_edit_recomputes_the_child_alone(
        self, api: ApiClient
    ) -> None:
        """Gluten, energy and sodium all move on the child's own row.

        PRD 3.3: "Adding a component is a specification change, so it invalidates
        costs: the owning recipe recomputes `component_count`, `allergen_mask`,
        `kcal_per_portion_micros`, `sodium_mcg_per_portion` and `depth` from the
        new component set, sets its `cost_state` to `STALE` and increments its
        `version`"

        Design: Corner/endpoints/the_allergen_nutrition_read_recomputes_live_and_persists_nothing
        """
        world = self._a_parent_over_its_child(api)
        self._widen_the_childs_allergens(api, world)

        child = get_success_data(api.get_recipe(world["child"]["id"]))

        assert_recipe(
            child,
            component_count=2,
            allergen_mask=ALLERGEN_PEANUT | ALLERGEN_GLUTEN,
            kcal_per_portion_micros=round_half_up(
                100 * 8_000_000 + 200 * 3_500_000, 10
            ),
            sodium_mcg_per_portion=round_half_up(200 * 20, 10),
            cost_state=CostState.STALE,
            batch_cost_micros=self.CHILD_BATCH_COST_MICROS,
        )
        assert_fields(
            child,
            allergen_mask=12,
            kcal_per_portion_micros=150_000_000,
            sodium_mcg_per_portion=400,
        )

    def test_the_parents_persisted_profile_is_left_behind(
        self, api: ApiClient
    ) -> None:
        """The parent's allergen profile is stale data its own record still shows.

        Only the *owning* recipe recomputes the derived profile, so the parent's
        persisted `allergen_mask`, `kcal_per_portion_micros` and
        `sodium_mcg_per_portion` still describe the pre-edit child.

        PRD 3.3: "the owning recipe recomputes `component_count`,
        `allergen_mask`, `kcal_per_portion_micros`, `sodium_mcg_per_portion` and
        `depth` from the new component set, sets its `cost_state` to `STALE` and
        increments its `version`; and every menu item backed by that recipe flips
        its `plate_cost_state` to `STALE` with `margin_class` reset to
        `UNCLASSIFIED`."

        The parent's own `cost_state` does move, because invalidation travels
        upward. PRD 2.6: "A recipe holding an active sub-recipe component whose
        child recipe just went stale is itself stale, and that reasoning repeats
        transitively up the graph." PRD 2.4 makes that cascade hop a mutation:
        "Every cascade hop described anywhere in this document increments the
        `version` of every row it touches."

        Design: Corner/endpoints/the_allergen_nutrition_read_recomputes_live_and_persists_nothing
        """
        world = self._a_parent_over_its_child(api)
        self._widen_the_childs_allergens(api, world)

        parent = get_success_data(api.get_recipe(world["parent"]["id"]))

        assert_recipe(
            parent,
            allergen_mask=9,
            kcal_per_portion_micros=500_000_000,
            sodium_mcg_per_portion=620_000,
            cost_state=CostState.STALE,
            version=world["parent"]["version"] + 1,
        )

    def test_the_computed_read_disagrees_with_the_persisted_record(
        self, api: ApiClient
    ) -> None:
        """Walking the live graph finds the gluten the record does not carry.

        PRD 3.3: "That read recalculates all of it from the live active component
        graph and returns it in the recipe's own response shape, but it persists
        nothing whatsoever and it works even when `cost_state` is `STALE`"

        Design: Corner/endpoints/the_allergen_nutrition_read_recomputes_live_and_persists_nothing
        """
        world = self._a_parent_over_its_child(api)
        self._widen_the_childs_allergens(api, world)

        live = get_success_data(
            api.get_recipe_allergen_nutrition(world["parent"]["id"], COST_ANALYST)
        )

        assert_recipe(
            live,
            allergen_mask=ALLERGEN_MILK | ALLERGEN_PEANUT | ALLERGEN_GLUTEN,
            kcal_per_portion_micros=round_half_up(
                400 * 4_000_000 + round_half_up(500 * 1_500_000_000, 1000), 4
            ),
            sodium_mcg_per_portion=round_half_up(
                400 * 6200 + round_half_up(500 * 4000, 1000), 4
            ),
            depth=1,
            component_count=2,
            batch_cost_micros=self.PARENT_BATCH_COST_MICROS,
        )
        assert_fields(
            live,
            allergen_mask=13,
            kcal_per_portion_micros=587_500_000,
            sodium_mcg_per_portion=620_500,
        )

    def test_the_computed_read_writes_nothing_at_all(
        self, api: ApiClient
    ) -> None:
        """After the read the record still says nine, and the version has not moved.

        PRD 3.3: "but it persists nothing whatsoever and it works even when
        `cost_state` is `STALE` — which is precisely how a caller distinguishes
        what the graph says today from what the last roll-up persisted."

        Design: Corner/endpoints/the_allergen_nutrition_read_recomputes_live_and_persists_nothing
        """
        world = self._a_parent_over_its_child(api)
        self._widen_the_childs_allergens(api, world)
        before = get_success_data(api.get_recipe(world["parent"]["id"]))

        api.get_recipe_allergen_nutrition(world["parent"]["id"], COST_ANALYST)
        after = get_success_data(api.get_recipe(world["parent"]["id"]))

        assert_recipe(
            after,
            allergen_mask=9,
            kcal_per_portion_micros=500_000_000,
            sodium_mcg_per_portion=620_000,
            version=before["version"],
        )

    def test_the_rollup_that_would_fix_the_parent_refuses_to_run(
        self, api: ApiClient
    ) -> None:
        """Children are never recomputed implicitly, so the parent cannot re-cost.

        PRD 3.3: "Every active sub-recipe component's child recipe must already
        have `cost_state` `FRESH` *and* a `cost_basis` equal to the basis this
        roll-up was asked for; if any child fails either test the whole call fails
        with `ERR_COST_STALE`."

        Design: Corner/endpoints/the_allergen_nutrition_read_recomputes_live_and_persists_nothing
        """
        world = self._a_parent_over_its_child(api)
        self._widen_the_childs_allergens(api, world)

        response = api.cost_rollup_recipe(
            world["parent"]["id"],
            factories.rollup_payload(basis=CostBasis.LATEST_PUBLISHED),
            COST_ANALYST,
        )

        validate_error(response, ApiErrorId.COST_STALE, 409)


class TestComponentListingFiltersAndPaging:
    """One shared collection, four orthogonal filters and the page envelope."""

    @staticmethod
    def _four_component_rows(api: ApiClient):
        """Two rows on the child and two on the parent, none of them costed."""
        oil = fixtures.create_peanut_oil(api)
        cheddar = fixtures.create_cheddar(api)
        flour = fixtures.create_ingredient(api, **WHEAT_FLOUR)

        child = fixtures.create_sub_recipe(
            api,
            code="SUB-OIL",
            name="Fry Oil Base",
            base_uom=BaseUom.MILLILITER,
            batch_yield_base_units=1000,
            portions_per_batch=10,
        )
        oil_component = fixtures.add_ingredient_component(
            api, child["id"], oil["id"], ep_quantity_base_units=100, sequence_no=1
        )
        flour_component = fixtures.add_ingredient_component(
            api, child["id"], flour["id"], ep_quantity_base_units=200, sequence_no=2
        )

        parent = fixtures.create_recipe(
            api, code="PLATE-DEEP", name="Deep Fried Plate"
        )
        cheddar_component = fixtures.add_ingredient_component(
            api, parent["id"], cheddar["id"], ep_quantity_base_units=400, sequence_no=1
        )
        sub_component = fixtures.add_sub_recipe_component(
            api, parent["id"], child["id"], ep_quantity_base_units=500, sequence_no=2
        )
        return {
            "cheddar": cheddar,
            "child": child,
            "parent": parent,
            "oil_component": oil_component,
            "flour_component": flour_component,
            "cheddar_component": cheddar_component,
            "sub_component": sub_component,
        }

    def test_the_owner_filter_returns_the_rows_in_sequence_order(
        self, api: ApiClient
    ) -> None:
        """Both of the child's lines, oldest sequence first.

        PRD 3.3: "The list can be narrowed by owning recipe with `recipe_id`, by
        `child_recipe_id` to discover which recipes consume a given sub-recipe, by
        `ingredient_id` to discover which recipes consume a given ingredient, and
        by `status`; it is ordered `sequence_no` ascending and then `created_at`
        ascending."

        Design: Corner/endpoints/component_listing_filters_by_owner_child_ingredient_and_status_under_pagination
        """
        world = self._four_component_rows(api)

        rows, meta = validate_paginated(
            api.list_recipe_components(
                {"recipe_id": world["child"]["id"], "limit": 10, "offset": 0},
                COST_ANALYST,
            )
        )

        assert ids_of(rows) == [
            world["oil_component"]["id"],
            world["flour_component"]["id"],
        ]
        assert_page_meta(meta, total_count=2, limit=10, offset=0, has_more=False)

    def test_offset_paging_walks_that_same_order_one_row_at_a_time(
        self, api: ApiClient
    ) -> None:
        """total_count counts the filtered set, not the page.

        PRD 2.3: "List responses carry `limit`, `offset`, `total_count` and
        `has_more` inside the `meta` object of the envelope, where `total_count` is
        the number of rows matching the request's filters before pagination is
        applied and `has_more` states whether any matching row remains beyond the
        returned page."

        Design: Corner/endpoints/component_listing_filters_by_owner_child_ingredient_and_status_under_pagination
        """
        world = self._four_component_rows(api)

        first_rows, first_meta = validate_paginated(
            api.list_recipe_components(
                {"recipe_id": world["child"]["id"], "limit": 1, "offset": 0},
                COST_ANALYST,
            )
        )
        second_rows, second_meta = validate_paginated(
            api.list_recipe_components(
                {"recipe_id": world["child"]["id"], "limit": 1, "offset": 1},
                COST_ANALYST,
            )
        )

        assert_recipe_component(
            single_row(first_rows), id=world["oil_component"]["id"], sequence_no=1
        )
        assert_page_meta(first_meta, total_count=2, limit=1, offset=0, has_more=True)
        assert_recipe_component(
            single_row(second_rows), id=world["flour_component"]["id"], sequence_no=2
        )
        assert_page_meta(second_meta, total_count=2, limit=1, offset=1, has_more=False)

    def test_the_child_recipe_filter_answers_who_consumes_the_sub_recipe(
        self, api: ApiClient
    ) -> None:
        """The reverse question: the parent's line, never the child's own two.

        PRD 3.3: "by `child_recipe_id` to discover which recipes consume a given
        sub-recipe"

        Design: Corner/endpoints/component_listing_filters_by_owner_child_ingredient_and_status_under_pagination
        """
        world = self._four_component_rows(api)

        rows, meta = validate_paginated(
            api.list_recipe_components(
                {"child_recipe_id": world["child"]["id"], "limit": 10, "offset": 0},
                COST_ANALYST,
            )
        )

        assert_recipe_component(
            single_row(rows, meta),
            id=world["sub_component"]["id"],
            recipe_id=world["parent"]["id"],
            child_recipe_id=world["child"]["id"],
        )

    def test_the_ingredient_filter_skips_the_sub_recipe_line(
        self, api: ApiClient
    ) -> None:
        """A sub-recipe line has no ingredient at all, so it cannot match.

        PRD 3.3: "An `INGREDIENT` line must carry `ingredient_id` and must leave
        `child_recipe_id` null; a `SUB_RECIPE` line must carry `child_recipe_id`
        and must leave `ingredient_id` null."

        Design: Corner/endpoints/component_listing_filters_by_owner_child_ingredient_and_status_under_pagination
        """
        world = self._four_component_rows(api)

        rows, meta = validate_paginated(
            api.list_recipe_components(
                {"ingredient_id": world["cheddar"]["id"], "limit": 10, "offset": 0},
                COST_ANALYST,
            )
        )

        assert_recipe_component(
            single_row(rows, meta),
            id=world["cheddar_component"]["id"],
            component_type=ComponentType.INGREDIENT,
            child_recipe_id=None,
        )

    def test_the_status_filter_is_what_makes_a_removed_row_observable(
        self, api: ApiClient
    ) -> None:
        """The soft-removed row stays in the collection under its own status.

        PRD 3.3: "Targeting a line that is already `REMOVED` is refused with
        `ERR_COMPONENT_ALREADY_REMOVED`. `component_count` is by definition the
        number of components of the recipe whose `status` is `ACTIVE`."

        Design: Corner/endpoints/component_listing_filters_by_owner_child_ingredient_and_status_under_pagination
        """
        world = self._four_component_rows(api)
        removed = fixtures.remove_component(
            api, world["parent"]["id"], world["cheddar_component"]["id"]
        )
        assert_recipe_component(removed, status=ComponentStatus.REMOVED)

        active_rows, active_meta = validate_paginated(
            api.list_recipe_components(
                {
                    "recipe_id": world["parent"]["id"],
                    "status": ComponentStatus.ACTIVE,
                    "limit": 10,
                    "offset": 0,
                },
                COST_ANALYST,
            )
        )
        removed_rows, removed_meta = validate_paginated(
            api.list_recipe_components(
                {
                    "recipe_id": world["parent"]["id"],
                    "status": ComponentStatus.REMOVED,
                    "limit": 10,
                    "offset": 0,
                },
                COST_ANALYST,
            )
        )

        assert_recipe_component(
            single_row(active_rows, active_meta), id=world["sub_component"]["id"]
        )
        assert_recipe_component(
            single_row(removed_rows, removed_meta),
            id=world["cheddar_component"]["id"],
        )

    def test_the_filters_and_together(self, api: ApiClient) -> None:
        """No row is simultaneously an ingredient line and a sub-recipe line.

        PRD 3.3: "The list can be narrowed by owning recipe with `recipe_id`, by
        `child_recipe_id` to discover which recipes consume a given sub-recipe, by
        `ingredient_id` to discover which recipes consume a given ingredient, and
        by `status`"

        Design: Corner/endpoints/component_listing_filters_by_owner_child_ingredient_and_status_under_pagination
        """
        world = self._four_component_rows(api)

        rows, meta = validate_paginated(
            api.list_recipe_components(
                {
                    "recipe_id": world["parent"]["id"],
                    "child_recipe_id": world["child"]["id"],
                    "ingredient_id": world["cheddar"]["id"],
                    "limit": 10,
                    "offset": 0,
                },
                COST_ANALYST,
            )
        )

        assert rows == []
        assert_page_meta(meta, total_count=0, has_more=False)


class TestPropagationIsConditionalOnTheApprovalDimension:
    """One action, two dimensions, and each target drains exactly once."""

    @staticmethod
    def _a_draft_quantity_change(api: ApiClient):
        """PLATE-GRILL live with revision 1 of its guide, and a DRAFT order on it."""
        world = fixtures.grill_world_active_recipe(api)
        world["guide"] = fixtures.sole_prep_guide(api, world["recipe"]["id"])
        world["order"] = fixtures.open_qty_change(
            api,
            world["recipe"]["id"],
            world["component"]["id"],
            new_ep_quantity_base_units=500,
        )
        return world

    @staticmethod
    def _an_approved_quantity_change(api: ApiClient):
        """The same order carried through submission and approval."""
        world = TestPropagationIsConditionalOnTheApprovalDimension._a_draft_quantity_change(
            api
        )
        fixtures.submit_change_order(api, world["order"]["id"])
        world["order"] = fixtures.approve_change_order(api, world["order"]["id"])
        return world

    def test_activation_minted_the_first_revision_of_the_guide(
        self, api: ApiClient
    ) -> None:
        """Revision 1, CURRENT, with the three figures frozen as they stand.

        PRD 3.4: "activation mints one with `revision_no` 1 and `sync_state`
        `CURRENT`, freezing three figures from the recipe as it now stands —
        `batch_yield_base_units_snapshot`, `portions_per_batch_snapshot` and
        `component_count_snapshot` — and recording `synced_spec_version` as the
        recipe's `version` *after* this transition's increment."

        Design: Corner/endpoints/propagation_is_a_conditional_action_on_the_approval_dimension_and_each_target_drains_once
        """
        world = self._a_draft_quantity_change(api)

        assert_prep_guide(
            world["guide"],
            recipe_id=world["recipe"]["id"],
            revision_no=1,
            sync_state=SyncState.CURRENT,
            component_count_snapshot=1,
            batch_yield_base_units_snapshot=4,
            portions_per_batch_snapshot=4,
            synced_spec_version=world["recipe"]["version"],
        )

    def test_the_new_order_starts_at_the_foot_of_both_dimensions(
        self, api: ApiClient
    ) -> None:
        """DRAFT on the approval axis, NOT_STARTED on the propagation axis.

        PRD 3.6: "The new order opens with `approval_status` `DRAFT`,
        `propagation_status` `NOT_STARTED`, and null `submitted_by_user_id`,
        `approved_by_user_id`, `rejection_reason`, `created_component_id`,
        `approved_at` and every `pre_change_` snapshot."

        Design: Corner/endpoints/propagation_is_a_conditional_action_on_the_approval_dimension_and_each_target_drains_once
        """
        world = self._a_draft_quantity_change(api)

        assert_spec_change_order(
            world["order"],
            approval_status=ApprovalStatus.DRAFT,
            propagation_status=PropagationStatus.NOT_STARTED,
            submitted_by_user_id=None,
            approved_by_user_id=None,
            approved_at=None,
            created_component_id=None,
            pre_change_ep_quantity_base_units=None,
        )

    def test_propagating_a_draft_order_is_refused(self, api: ApiClient) -> None:
        """The propagation axis only ever advances from APPROVED.

        PRD 3.6: "The order's `approval_status` must be `APPROVED`, otherwise
        `ERR_SCO_INVALID_STATE`."

        Design: Corner/endpoints/propagation_is_a_conditional_action_on_the_approval_dimension_and_each_target_drains_once
        """
        world = self._a_draft_quantity_change(api)

        response = api.propagate_spec_change_order(
            world["order"]["id"],
            factories.propagate_payload(PropagationTarget.PREP_GUIDE),
            COST_ANALYST,
        )

        validate_error(response, ApiErrorId.SCO_INVALID_STATE, 409)

    def test_propagating_a_pending_order_is_refused_with_the_same_error(
        self, api: ApiClient
    ) -> None:
        """One step further along the approval axis, and still not APPROVED.

        PRD 3.6: "**Submission** moves `DRAFT` to `PENDING` and is the same
        `RecipeDeveloper`'s act."

        Design: Corner/endpoints/propagation_is_a_conditional_action_on_the_approval_dimension_and_each_target_drains_once
        """
        world = self._a_draft_quantity_change(api)
        submitted = fixtures.submit_change_order(api, world["order"]["id"])
        assert_spec_change_order(submitted, approval_status=ApprovalStatus.PENDING)

        response = api.propagate_spec_change_order(
            world["order"]["id"],
            factories.propagate_payload(PropagationTarget.PREP_GUIDE),
            COST_ANALYST,
        )

        validate_error(response, ApiErrorId.SCO_INVALID_STATE, 409)

    def test_approval_flags_the_guide_without_reissuing_it(
        self, api: ApiClient
    ) -> None:
        """Approval enqueues the work; it does not perform it.

        PRD 3.6: "Hop 2 also enqueues the propagation work: it flips the recipe's
        prep guide `sync_state` to `OUT_OF_DATE`"

        Design: Corner/endpoints/propagation_is_a_conditional_action_on_the_approval_dimension_and_each_target_drains_once
        """
        world = self._an_approved_quantity_change(api)

        assert_spec_change_order(
            world["order"],
            approval_status=ApprovalStatus.APPROVED,
            propagation_status=PropagationStatus.NOT_STARTED,
        )
        assert_prep_guide(
            fixtures.sole_prep_guide(api, world["recipe"]["id"]),
            revision_no=1,
            sync_state=SyncState.OUT_OF_DATE,
        )

    def test_the_prep_guide_drain_reissues_the_kitchen_document(
        self, api: ApiClient
    ) -> None:
        """Revision two, CURRENT again, and the approval axis does not move.

        PRD 3.6: "The `PREP_GUIDE` target re-issues the kitchen document: the
        recipe's prep guide has its `sync_state` set to `CURRENT`, its
        `revision_no` incremented by one, its `batch_yield_base_units_snapshot`,
        `portions_per_batch_snapshot` and `component_count_snapshot` refreshed from
        the recipe as it now stands, and its `synced_spec_version` set to the
        recipe's current `version`."

        Design: Corner/endpoints/propagation_is_a_conditional_action_on_the_approval_dimension_and_each_target_drains_once
        """
        world = self._an_approved_quantity_change(api)
        recipe_version = fixtures.recipe_version(api, world["recipe"]["id"])

        drained = fixtures.propagate_change_order(
            api, world["order"]["id"], target=PropagationTarget.PREP_GUIDE
        )

        assert_spec_change_order(
            drained,
            approval_status=ApprovalStatus.APPROVED,
            propagation_status=PropagationStatus.PREP_GUIDE_SYNCED,
        )
        assert_prep_guide(
            fixtures.sole_prep_guide(api, world["recipe"]["id"]),
            revision_no=2,
            sync_state=SyncState.CURRENT,
            component_count_snapshot=1,
            batch_yield_base_units_snapshot=4,
            portions_per_batch_snapshot=4,
            synced_spec_version=recipe_version,
        )

    def test_the_prep_guide_target_drains_exactly_once(
        self, api: ApiClient
    ) -> None:
        """A second drain of the same target is refused.

        PRD 3.6: "The named target must not already be reflected in
        `propagation_status`, otherwise `ERR_PROPAGATION_ALREADY_SYNCED` — each
        target may be drained exactly once per order."

        Design: Corner/endpoints/propagation_is_a_conditional_action_on_the_approval_dimension_and_each_target_drains_once
        """
        world = self._an_approved_quantity_change(api)
        fixtures.propagate_change_order(
            api, world["order"]["id"], target=PropagationTarget.PREP_GUIDE
        )

        response = api.propagate_spec_change_order(
            world["order"]["id"],
            factories.propagate_payload(PropagationTarget.PREP_GUIDE),
            COST_ANALYST,
        )

        validate_error(response, ApiErrorId.PROPAGATION_ALREADY_SYNCED, 409)

    def test_draining_an_empty_count_sheet_target_still_advances_the_dimension(
        self, api: ApiClient
    ) -> None:
        """There is not one count sheet line in the system, and it composes anyway.

        PRD 3.6: "from `NOT_STARTED`, a `PREP_GUIDE` target advances to
        `PREP_GUIDE_SYNCED` and a `COUNT_SHEETS` target advances to
        `COUNTS_SYNCED`; from `PREP_GUIDE_SYNCED`, a `COUNT_SHEETS` target advances
        to `FULLY_PROPAGATED`; and from `COUNTS_SYNCED`, a `PREP_GUIDE` target
        advances to `FULLY_PROPAGATED`."

        Design: Corner/endpoints/propagation_is_a_conditional_action_on_the_approval_dimension_and_each_target_drains_once
        """
        world = self._an_approved_quantity_change(api)
        fixtures.propagate_change_order(
            api, world["order"]["id"], target=PropagationTarget.PREP_GUIDE
        )

        drained = fixtures.propagate_change_order(
            api, world["order"]["id"], target=PropagationTarget.COUNT_SHEETS
        )

        assert_spec_change_order(
            drained,
            approval_status=ApprovalStatus.APPROVED,
            propagation_status=PropagationStatus.FULLY_PROPAGATED,
        )

    def test_the_count_sheet_target_also_drains_exactly_once(
        self, api: ApiClient
    ) -> None:
        """The already-synced conflict, not a state error: the order is still APPROVED.

        PRD 3.6: "The named target must not already be reflected in
        `propagation_status`, otherwise `ERR_PROPAGATION_ALREADY_SYNCED` — each
        target may be drained exactly once per order."

        Design: Corner/endpoints/propagation_is_a_conditional_action_on_the_approval_dimension_and_each_target_drains_once
        """
        world = self._an_approved_quantity_change(api)
        fixtures.propagate_change_order(
            api, world["order"]["id"], target=PropagationTarget.PREP_GUIDE
        )
        fixtures.propagate_change_order(
            api, world["order"]["id"], target=PropagationTarget.COUNT_SHEETS
        )

        response = api.propagate_spec_change_order(
            world["order"]["id"],
            factories.propagate_payload(PropagationTarget.COUNT_SHEETS),
            COST_ANALYST,
        )

        validate_error(response, ApiErrorId.PROPAGATION_ALREADY_SYNCED, 409)
        assert_spec_change_order(
            get_success_data(api.get_spec_change_order(world["order"]["id"])),
            approval_status=ApprovalStatus.APPROVED,
            propagation_status=PropagationStatus.FULLY_PROPAGATED,
        )


class TestLoadingAMixLineSnapshotsThePlateCost:
    """A link row whose value copy makes a closed period immune to re-costing."""

    @staticmethod
    def _an_open_review_over_july(api: ApiClient):
        """The live MI-GRILL-MW plus one OPEN review of July at STORE-001."""
        world = fixtures.grill_world_active_item(api)
        world["unit"] = fixtures.create_unit(api, code="STORE-001", name="Downtown")
        world["review"] = fixtures.open_review(
            api,
            world["unit"]["id"],
            period_start="2026-07-01T00:00:00.000Z",
            period_end="2026-08-01T00:00:00.000Z",
            basis=ReviewBasis.SALES_MIX_BASED,
        )
        return world

    @staticmethod
    def _reprice_the_cheddar(api: ApiClient, world):
        """Publish a mid-July rise, re-cost the recipe and re-price the plate."""
        fixtures.publish_price(
            api,
            world["cheddar"]["id"],
            33_000_000,
            effective_from="2026-07-15T00:00:00.000Z",
        )
        recipe = fixtures.rollup(api, world["recipe"]["id"])
        item = fixtures.plate_cost(api, world["menu_item"]["id"])
        return recipe, item

    def test_the_world_starts_at_the_july_price_with_an_open_review(
        self, api: ApiClient
    ) -> None:
        """One hundred cents of plate against a four-hundred-cent menu price.

        PRD 3.5: "`plate_cost_cents` is `plate_cost_micros` divided by 10000,
        rounded half up. `food_cost_bps` is `plate_cost_cents` multiplied by 10000
        and divided by `current_price_cents`, rounded half up."

        Design: Corner/endpoints/loading_a_mix_line_snapshots_the_plate_cost_and_never_tracks_it
        """
        world = self._an_open_review_over_july(api)

        assert_recipe(
            world["recipe"],
            status=RecipeStatus.ACTIVE,
            portion_cost_micros=round_half_up(round_half_up(400 * 22_000_000, 2268), 4),
        )
        assert_fields(world["recipe"], portion_cost_micros=970_018)
        assert_menu_item(
            world["menu_item"],
            status=MenuItemStatus.ACTIVE,
            plate_cost_state=CostState.FRESH,
            plate_cost_cents=micros_to_cents(plate_cost_micros(970_018, RegionCode.MW)),
        )
        assert_fields(world["menu_item"], plate_cost_cents=100)
        assert_period_review(world["review"], status=ReviewStatus.OPEN)

    def test_a_menu_item_that_does_not_exist_is_its_own_not_found(
        self, api: ApiClient
    ) -> None:
        """The body end of the association fails on the body's identifier.

        PRD 2.10: "A `menu_item_id` in the path or body identifies an existing menu
        item — `ERR_MENU_ITEM_NOT_FOUND`, 404. This covers every menu-item-scoped
        endpoint plus proposal creation, promotion creation and mix-line loading."

        Design: Corner/endpoints/loading_a_mix_line_snapshots_the_plate_cost_and_never_tracks_it
        """
        world = self._an_open_review_over_july(api)

        response = api.add_mix_line(
            world["review"]["id"],
            factories.mix_line_payload(
                MISSING_UUID_BEEF, units_sold=100, gross_sales_cents=40_000
            ),
            COST_ANALYST,
        )

        validate_error(response, ApiErrorId.MENU_ITEM_NOT_FOUND, 404)

    def test_a_review_that_does_not_exist_is_a_different_not_found(
        self, api: ApiClient
    ) -> None:
        """The path end fails on the path's identifier even with a valid body.

        PRD 2.10: "A `period_review_id` in the path identifies an existing period
        review — `ERR_PERIOD_REVIEW_NOT_FOUND`, 404."

        Design: Corner/endpoints/loading_a_mix_line_snapshots_the_plate_cost_and_never_tracks_it
        """
        world = self._an_open_review_over_july(api)

        response = api.add_mix_line(
            MISSING_UUID,
            factories.mix_line_payload(
                world["menu_item"]["id"], units_sold=100, gross_sales_cents=40_000
            ),
            COST_ANALYST,
        )

        validate_error(response, ApiErrorId.PERIOD_REVIEW_NOT_FOUND, 404)

    def test_the_link_freezes_the_plate_cost_at_the_moment_of_loading(
        self, api: ApiClient
    ) -> None:
        """Both ends are recorded and the money is copied, not referenced.

        PRD 3.8: "The line freezes `plate_cost_cents_snapshot` from the item's
        `plate_cost_cents` at the moment of loading, and every later classification
        and close values that line with the snapshot rather than with the item's
        live plate cost."

        Design: Corner/endpoints/loading_a_mix_line_snapshots_the_plate_cost_and_never_tracks_it
        """
        world = self._an_open_review_over_july(api)

        line = fixtures.load_mix_line(
            api,
            world["review"]["id"],
            world["menu_item"]["id"],
            units_sold=100,
            gross_sales_cents=40_000,
        )

        assert_mix_line(
            line,
            period_review_id=world["review"]["id"],
            menu_item_id=world["menu_item"]["id"],
            units_sold=100,
            gross_sales_cents=40_000,
            plate_cost_cents_snapshot=100,
        )

    def test_the_first_line_advances_the_review_and_totals_it(
        self, api: ApiClient
    ) -> None:
        """No explicit request moves the review; the load does it.

        PRD 3.8: "Loading a line recomputes the review's `total_units_sold` and
        `total_gross_sales_cents` from all of its mix lines and increments the
        review's `version`. The **first** line auto-advances the review from `OPEN`
        to `MIX_LOADED` without any explicit request; later lines leave it in
        `MIX_LOADED`."

        Design: Corner/endpoints/loading_a_mix_line_snapshots_the_plate_cost_and_never_tracks_it
        """
        world = self._an_open_review_over_july(api)
        fixtures.load_mix_line(
            api,
            world["review"]["id"],
            world["menu_item"]["id"],
            units_sold=100,
            gross_sales_cents=40_000,
        )

        review = get_success_data(api.get_period_review(world["review"]["id"]))

        assert_period_review(
            review,
            status=ReviewStatus.MIX_LOADED,
            total_units_sold=100,
            total_gross_sales_cents=40_000,
        )
        assert review["version"] > world["review"]["version"]

    def test_a_later_price_rise_moves_the_plate_and_not_the_snapshot(
        self, api: ApiClient
    ) -> None:
        """The plate genuinely goes to 151 cents and the loaded line stays at 100.

        PRD 3.2: "A new line whose `effective_from` falls strictly after an
        open-ended published row's `effective_from` does not collide either: it
        *truncates* that predecessor."

        Design: Corner/endpoints/loading_a_mix_line_snapshots_the_plate_cost_and_never_tracks_it
        """
        world = self._an_open_review_over_july(api)
        fixtures.load_mix_line(
            api,
            world["review"]["id"],
            world["menu_item"]["id"],
            units_sold=100,
            gross_sales_cents=40_000,
        )

        recipe, item = self._reprice_the_cheddar(api, world)
        rows, meta = validate_paginated(
            api.list_mix_lines(
                world["review"]["id"], {"limit": 10, "offset": 0}, COST_ANALYST
            )
        )

        assert_recipe(
            recipe,
            portion_cost_micros=round_half_up(round_half_up(400 * 33_000_000, 2268), 4),
        )
        assert_fields(recipe, portion_cost_micros=1_455_027)
        assert_menu_item(
            item,
            plate_cost_cents=micros_to_cents(
                plate_cost_micros(1_455_027, RegionCode.MW)
            ),
        )
        assert_fields(item, plate_cost_cents=151)
        assert_mix_line(
            single_row(rows, meta), plate_cost_cents_snapshot=100, units_sold=100
        )

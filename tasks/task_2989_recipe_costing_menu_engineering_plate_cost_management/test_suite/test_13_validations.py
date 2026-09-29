"""Validation rules whose interest is which one fires, and in what order.

Each group here satisfies the higher-priority gate on purpose so that the
lower-priority one is the only thing left to fail, or arranges two gates so that
draining one is the precondition of the other.  Nothing in this file tests a
message in isolation: every assertion pins a rule against a neighbour that could
plausibly have claimed the same request.
"""

from test_helpers import (
    MAX_RECIPE_DEPTH,
    ApiClient,
    ApiErrorId,
    ApprovalStatus,
    BaseUom,
    CostState,
    IngredientStatus,
    MenuItemStatus,
    PropagationStatus,
    PropagationTarget,
    ProposalStatus,
    RecipeStatus,
    RecipeType,
    RegionCode,
    ReviewBasis,
    ReviewStatus,
    SyncState,
    VarianceFlag,
    assert_count_line,
    assert_fields,
    assert_ingredient,
    assert_instant_equals,
    assert_menu_item,
    assert_period_review,
    assert_projections_unset,
    assert_proposal,
    assert_recipe,
    assert_spec_change_order,
    factories,
    fixtures,
    get_success_data,
    single_row,
    validate_error,
    COST_ANALYST,
    CULINARY_DIRECTOR,
    PLATFORM_ADMIN,
    RECIPE_DEVELOPER,
    SUBMITTER_USER_ID,
    make_recipe_developer_headers,
    micros_to_cents,
    plate_cost_micros,
    round_half_up,
    DEFAULT_BASELINE_UNITS,
    KIDS_MENU_SODIUM_CAP_MCG_PER_PORTION,
    MARGIN_FLOOR_CENTS,
    REGION_CAP_MULTIPLIER_BPS,
    REGION_COMPETITOR_INDEX_CENTS,
    CURRENT_PRICE_CAP_MULTIPLIER_BPS,
)


class TestKidsMenuSodiumCeilingIsGatedOnTheFlag:
    """Two recipes either side of 640000 micrograms, three items over them."""

    @staticmethod
    def _two_recipes_and_three_items(api: ApiClient):
        """One recipe inside the sodium ceiling, one outside, both ACTIVE."""
        world = fixtures.grill_world_priced(api)
        recipes = {}
        for code, name, ep in (
            ("KIDS-LOW", "Kids Grilled Cheese Small", 400),
            ("KIDS-HIGH", "Kids Grilled Cheese Large", 500),
        ):
            recipe = fixtures.create_recipe(api, code=code, name=name)
            fixtures.add_ingredient_component(
                api, recipe["id"], world["cheddar"]["id"], ep_quantity_base_units=ep
            )
            fixtures.rollup(api, recipe["id"])
            recipes[code] = fixtures.review_and_activate_recipe(api, recipe["id"])
        items = {
            "MI-KIDS-LOW": fixtures.create_menu_item(
                api, recipes["KIDS-LOW"]["id"], code="MI-KIDS-LOW", is_kids_menu=True
            ),
            "MI-KIDS-HIGH": fixtures.create_menu_item(
                api, recipes["KIDS-HIGH"]["id"], code="MI-KIDS-HIGH", is_kids_menu=True
            ),
            "MI-ADULT-HIGH": fixtures.create_menu_item(
                api, recipes["KIDS-HIGH"]["id"], code="MI-ADULT-HIGH"
            ),
        }
        for code, item in items.items():
            items[code] = fixtures.plate_cost(api, item["id"])
        world.update({"recipes": recipes, "items": items})
        return world

    def test_the_small_portion_rolls_up_inside_the_sodium_ceiling(
        self, api: ApiClient
    ) -> None:
        """620000 micrograms per portion against a 640000 bar.

        PRD 3.3: "The reported `kcal_per_portion_micros` is the batch energy total
        divided by `portions_per_batch`, rounded half up, and
        `sodium_mcg_per_portion` is the batch sodium total divided by
        `portions_per_batch`, rounded half up."

        Design: Corner/validations/kids_menu_sodium_cap_applies_only_when_the_flag_is_set
        """
        world = self._two_recipes_and_three_items(api)

        assert_recipe(
            world["recipes"]["KIDS-LOW"],
            status=RecipeStatus.ACTIVE,
            sodium_mcg_per_portion=round_half_up(400 * 6200, 4),
            kcal_per_portion_micros=round_half_up(400 * 4_000_000, 4),
        )
        assert_fields(
            world["recipes"]["KIDS-LOW"],
            sodium_mcg_per_portion=620_000,
            kcal_per_portion_micros=400_000_000,
        )
        assert 620_000 <= KIDS_MENU_SODIUM_CAP_MCG_PER_PORTION

    def test_the_large_portion_rolls_up_over_the_sodium_ceiling(
        self, api: ApiClient
    ) -> None:
        """775000 micrograms per portion, and a costlier plate to match.

        PRD 3.3: "`portion_cost_micros` is `batch_cost_micros` divided by
        `portions_per_batch`, rounded half up"

        Design: Corner/validations/kids_menu_sodium_cap_applies_only_when_the_flag_is_set
        """
        world = self._two_recipes_and_three_items(api)

        assert_recipe(
            world["recipes"]["KIDS-HIGH"],
            status=RecipeStatus.ACTIVE,
            sodium_mcg_per_portion=round_half_up(500 * 6200, 4),
            batch_cost_micros=round_half_up(500 * 22_000_000, 2268),
            portion_cost_micros=round_half_up(
                round_half_up(500 * 22_000_000, 2268), 4
            ),
        )
        assert_fields(
            world["recipes"]["KIDS-HIGH"],
            sodium_mcg_per_portion=775_000,
            portion_cost_micros=1_212_522,
        )
        assert 775_000 > KIDS_MENU_SODIUM_CAP_MCG_PER_PORTION

    def test_the_kids_flag_defaults_to_false_when_the_field_is_omitted(
        self, api: ApiClient
    ) -> None:
        """Two items on one recipe differ only in a boolean nobody sent.

        PRD 3.5: "an optional `is_kids_menu` boolean that defaults to false when
        omitted."

        Design: Corner/validations/kids_menu_sodium_cap_applies_only_when_the_flag_is_set
        """
        world = self._two_recipes_and_three_items(api)

        assert_menu_item(
            world["items"]["MI-KIDS-HIGH"],
            is_kids_menu=True,
            plate_cost_cents=126,
            sodium_mcg_per_portion=775_000,
        )
        assert_menu_item(
            world["items"]["MI-ADULT-HIGH"],
            is_kids_menu=False,
            plate_cost_cents=126,
            sodium_mcg_per_portion=775_000,
        )
        assert world["items"]["MI-KIDS-HIGH"]["recipe_id"] == (
            world["items"]["MI-ADULT-HIGH"]["recipe_id"]
        )

    def test_a_kids_item_inside_the_ceiling_activates(self, api: ApiClient) -> None:
        """620000 is at most 640000, so the gate passes and nothing else moves.

        PRD 3.5: "when `is_kids_menu` is true, the backing recipe's
        `sodium_mcg_per_portion` must be at most 640000 micrograms — that is, 640
        milligrams of sodium per portion — and exceeding it is refused with
        `ERR_NUTRITION_LIMIT_EXCEEDED`"

        Design: Corner/validations/kids_menu_sodium_cap_applies_only_when_the_flag_is_set
        """
        world = self._two_recipes_and_three_items(api)
        item = world["items"]["MI-KIDS-LOW"]

        activated = fixtures.activate_menu_item(api, item["id"])

        assert_menu_item(
            activated,
            status=MenuItemStatus.ACTIVE,
            plate_cost_state=CostState.FRESH,
            plate_cost_cents=micros_to_cents(plate_cost_micros(970_018, RegionCode.MW)),
            version=item["version"] + 1,
        )
        assert_fields(activated, plate_cost_cents=100, sodium_mcg_per_portion=620_000)

    def test_a_kids_item_over_the_ceiling_is_refused_and_stays_draft(
        self, api: ApiClient
    ) -> None:
        """775000 exceeds the bar, and the refusal persists nothing at all.

        PRD 3.5: "A successful activation increments the item's `version` and
        changes nothing else."

        Design: Corner/validations/kids_menu_sodium_cap_applies_only_when_the_flag_is_set
        """
        world = self._two_recipes_and_three_items(api)
        item = world["items"]["MI-KIDS-HIGH"]

        response = api.activate_menu_item(item["id"], CULINARY_DIRECTOR)

        validate_error(response, ApiErrorId.NUTRITION_LIMIT_EXCEEDED, 422)
        assert_menu_item(
            get_success_data(api.get_menu_item(item["id"])),
            status=MenuItemStatus.DRAFT,
            plate_cost_state=CostState.FRESH,
            version=item["version"],
        )

    def test_the_ceiling_is_not_enforced_at_all_for_an_adult_item(
        self, api: ApiClient
    ) -> None:
        """The same 775000-microgram recipe goes live under a false flag.

        PRD 3.5: "when `is_kids_menu` is false the sodium ceiling is not enforced
        at all."

        Design: Corner/validations/kids_menu_sodium_cap_applies_only_when_the_flag_is_set
        """
        world = self._two_recipes_and_three_items(api)
        adult = world["items"]["MI-ADULT-HIGH"]

        activated = fixtures.activate_menu_item(api, adult["id"])

        assert_menu_item(
            activated,
            status=MenuItemStatus.ACTIVE,
            sodium_mcg_per_portion=775_000,
            version=adult["version"] + 1,
        )
        kids = api.activate_menu_item(
            world["items"]["MI-KIDS-HIGH"]["id"], CULINARY_DIRECTOR
        )
        validate_error(kids, ApiErrorId.NUTRITION_LIMIT_EXCEEDED, 422)


class TestUniquenessIsScopedPerEntityType:
    """One store, one ingredient, one recipe and one item, then four repeats."""

    @staticmethod
    def _one_of_each(api: ApiClient):
        """A registry holding exactly one row of every code-bearing type."""
        unit = fixtures.create_unit(api)
        cheddar = fixtures.create_cheddar(api)
        recipe = fixtures.create_recipe(api)
        item = fixtures.create_menu_item(api, recipe["id"])
        return {"unit": unit, "cheddar": cheddar, "recipe": recipe, "item": item}

    def test_a_repeated_ingredient_sku_is_refused_however_different_the_rest(
        self, api: ApiClient
    ) -> None:
        """A different unit, pack, yield and allergen mask save nothing.

        PRD 3.1: "unique across all ingredients, with a repeat refused as
        `ERR_DUPLICATE_SKU`"

        Design: Corner/validations/sku_and_code_uniqueness_are_scoped_per_entity_type
        """
        world = self._one_of_each(api)
        assert world["cheddar"]["sku"] == "CHEDDAR-BLOCK"

        response = api.create_ingredient(
            factories.ingredient_payload(
                sku="CHEDDAR-BLOCK",
                name="Imported Cheddar",
                base_uom=BaseUom.MILLILITER,
                pack_base_units=500,
                trim_yield_bps=9000,
                cook_shrink_bps=500,
                allergen_mask=2,
                kcal_per_base_unit_micros=1_000_000,
                sodium_mcg_per_base_unit=10,
            ),
            RECIPE_DEVELOPER,
        )

        validate_error(response, ApiErrorId.DUPLICATE_SKU, 409)

    def test_a_repeated_store_code_is_refused_in_another_region(
        self, api: ApiClient
    ) -> None:
        """Store codes are global, not per-region.

        PRD 3.1: "it must be unique across all stores; a repeat is refused with
        `ERR_DUPLICATE_CODE`"

        Design: Corner/validations/sku_and_code_uniqueness_are_scoped_per_entity_type
        """
        world = self._one_of_each(api)
        assert world["unit"]["code"] == "STORE-001"

        response = api.create_unit(
            factories.unit_payload(
                code="STORE-001", name="Uptown", region_code=RegionCode.SE
            ),
            PLATFORM_ADMIN,
        )

        validate_error(response, ApiErrorId.DUPLICATE_CODE, 409)

    def test_a_repeated_recipe_code_is_refused_across_recipe_types(
        self, api: ApiClient
    ) -> None:
        """A sub-recipe may not borrow a plated recipe's code.

        PRD 3.3: "unique across recipes, with a repeat refused as
        `ERR_DUPLICATE_CODE`"

        Design: Corner/validations/sku_and_code_uniqueness_are_scoped_per_entity_type
        """
        world = self._one_of_each(api)
        assert world["recipe"]["code"] == "PLATE-GRILL"

        response = api.create_recipe(
            factories.recipe_payload(
                code="PLATE-GRILL",
                name="Grill Sauce Base",
                recipe_type=RecipeType.SUB_RECIPE,
                base_uom=BaseUom.MILLILITER,
                batch_yield_base_units=2000,
                portions_per_batch=20,
            ),
            RECIPE_DEVELOPER,
        )

        validate_error(response, ApiErrorId.DUPLICATE_CODE, 409)

    def test_a_repeated_menu_item_code_is_refused_in_another_region(
        self, api: ApiClient
    ) -> None:
        """The same dish sold in two regions still needs two codes.

        PRD 3.5: "unique across menu items, with a repeat refused as
        `ERR_DUPLICATE_CODE`"

        Design: Corner/validations/sku_and_code_uniqueness_are_scoped_per_entity_type
        """
        world = self._one_of_each(api)
        assert world["item"]["code"] == "MI-GRILL-MW"

        response = api.create_menu_item(
            factories.menu_item_payload(
                world["recipe"]["id"],
                code="MI-GRILL-MW",
                name="Grilled Cheese South",
                region_code=RegionCode.SE,
            ),
            RECIPE_DEVELOPER,
        )

        validate_error(response, ApiErrorId.DUPLICATE_CODE, 409)

    def test_a_store_may_take_the_code_a_recipe_already_uses(
        self, api: ApiClient
    ) -> None:
        """Each type keeps its own namespace, so PLATE-GRILL is free for a store.

        PRD 2.10: "The submitted `code` is unused among entities of the same type
        — `ERR_DUPLICATE_CODE`, 409, on store creation, recipe creation and
        menu-item creation."

        Design: Corner/validations/sku_and_code_uniqueness_are_scoped_per_entity_type
        """
        world = self._one_of_each(api)

        borrowed = fixtures.create_unit(
            api, code="PLATE-GRILL", name="Grill Street", region_code=RegionCode.SE
        )

        assert_fields(borrowed, code="PLATE-GRILL", region_code=RegionCode.SE)
        assert borrowed["code"] == world["recipe"]["code"]
        assert borrowed["id"] != world["recipe"]["id"]


class TestCycleDetectionOutranksTheDepthCeiling:
    """A four-level chain plus one spare leaf, probed from the bottom."""

    @staticmethod
    def _a_chain_at_the_ceiling(api: ApiClient):
        """SR1 under SR2 under SR3 under SR4 under the plated SR5, plus SR0."""
        spare = fixtures.create_sub_recipe(
            api,
            code="SR0",
            name="Spare Base",
            base_uom=BaseUom.MILLILITER,
            batch_yield_base_units=1000,
            portions_per_batch=10,
        )
        chain = {}
        for code, name in (
            ("SR1", "Level One Base"),
            ("SR2", "Level Two Base"),
            ("SR3", "Level Three Base"),
            ("SR4", "Level Four Base"),
        ):
            chain[code] = fixtures.create_sub_recipe(
                api,
                code=code,
                name=name,
                base_uom=BaseUom.MILLILITER,
                batch_yield_base_units=1000,
                portions_per_batch=10,
            )
        chain["SR5"] = fixtures.create_recipe(api, code="SR5", name="Deep Plate")
        for parent, child in (
            ("SR2", "SR1"),
            ("SR3", "SR2"),
            ("SR4", "SR3"),
            ("SR5", "SR4"),
        ):
            fixtures.add_sub_recipe_component(
                api,
                chain[parent]["id"],
                chain[child]["id"],
                ep_quantity_base_units=100,
            )
        return spare, {
            code: get_success_data(api.get_recipe(recipe["id"]))
            for code, recipe in chain.items()
        }

    @staticmethod
    def _add_child(api: ApiClient, parent_id: str, child_id: str, sequence_no: int = 1):
        """Attempt one sub-recipe append with a freshly read guard version."""
        payload = factories.sub_recipe_component_payload(
            child_id,
            fixtures.recipe_version(api, parent_id),
            ep_quantity_base_units=100,
            sequence_no=sequence_no,
        )
        return api.add_recipe_component(parent_id, payload, RECIPE_DEVELOPER)

    def test_the_chain_starts_exactly_at_the_depth_ceiling(
        self, api: ApiClient
    ) -> None:
        """Four levels of nesting above a leaf whose own depth is zero.

        PRD 3.3: "`depth` measures nesting: a recipe with no active sub-recipe
        component — all ingredient leaves — has a depth of 0; otherwise its depth
        is one more than the greatest depth among the children of its active
        sub-recipe components."

        Design: Corner/validations/cycle_detection_outranks_the_depth_limit_and_both_look_at_the_whole_dag
        """
        spare, chain = self._a_chain_at_the_ceiling(api)

        assert_recipe(chain["SR5"], depth=MAX_RECIPE_DEPTH, component_count=1)
        assert_fields(chain["SR4"], depth=3)
        assert_fields(chain["SR3"], depth=2)
        assert_fields(chain["SR2"], depth=1)
        assert_recipe(chain["SR1"], depth=0, component_count=0)
        assert_recipe(spare, depth=0, component_count=0)

    def test_a_recipe_may_not_contain_itself(self, api: ApiClient) -> None:
        """The degenerate cycle is caught before any depth arithmetic runs.

        PRD 3.3: "A sub-recipe line whose `child_recipe_id` is the owning recipe
        itself, or is any recipe that already reaches the owning recipe through
        active components, would make the recipe graph cyclic and is refused with
        `ERR_RECIPE_CYCLE`"

        Design: Corner/validations/cycle_detection_outranks_the_depth_limit_and_both_look_at_the_whole_dag
        """
        _, chain = self._a_chain_at_the_ceiling(api)

        response = self._add_child(api, chain["SR1"]["id"], chain["SR1"]["id"])

        validate_error(response, ApiErrorId.RECIPE_CYCLE, 422)

    def test_the_cycle_gate_outranks_the_depth_gate(self, api: ApiClient) -> None:
        """Closing the loop from the top would also breach the ceiling; cycle wins.

        PRD 2.10: "Requests are validated in one fixed order, and the **first**
        rule that fails determines the response; no later rule is evaluated and no
        partial mutation is persisted."

        Design: Corner/validations/cycle_detection_outranks_the_depth_limit_and_both_look_at_the_whole_dag
        """
        _, chain = self._a_chain_at_the_ceiling(api)

        response = self._add_child(api, chain["SR1"]["id"], chain["SR5"]["id"])

        validate_error(response, ApiErrorId.RECIPE_CYCLE, 422)

    def test_the_depth_gate_speaks_for_an_ancestor_absent_from_the_request(
        self, api: ApiClient
    ) -> None:
        """Adding a leaf under the leaf pushes SR5 to five levels and is refused.

        PRD 2.10: "The resulting depth of the owning recipe and of every recipe
        that transitively contains it stays within the depth ceiling —
        `ERR_RECIPE_DEPTH_EXCEEDED`, 422, on component creation and recipe
        activation."

        Design: Corner/validations/cycle_detection_outranks_the_depth_limit_and_both_look_at_the_whole_dag
        """
        spare, chain = self._a_chain_at_the_ceiling(api)

        response = self._add_child(api, chain["SR1"]["id"], spare["id"])

        validate_error(response, ApiErrorId.RECIPE_DEPTH_EXCEEDED, 422)

    def test_the_three_refusals_leave_the_leaf_untouched(
        self, api: ApiClient
    ) -> None:
        """SR1 still holds nothing and still carries the version it was made with.

        PRD 3.3: "`component_count` is by definition the number of components of
        the recipe whose `status` is `ACTIVE`."

        Design: Corner/validations/cycle_detection_outranks_the_depth_limit_and_both_look_at_the_whole_dag
        """
        spare, chain = self._a_chain_at_the_ceiling(api)
        leaf = chain["SR1"]

        for child_id in (leaf["id"], chain["SR5"]["id"], spare["id"]):
            assert self._add_child(api, leaf["id"], child_id).status_code >= 400

        assert_recipe(
            get_success_data(api.get_recipe(leaf["id"])),
            status=RecipeStatus.DRAFT,
            component_count=0,
            depth=0,
            version=leaf["version"],
        )

    def test_a_sibling_branch_is_a_maximum_and_never_a_sum(
        self, api: ApiClient
    ) -> None:
        """A second child of depth zero beside a child of depth two changes nothing.

        PRD 3.3: "otherwise its depth is one more than the greatest depth among
        the children of its active sub-recipe components."

        Design: Corner/validations/cycle_detection_outranks_the_depth_limit_and_both_look_at_the_whole_dag
        """
        spare, chain = self._a_chain_at_the_ceiling(api)

        added = fixtures.add_sub_recipe_component(
            api,
            chain["SR4"]["id"],
            spare["id"],
            ep_quantity_base_units=100,
            sequence_no=2,
        )

        assert_fields(added, sequence_no=2, ap_quantity_base_units=100)
        assert_recipe(
            get_success_data(api.get_recipe(chain["SR4"]["id"])),
            depth=3,
            component_count=2,
        )
        assert_fields(
            get_success_data(api.get_recipe(chain["SR5"]["id"])),
            depth=MAX_RECIPE_DEPTH,
        )


class TestAnApprovedSpecChangeBlocksTheReviewClose:
    """A classified review, then a re-quantified component underneath it."""

    @staticmethod
    def _classified_review_with_an_approved_change(api: ApiClient):
        """One CLASSIFIED review and one APPROVED, undrained quantity change."""
        fixtures.set_clock(api, "2026-08-05T00:00:00.000Z")
        world = fixtures.grill_world_active_item(api)
        unit = fixtures.create_unit(api)
        review = fixtures.open_review(
            api, unit["id"], basis=ReviewBasis.SALES_MIX_BASED
        )
        fixtures.load_mix_line(
            api,
            review["id"],
            world["menu_item"]["id"],
            units_sold=100,
            gross_sales_cents=40_000,
        )
        count_line = fixtures.record_count_line(
            api,
            review["id"],
            world["cheddar"]["id"],
            opening_base_units=10_500,
            received_base_units=0,
            counted_base_units=300,
        )
        classified = fixtures.classify_review(api, review["id"])
        order = fixtures.approved_qty_change(
            api,
            world["recipe"]["id"],
            world["component"]["id"],
            new_ep_quantity_base_units=500,
        )
        world.update(
            {
                "unit": unit,
                "review": classified,
                "count_line": count_line,
                "order": order,
            }
        )
        return world

    def test_the_expectation_is_computed_against_the_mix_as_loaded(
        self, api: ApiClient
    ) -> None:
        """One hundred plates of a 400-gram specification expect 10000 grams.

        PRD 3.8: "Creation also derives `expected_base_units` from the currently
        loaded mix by the explosion described next, sets `variance_base_units` to
        `used_base_units` minus `expected_base_units`, sets `sync_state` to
        `CURRENT`"

        Design: Corner/validations/an_approved_spec_change_blocks_the_review_close_until_the_counts_are_drained
        """
        world = self._classified_review_with_an_approved_change(api)

        assert_count_line(
            world["count_line"],
            used_base_units=10_500 + 0 - 300,
            expected_base_units=100 * round_half_up(400 * 1_000_000, 4) // 1_000_000,
            variance_base_units=200,
            sync_state=SyncState.CURRENT,
            valued_usage_micros=0,
        )
        assert_fields(
            world["count_line"], used_base_units=10_200, expected_base_units=10_000
        )
        assert_period_review(world["review"], status=ReviewStatus.CLASSIFIED)

    def test_the_approved_order_leaves_the_propagation_undrained(
        self, api: ApiClient
    ) -> None:
        """Approval moves the approval dimension only.

        PRD 3.6: "`propagation_status` runs `NOT_STARTED`, then
        `PREP_GUIDE_SYNCED` or `COUNTS_SYNCED`, then `FULLY_PROPAGATED`. The
        propagation dimension only ever advances while `approval_status` is
        `APPROVED`"

        Design: Corner/validations/an_approved_spec_change_blocks_the_review_close_until_the_counts_are_drained
        """
        world = self._classified_review_with_an_approved_change(api)

        assert_spec_change_order(
            world["order"],
            approval_status=ApprovalStatus.APPROVED,
            propagation_status=PropagationStatus.NOT_STARTED,
            pre_change_ep_quantity_base_units=400,
        )
        assert_recipe(
            get_success_data(api.get_recipe(world["recipe"]["id"])),
            status=RecipeStatus.ACTIVE,
            cost_state=CostState.STALE,
        )

    def test_the_close_is_refused_while_one_count_line_is_out_of_date(
        self, api: ApiClient
    ) -> None:
        """The review has everything it needs except a current expectation.

        PRD 3.8: "it requires every count line of the review to have `sync_state`
        `CURRENT`, otherwise `ERR_COUNT_SHEET_OUT_OF_DATE` — a review cannot be
        closed on expectations computed against a specification that has since
        changed."

        Design: Corner/validations/an_approved_spec_change_blocks_the_review_close_until_the_counts_are_drained
        """
        world = self._classified_review_with_an_approved_change(api)

        response = api.close_period_review(world["review"]["id"], COST_ANALYST)

        validate_error(response, ApiErrorId.COUNT_SHEET_OUT_OF_DATE, 409)
        assert_period_review(
            get_success_data(api.get_period_review(world["review"]["id"])),
            status=ReviewStatus.CLASSIFIED,
            closed_at=None,
        )

    def test_the_flagged_line_keeps_its_stale_expectation_until_drained(
        self, api: ApiClient
    ) -> None:
        """Approval flags the line, it does not recompute it.

        PRD 3.6: "it flips `sync_state` to `OUT_OF_DATE` on every count sheet line
        that belongs to a period review whose `status` is not `CLOSED` and whose
        `ingredient_id` is consumed by an active component of this recipe."

        Design: Corner/validations/an_approved_spec_change_blocks_the_review_close_until_the_counts_are_drained
        """
        world = self._classified_review_with_an_approved_change(api)

        assert_count_line(
            single_row(fixtures.count_line_rows(api, world["review"]["id"])),
            sync_state=SyncState.OUT_OF_DATE,
            expected_base_units=10_000,
            variance_base_units=200,
            used_base_units=10_200,
        )

    def test_draining_the_count_sheets_recomputes_the_expectation(
        self, api: ApiClient
    ) -> None:
        """The 500-gram specification expects 12500 grams and inverts the variance.

        PRD 3.6: "for every count sheet line whose `sync_state` is `OUT_OF_DATE`
        and that belongs to a period review whose `status` is not `CLOSED`,
        `expected_base_units` is recomputed by the expected-usage explosion of
        §3.8 against the current specification, `sync_state` is set to `CURRENT`,
        `variance_base_units` is recomputed as `used_base_units` minus the new
        `expected_base_units`"

        Design: Corner/validations/an_approved_spec_change_blocks_the_review_close_until_the_counts_are_drained
        """
        world = self._classified_review_with_an_approved_change(api)

        drained = fixtures.propagate_change_order(
            api, world["order"]["id"], target=PropagationTarget.COUNT_SHEETS
        )

        assert_spec_change_order(
            drained, propagation_status=PropagationStatus.COUNTS_SYNCED
        )
        assert_count_line(
            single_row(fixtures.count_line_rows(api, world["review"]["id"])),
            sync_state=SyncState.CURRENT,
            expected_base_units=100 * round_half_up(500 * 1_000_000, 4) // 1_000_000,
            variance_base_units=10_200 - 12_500,
        )
        assert_fields(
            single_row(fixtures.count_line_rows(api, world["review"]["id"])),
            expected_base_units=12_500,
            variance_base_units=-2_300,
        )

    def test_the_close_then_values_the_period_at_the_frozen_snapshot(
        self, api: ApiClient
    ) -> None:
        """10000 cents in theory against 9894 actual, inside the tolerance.

        PRD 3.8: "Under `SALES_MIX_BASED` it is the sum over the mix lines of
        `units_sold` multiplied by `plate_cost_cents_snapshot`"

        Design: Corner/validations/an_approved_spec_change_blocks_the_review_close_until_the_counts_are_drained
        """
        world = self._classified_review_with_an_approved_change(api)
        fixtures.propagate_change_order(
            api, world["order"]["id"], target=PropagationTarget.COUNT_SHEETS
        )

        closed = fixtures.close_review(api, world["review"]["id"])

        assert_period_review(
            closed,
            status=ReviewStatus.CLOSED,
            theoretical_food_cost_cents=100 * 100,
            actual_food_cost_cents=round_half_up(
                round_half_up(10_200 * 22_000_000, 2268), 10_000
            ),
            variance_bps=-106,
            variance_flag=VarianceFlag.WITHIN_TOLERANCE,
        )
        assert_fields(closed, actual_food_cost_cents=9_894)
        assert_instant_equals(closed["closed_at"], "2026-08-05T00:00:00.000Z")

    def test_the_close_is_not_gated_on_the_recipe_cost_state(
        self, api: ApiClient
    ) -> None:
        """A STALE recipe underneath does not stop a drained review closing.

        PRD 2.10: "The cost figures the operation consumes are not stale —
        `ERR_COST_STALE`, 409 — on recipe roll-up, recipe review submission,
        recipe activation, plate-cost recomputation, menu-item activation,
        proposal submission, proposal approval and promotion costing."

        Design: Corner/validations/an_approved_spec_change_blocks_the_review_close_until_the_counts_are_drained
        """
        world = self._classified_review_with_an_approved_change(api)
        fixtures.propagate_change_order(
            api, world["order"]["id"], target=PropagationTarget.COUNT_SHEETS
        )

        closed = fixtures.close_review(api, world["review"]["id"])

        assert_recipe(
            get_success_data(api.get_recipe(world["recipe"]["id"])),
            cost_state=CostState.STALE,
        )
        assert_menu_item(
            get_success_data(api.get_menu_item(world["menu_item"]["id"])),
            plate_cost_state=CostState.STALE,
        )
        assert_period_review(closed, status=ReviewStatus.CLOSED)


class TestCoolingOffAndOneLiveProposalInterlock:
    """One applied price change, then two more proposals fighting over it."""

    @staticmethod
    def _priced_item_at_the_second_of_august(api: ApiClient):
        """A live MI-GRILL-MW at 400 cents over a 100-cent plate, clock advanced."""
        world = fixtures.grill_world_active_item(api)
        fixtures.set_clock(api, "2026-08-02T00:00:00.000Z")
        world["first"] = fixtures.open_proposal(
            api,
            world["menu_item"]["id"],
            proposed_price_cents=420,
            effective_from="2026-08-02T00:00:00.000Z",
            elasticity_bps=12_000,
        )
        return world

    @staticmethod
    def _first_change_applied(api: ApiClient):
        """The 420-cent move all the way through to EFFECTIVE."""
        world = TestCoolingOffAndOneLiveProposalInterlock._priced_item_at_the_second_of_august(
            api
        )
        fixtures.submit_proposal(api, world["first"]["id"])
        fixtures.approve_proposal(api, world["first"]["id"])
        world["first"] = fixtures.apply_proposal(api, world["first"]["id"])
        return world

    def test_a_new_proposal_carries_no_projection_at_all(
        self, api: ApiClient
    ) -> None:
        """Eight projection fields all null until a submission writes them.

        PRD 3.7: "The new proposal opens in `DRAFT` with `revision_round` 0, null
        `submitted_by_user_id`, `approved_by_user_id`, `last_revision_reason` and
        `applied_at`, and no projection at all — every projection field stays unset
        until submission."

        Design: Corner/validations/cooling_off_and_one_live_proposal_per_item_interlock
        """
        world = self._priced_item_at_the_second_of_august(api)

        assert_proposal(
            world["first"],
            status=ProposalStatus.DRAFT,
            revision_round=0,
            submitted_by_user_id=None,
            approved_by_user_id=None,
            last_revision_reason=None,
            applied_at=None,
        )
        assert_projections_unset(world["first"])

    def test_the_first_submission_falls_back_to_the_default_baseline(
        self, api: ApiClient
    ) -> None:
        """No closed review anywhere, so the volume baseline is 1000 units.

        PRD 3.7: "when no such line exists anywhere, `baseline_units` is the
        default baseline of 1000 units."

        Design: Corner/validations/cooling_off_and_one_live_proposal_per_item_interlock
        """
        world = self._priced_item_at_the_second_of_august(api)

        submitted = fixtures.submit_proposal(api, world["first"]["id"])

        assert_proposal(
            submitted,
            status=ProposalStatus.SUBMITTED,
            baseline_units=DEFAULT_BASELINE_UNITS,
            price_delta_bps=round_half_up(abs(420 - 400) * 10_000, 400),
            projected_unit_delta_bps=-round_half_up(500 * 12_000, 10_000),
            projected_units=round_half_up(1_000 * (10_000 - 600), 10_000),
            projected_food_cost_bps=round_half_up(100 * 10_000, 420),
            submitted_by_user_id=SUBMITTER_USER_ID,
        )
        assert_fields(
            submitted,
            baseline_units=1_000,
            price_delta_bps=500,
            projected_unit_delta_bps=-600,
            projected_units=940,
            projected_food_cost_bps=2_381,
        )

    def test_the_first_submission_faces_no_cooling_off_gate(
        self, api: ApiClient
    ) -> None:
        """A null `last_price_change_at` exempts the very first move entirely.

        PRD 3.7: "when `last_price_change_at` is null there is no cooling-off
        restriction at all."

        Design: Corner/validations/cooling_off_and_one_live_proposal_per_item_interlock
        """
        world = self._priced_item_at_the_second_of_august(api)
        assert world["menu_item"]["last_price_change_at"] is None

        submitted = fixtures.submit_proposal(api, world["first"]["id"])

        assert_proposal(
            submitted,
            status=ProposalStatus.SUBMITTED,
            market_cap_price_cents=min(
                round_half_up(
                    REGION_COMPETITOR_INDEX_CENTS[RegionCode.MW]
                    * REGION_CAP_MULTIPLIER_BPS[RegionCode.MW],
                    10_000,
                ),
                round_half_up(400 * CURRENT_PRICE_CAP_MULTIPLIER_BPS, 10_000),
            ),
            effective_cap_price_cents=448,
            projected_contribution_delta_cents=940 * (420 - 100) - 1_000 * (400 - 100),
        )
        assert_fields(
            submitted,
            market_cap_price_cents=448,
            projected_contribution_delta_cents=800,
        )

    def test_application_stamps_the_last_price_change_and_clears_the_class(
        self, api: ApiClient
    ) -> None:
        """The item moves to 420 cents on the same 100-cent plate.

        PRD 3.7: "Application stamps `applied_at` with the current logical clock
        and then rewrites the item: `current_price_cents` becomes
        `proposed_price_cents`, `last_price_change_at` becomes the current logical
        clock, and `food_cost_bps` and `contribution_margin_cents` are recomputed
        from the *unchanged* `plate_cost_cents` against the new price by the same
        two formulas plate costing uses."

        Design: Corner/validations/cooling_off_and_one_live_proposal_per_item_interlock
        """
        world = self._first_change_applied(api)

        assert_proposal(world["first"], status=ProposalStatus.EFFECTIVE)
        assert_instant_equals(world["first"]["applied_at"], "2026-08-02T00:00:00.000Z")
        item = get_success_data(api.get_menu_item(world["menu_item"]["id"]))
        assert_menu_item(
            item,
            current_price_cents=420,
            plate_cost_cents=100,
            plate_cost_state=CostState.FRESH,
            food_cost_bps=round_half_up(100 * 10_000, 420),
            contribution_margin_cents=420 - 100,
        )
        assert_fields(item, food_cost_bps=2_381, contribution_margin_cents=320)
        assert_instant_equals(
            item["last_price_change_at"], "2026-08-02T00:00:00.000Z"
        )

    def test_a_second_move_inside_the_cooling_off_window_is_refused(
        self, api: ApiClient
    ) -> None:
        """The eighth day is not the fourteenth, and nothing is written.

        PRD 3.7: "When the item's `last_price_change_at` is not null, the
        proposal's `effective_from` must be at least 14 whole days after it,
        otherwise `ERR_PRICE_CHANGE_COOLING_OFF`"

        Design: Corner/validations/cooling_off_and_one_live_proposal_per_item_interlock
        """
        world = self._first_change_applied(api)
        second = fixtures.open_proposal(
            api,
            world["menu_item"]["id"],
            proposed_price_cents=440,
            effective_from="2026-08-10T00:00:00.000Z",
            elasticity_bps=12_000,
        )

        response = api.submit_proposal(
            second["id"], make_recipe_developer_headers(SUBMITTER_USER_ID)
        )

        validate_error(response, ApiErrorId.PRICE_CHANGE_COOLING_OFF, 409)
        stored = get_success_data(api.get_proposal(second["id"]))
        assert_proposal(
            stored, status=ProposalStatus.DRAFT, submitted_by_user_id=None
        )
        assert_projections_unset(stored)

    def test_a_third_proposal_cannot_even_be_created(self, api: ApiClient) -> None:
        """One DRAFT proposal is enough to close the item to another.

        PRD 3.7: "The target item may have no other proposal whose `status` is
        `DRAFT`, `SUBMITTED`, `REVISION_REQUESTED` or `APPROVED`; a second live
        proposal is refused with `ERR_PROPOSAL_ALREADY_OPEN`."

        Design: Corner/validations/cooling_off_and_one_live_proposal_per_item_interlock
        """
        world = self._first_change_applied(api)
        fixtures.open_proposal(
            api,
            world["menu_item"]["id"],
            proposed_price_cents=440,
            effective_from="2026-08-10T00:00:00.000Z",
            elasticity_bps=12_000,
        )

        response = api.create_proposal(
            factories.proposal_payload(
                world["menu_item"]["id"],
                proposed_price_cents=450,
                effective_from="2026-09-01T00:00:00.000Z",
            ),
            RECIPE_DEVELOPER,
        )

        validate_error(response, ApiErrorId.PROPOSAL_ALREADY_OPEN, 409)

    def test_moving_the_date_to_the_fourteenth_day_clears_the_gate(
        self, api: ApiClient
    ) -> None:
        """Exactly fourteen whole days later, and the cap is re-cut from 420.

        PRD 3.7: "the single-step arm, which is the item's `current_price_cents`
        multiplied by 11200 — that is, 10000 plus the 1200-basis-point
        single-increase ceiling — divided by 10000 and rounded half up."

        Design: Corner/validations/cooling_off_and_one_live_proposal_per_item_interlock
        """
        world = self._first_change_applied(api)
        second = fixtures.open_proposal(
            api,
            world["menu_item"]["id"],
            proposed_price_cents=440,
            effective_from="2026-08-10T00:00:00.000Z",
            elasticity_bps=12_000,
        )
        get_success_data(
            api.update_proposal(
                second["id"],
                {"effective_from": "2026-08-16T00:00:00.000Z"},
                RECIPE_DEVELOPER,
            )
        )

        submitted = fixtures.submit_proposal(api, second["id"])

        assert_proposal(
            submitted,
            status=ProposalStatus.SUBMITTED,
            price_delta_bps=round_half_up(abs(440 - 420) * 10_000, 420),
            projected_unit_delta_bps=-round_half_up(476 * 12_000, 10_000),
            projected_units=round_half_up(1_000 * (10_000 - 571), 10_000),
            projected_food_cost_bps=round_half_up(100 * 10_000, 440),
            effective_cap_price_cents=round_half_up(
                420 * CURRENT_PRICE_CAP_MULTIPLIER_BPS, 10_000
            ),
            projected_contribution_delta_cents=943 * (440 - 100)
            - 1_000 * (420 - 100),
        )
        assert_fields(
            submitted,
            price_delta_bps=476,
            projected_unit_delta_bps=-571,
            projected_units=943,
            projected_food_cost_bps=2_273,
            effective_cap_price_cents=470,
            projected_contribution_delta_cents=620,
        )


class TestTheMarginFloorFiresBelowTheMarketCap:
    """A price cut that the market would accept and the arithmetic will not."""

    @staticmethod
    def _a_cut_to_three_hundred_and_eighty(api: ApiClient):
        """MI-GRILL-MW live at 400 cents, with a DRAFT cut to 380 waiting."""
        world = fixtures.grill_world_active_item(api)
        world["cut"] = fixtures.open_proposal(
            api,
            world["menu_item"]["id"],
            proposed_price_cents=380,
            elasticity_bps=12_000,
        )
        return world

    @staticmethod
    def _market_cap_cents(current_price_cents: int) -> int:
        """The smaller of the competitor arm and the single-step arm, in MW."""
        return min(
            round_half_up(
                REGION_COMPETITOR_INDEX_CENTS[RegionCode.MW]
                * REGION_CAP_MULTIPLIER_BPS[RegionCode.MW],
                10_000,
            ),
            round_half_up(
                current_price_cents * CURRENT_PRICE_CAP_MULTIPLIER_BPS, 10_000
            ),
        )

    def test_the_plate_reports_a_hundred_cents_and_a_three_hundred_cent_margin(
        self, api: ApiClient
    ) -> None:
        """The item sits exactly on the floor before anybody proposes anything.

        PRD 3.5: "`plate_cost_cents` is `plate_cost_micros` divided by 10000,
        rounded half up. `food_cost_bps` is `plate_cost_cents` multiplied by 10000
        and divided by `current_price_cents`, rounded half up."

        Design: Corner/validations/margin_floor_breach_fires_while_the_market_cap_is_satisfied
        """
        world = self._a_cut_to_three_hundred_and_eighty(api)

        assert_menu_item(
            world["menu_item"],
            status=MenuItemStatus.ACTIVE,
            plate_cost_state=CostState.FRESH,
            plate_cost_micros=plate_cost_micros(970_018, RegionCode.MW),
            plate_cost_cents=micros_to_cents(1_004_259),
            food_cost_bps=round_half_up(100 * 10_000, 400),
            contribution_margin_cents=400 - 100,
            target_food_cost_bps=3_000,
        )
        assert_fields(
            world["menu_item"],
            plate_cost_micros=1_004_259,
            plate_cost_cents=100,
            food_cost_bps=2_500,
            contribution_margin_cents=MARGIN_FLOOR_CENTS,
        )

    def test_the_cut_is_refused_by_the_margin_floor(self, api: ApiClient) -> None:
        """380 minus 100 is 280, twenty cents short of the floor.

        PRD 3.7: "And `proposed_price_cents` minus the item's `plate_cost_cents`
        must be at least the 300-cent margin floor, otherwise
        `ERR_MARGIN_FLOOR_BREACH`."

        Design: Corner/validations/margin_floor_breach_fires_while_the_market_cap_is_satisfied
        """
        world = self._a_cut_to_three_hundred_and_eighty(api)

        response = api.submit_proposal(
            world["cut"]["id"], make_recipe_developer_headers(SUBMITTER_USER_ID)
        )

        validate_error(response, ApiErrorId.MARGIN_FLOOR_BREACH, 422)
        assert 380 - 100 < MARGIN_FLOOR_CENTS

    def test_the_higher_priority_market_cap_gate_did_not_fire(
        self, api: ApiClient
    ) -> None:
        """A cut is far under the cap, so only the lower-priority gate is left.

        PRD 2.10: "Second, position 47 sits above position 48: a proposal that
        breaches both the market cap and the margin floor reports
        `ERR_MARKET_CAP_EXCEEDED`."

        Design: Corner/validations/margin_floor_breach_fires_while_the_market_cap_is_satisfied
        """
        world = self._a_cut_to_three_hundred_and_eighty(api)

        response = api.submit_proposal(
            world["cut"]["id"], make_recipe_developer_headers(SUBMITTER_USER_ID)
        )

        assert self._market_cap_cents(400) == 448
        assert 380 <= self._market_cap_cents(400)
        validate_error(response, ApiErrorId.MARGIN_FLOOR_BREACH, 422)

    def test_the_refused_submission_discards_the_whole_projection(
        self, api: ApiClient
    ) -> None:
        """The figures were computed and then thrown away entire.

        PRD 2.10: "no later rule is evaluated and no partial mutation is
        persisted."

        Design: Corner/validations/margin_floor_breach_fires_while_the_market_cap_is_satisfied
        """
        world = self._a_cut_to_three_hundred_and_eighty(api)
        api.submit_proposal(
            world["cut"]["id"], make_recipe_developer_headers(SUBMITTER_USER_ID)
        )

        stored = get_success_data(api.get_proposal(world["cut"]["id"]))

        assert_proposal(
            stored,
            status=ProposalStatus.DRAFT,
            proposed_price_cents=380,
            submitted_by_user_id=None,
            version=world["cut"]["version"],
        )
        assert_projections_unset(stored)

    def test_one_more_cent_clears_the_floor_and_submits(
        self, api: ApiClient
    ) -> None:
        """401 leaves 301 cents of contribution and the projection sticks.

        PRD 3.7: "**Step seven** computes `projected_contribution_delta_cents` as
        `projected_units` multiplied by the difference between
        `proposed_price_cents` and `plate_cost_cents`, minus `baseline_units`
        multiplied by the difference between `current_price_cents` and
        `plate_cost_cents`"

        Design: Corner/validations/margin_floor_breach_fires_while_the_market_cap_is_satisfied
        """
        world = self._a_cut_to_three_hundred_and_eighty(api)
        api.submit_proposal(
            world["cut"]["id"], make_recipe_developer_headers(SUBMITTER_USER_ID)
        )
        edited = get_success_data(
            api.update_proposal(
                world["cut"]["id"], {"proposed_price_cents": 401}, RECIPE_DEVELOPER
            )
        )
        assert_proposal(edited, proposed_price_cents=401)

        submitted = fixtures.submit_proposal(api, world["cut"]["id"])

        assert_proposal(
            submitted,
            status=ProposalStatus.SUBMITTED,
            price_delta_bps=round_half_up(abs(401 - 400) * 10_000, 400),
            projected_unit_delta_bps=-round_half_up(25 * 12_000, 10_000),
            projected_units=round_half_up(1_000 * (10_000 - 30), 10_000),
            projected_food_cost_bps=round_half_up(100 * 10_000, 401),
            projected_contribution_delta_cents=997 * (401 - 100)
            - DEFAULT_BASELINE_UNITS * (400 - 100),
        )
        assert_fields(
            submitted,
            price_delta_bps=25,
            projected_unit_delta_bps=-30,
            projected_units=997,
            projected_food_cost_bps=2_494,
            projected_contribution_delta_cents=97,
        )
        assert 401 - 100 >= MARGIN_FLOOR_CENTS


class TestTheTwoReviewEmptinessGates:
    """Two emptiness rules, each fired from the state its own remedy leaves."""

    @staticmethod
    def _an_empty_june_review(api: ApiClient):
        """A live item, a store, and a brand-new review of June with nothing in it."""
        world = fixtures.grill_world_active_item(api)
        unit = fixtures.create_unit(api, code="STORE-001", name="Downtown")
        world["unit"] = unit
        world["review"] = fixtures.open_review(
            api,
            unit["id"],
            period_start="2026-06-01T00:00:00.000Z",
            period_end="2026-07-01T00:00:00.000Z",
            basis=ReviewBasis.SALES_MIX_BASED,
        )
        return world

    def test_the_new_review_opens_with_every_aggregate_at_zero(
        self, api: ApiClient
    ) -> None:
        """Nothing has been loaded, so every total starts at zero.

        PRD 3.8: "The review opens in `status` `OPEN` with `total_units_sold`,
        `total_gross_sales_cents`, `popularity_threshold_bps`,
        `margin_threshold_cents`, `theoretical_food_cost_cents`,
        `actual_food_cost_cents` and `variance_bps` all 0, `variance_flag` unset
        until close, and a null `closed_at`."

        Design: Corner/validations/the_two_review_emptiness_gates_create_an_unrecoverable_ordering_trap
        """
        world = self._an_empty_june_review(api)

        assert_period_review(
            world["review"],
            status=ReviewStatus.OPEN,
            basis=ReviewBasis.SALES_MIX_BASED,
            total_units_sold=0,
            total_gross_sales_cents=0,
            popularity_threshold_bps=0,
            margin_threshold_cents=0,
            theoretical_food_cost_cents=0,
            actual_food_cost_cents=0,
            variance_bps=0,
            variance_flag=None,
            closed_at=None,
        )

    def test_classifying_an_open_review_reports_the_empty_mix_not_a_state_error(
        self, api: ApiClient
    ) -> None:
        """The state gate lets OPEN through purely so this error is what surfaces.

        PRD 3.8: "It is reachable from `OPEN` and from `MIX_LOADED`, but a review
        still in `OPEN` has by definition no mix lines and therefore always fails
        with `ERR_EMPTY_MIX`; the state gate admits it so that the empty-mix error
        rather than a state error is what the caller sees."

        Design: Corner/validations/the_two_review_emptiness_gates_create_an_unrecoverable_ordering_trap
        """
        world = self._an_empty_june_review(api)

        response = api.classify_period_review(world["review"]["id"], COST_ANALYST)

        validate_error(response, ApiErrorId.EMPTY_MIX, 422)
        assert_period_review(
            get_success_data(api.get_period_review(world["review"]["id"])),
            status=ReviewStatus.OPEN,
            popularity_threshold_bps=0,
            margin_threshold_cents=0,
        )

    def test_the_first_mix_line_unblocks_classification(
        self, api: ApiClient
    ) -> None:
        """One line auto-advances the review and the same request now succeeds.

        PRD 3.8: "The **first** line auto-advances the review from `OPEN` to
        `MIX_LOADED` without any explicit request; later lines leave it in
        `MIX_LOADED`."

        Design: Corner/validations/the_two_review_emptiness_gates_create_an_unrecoverable_ordering_trap
        """
        world = self._an_empty_june_review(api)
        api.classify_period_review(world["review"]["id"], COST_ANALYST)

        fixtures.load_mix_line(
            api,
            world["review"]["id"],
            world["menu_item"]["id"],
            units_sold=100,
            gross_sales_cents=40_000,
        )
        loaded = get_success_data(api.get_period_review(world["review"]["id"]))
        classified = fixtures.classify_review(api, world["review"]["id"])

        assert_period_review(
            loaded,
            status=ReviewStatus.MIX_LOADED,
            total_units_sold=100,
            total_gross_sales_cents=40_000,
        )
        assert_period_review(
            classified,
            status=ReviewStatus.CLASSIFIED,
            popularity_threshold_bps=round_half_up(7_000, 1),
            margin_threshold_cents=round_half_up(
                100 * (round_half_up(40_000, 100) - 100), 100
            ),
        )
        assert_fields(
            classified, popularity_threshold_bps=7_000, margin_threshold_cents=300
        )

    def test_the_close_then_reports_the_other_emptiness_gate(
        self, api: ApiClient
    ) -> None:
        """The mix is loaded and classified, and the count sheet is still bare.

        PRD 3.8: "It requires at least one count line, otherwise
        `ERR_EMPTY_COUNT_SHEET`"

        Design: Corner/validations/the_two_review_emptiness_gates_create_an_unrecoverable_ordering_trap
        """
        world = self._an_empty_june_review(api)
        fixtures.load_mix_line(
            api,
            world["review"]["id"],
            world["menu_item"]["id"],
            units_sold=100,
            gross_sales_cents=40_000,
        )
        fixtures.classify_review(api, world["review"]["id"])

        response = api.close_period_review(world["review"]["id"], COST_ANALYST)

        validate_error(response, ApiErrorId.EMPTY_COUNT_SHEET, 422)

    def test_the_refused_close_leaves_the_review_classified_and_unclosed(
        self, api: ApiClient
    ) -> None:
        """No partial close: the thresholds stand and closed_at is still null.

        PRD 2.10: "Requests are validated in one fixed order, and the **first**
        rule that fails determines the response; no later rule is evaluated and no
        partial mutation is persisted."

        Design: Corner/validations/the_two_review_emptiness_gates_create_an_unrecoverable_ordering_trap
        """
        world = self._an_empty_june_review(api)
        fixtures.load_mix_line(
            api,
            world["review"]["id"],
            world["menu_item"]["id"],
            units_sold=100,
            gross_sales_cents=40_000,
        )
        classified = fixtures.classify_review(api, world["review"]["id"])
        api.close_period_review(world["review"]["id"], COST_ANALYST)

        stored = get_success_data(api.get_period_review(world["review"]["id"]))

        assert_period_review(
            stored,
            status=ReviewStatus.CLASSIFIED,
            popularity_threshold_bps=7_000,
            margin_threshold_cents=300,
            theoretical_food_cost_cents=0,
            actual_food_cost_cents=0,
            variance_bps=0,
            variance_flag=None,
            closed_at=None,
            version=classified["version"],
        )


class TestTheLogicalClockRefusesToMoveBackwards:
    """At-or-after, so standing still is legal and stepping back is not."""

    @staticmethod
    def _four_probe_ingredients(api: ApiClient):
        """Four throwaway ACTIVE ingredients, one per clock reading to be stamped."""
        probes = {}
        for suffix in ("A", "B", "C", "D"):
            probes[suffix] = fixtures.create_ingredient(
                api,
                sku=f"CLOCK-{suffix}",
                name=f"Clock Probe {suffix}",
                base_uom=BaseUom.GRAM,
                pack_base_units=1000,
                trim_yield_bps=10_000,
                cook_shrink_bps=0,
                allergen_mask=0,
                kcal_per_base_unit_micros=1_000_000,
                sodium_mcg_per_base_unit=10,
            )
        return probes

    def test_a_forward_move_stamps_the_new_reading(self, api: ApiClient) -> None:
        """The retirement is stamped with the clock, not with real time.

        PRD 2.4: "Every timestamp the system writes itself (`retired_at`,
        `published_at`, `last_rollup_at`, `removed_at`, `approved_at`,
        `applied_at`, `closed_at`, `reviewed_at`, `last_price_change_at`) is the
        logical clock's reading at the moment of the write."

        Design: Corner/validations/the_logical_clock_refuses_to_move_backwards_but_accepts_standing_still
        """
        probes = self._four_probe_ingredients(api)
        fixtures.set_clock(api, "2026-08-10T00:00:00.000Z")

        retired = fixtures.retire_ingredient(api, probes["A"]["id"])

        assert_ingredient(retired, status=IngredientStatus.RETIRED)
        assert_instant_equals(
            retired["retired_at"], "2026-08-10T00:00:00.000Z", "retired_at"
        )

    def test_one_millisecond_backwards_is_refused(self, api: ApiClient) -> None:
        """A single millisecond short of the current reading is still backwards.

        PRD 2.4: "the clock is strictly monotonic, so an instant earlier than the
        current reading is refused with `ERR_CLOCK_NOT_MONOTONIC` and HTTP 422."

        Design: Corner/validations/the_logical_clock_refuses_to_move_backwards_but_accepts_standing_still
        """
        self._four_probe_ingredients(api)
        fixtures.set_clock(api, "2026-08-10T00:00:00.000Z")

        response = api.set_clock(
            factories.clock_payload("2026-08-09T23:59:59.999Z"), PLATFORM_ADMIN
        )

        validate_error(response, ApiErrorId.CLOCK_NOT_MONOTONIC, 422)

    def test_the_refused_move_leaves_the_reading_exactly_where_it_was(
        self, api: ApiClient
    ) -> None:
        """The next write proves the rejected request advanced nothing.

        PRD 2.10: "The requested clock instant is at or after the current logical
        clock — `ERR_CLOCK_NOT_MONOTONIC`, 422."

        Design: Corner/validations/the_logical_clock_refuses_to_move_backwards_but_accepts_standing_still
        """
        probes = self._four_probe_ingredients(api)
        fixtures.set_clock(api, "2026-08-10T00:00:00.000Z")
        api.set_clock(
            factories.clock_payload("2026-08-09T23:59:59.999Z"), PLATFORM_ADMIN
        )

        retired = fixtures.retire_ingredient(api, probes["B"]["id"])

        assert_instant_equals(
            retired["retired_at"], "2026-08-10T00:00:00.000Z", "retired_at"
        )

    def test_standing_still_on_the_current_reading_is_accepted(
        self, api: ApiClient
    ) -> None:
        """At-or-after admits the equal case, and the reading does not budge.

        PRD 2.10: "The requested clock instant is at or after the current logical
        clock — `ERR_CLOCK_NOT_MONOTONIC`, 422."

        Design: Corner/validations/the_logical_clock_refuses_to_move_backwards_but_accepts_standing_still
        """
        probes = self._four_probe_ingredients(api)
        fixtures.set_clock(api, "2026-08-10T00:00:00.000Z")

        standing_still = api.set_clock(
            factories.clock_payload("2026-08-10T00:00:00.000Z"), PLATFORM_ADMIN
        )
        get_success_data(standing_still)
        retired = fixtures.retire_ingredient(api, probes["C"]["id"])

        assert_instant_equals(
            retired["retired_at"], "2026-08-10T00:00:00.000Z", "retired_at"
        )

    def test_the_clock_advances_and_stamps_at_millisecond_resolution(
        self, api: ApiClient
    ) -> None:
        """One millisecond forward is a real move and shows up in the stamp.

        PRD 2.4: "Before the first clock write the logical clock reads exactly
        `2026-08-01T00:00:00Z`, and it never falls back to real time under any
        circumstance."

        Design: Corner/validations/the_logical_clock_refuses_to_move_backwards_but_accepts_standing_still
        """
        probes = self._four_probe_ingredients(api)
        fixtures.set_clock(api, "2026-08-10T00:00:00.000Z")
        fixtures.set_clock(api, "2026-08-10T00:00:00.001Z")

        retired = fixtures.retire_ingredient(api, probes["D"]["id"])

        assert_instant_equals(
            retired["retired_at"], "2026-08-10T00:00:00.001Z", "retired_at"
        )

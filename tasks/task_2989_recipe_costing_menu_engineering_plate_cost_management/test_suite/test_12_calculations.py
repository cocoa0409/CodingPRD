"""Every arithmetic rule the API states, exercised at the value that breaks shortcuts.

The plate-cost ladder is checked step by step so that a collapsed multiplier and a
missing garnish floor both fail; the count-sheet explosion is checked through a
sub-recipe so that a one-level walk fails; the projection is checked against three
period reviews so that the wrong baseline fails; and the promotion arithmetic is
checked at values that are negative, unclamped or exactly on a threshold.
"""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    BaseUom,
    COST_ANALYST,
    CostBasis,
    CostState,
    LtoStatus,
    LtoVerdict,
    MarginClass,
    MenuItemStatus,
    ProposalStatus,
    RecipeType,
    RegionCode,
    ReviewBasis,
    ReviewStatus,
    SUBMITTER_USER_ID,
    SyncState,
    VarianceFlag,
    assert_count_line,
    assert_fields,
    assert_lto_campaign,
    assert_menu_item,
    assert_mix_line,
    assert_period_review,
    assert_projections_unset,
    assert_proposal,
    assert_recipe,
    fixtures,
    floor_div,
    get_success_data,
    micros_to_cents,
    plate_cost_micros,
    round_half_up,
    single_row,
    validate_error,
)

# The PLATE-GRILL world: 400 grams of cheddar at 22000000 micros per 2268-gram
# pack, over four portions.
GRILL_BATCH_MICROS = round_half_up(400 * 22_000_000, 2268)
GRILL_PORTION_MICROS = round_half_up(GRILL_BATCH_MICROS, 4)


class TestPlateCostAppliesTheUpliftAndWasteSequentially:
    """One portion cost of 970018 micros, plated in MW and in NE."""

    @staticmethod
    def _one_recipe_two_regions(api: ApiClient):
        """A FRESH recipe backing a Midwest item and a Northeast item."""
        world = fixtures.grill_world_costed(api)
        world["mw_item"] = fixtures.create_menu_item(
            api,
            world["recipe"]["id"],
            code="MI-GRILL-MW",
            name="Grilled Cheese Midwest",
            region_code=RegionCode.MW,
            current_price_cents=400,
        )
        world["ne_item"] = fixtures.create_menu_item(
            api,
            world["recipe"]["id"],
            code="MI-GRILL-NE",
            name="Grilled Cheese Northeast",
            region_code=RegionCode.NE,
            current_price_cents=400,
        )
        return world

    def test_the_zero_uplift_region_walks_the_four_steps(
        self, api: ApiClient
    ) -> None:
        """970018 becomes 989418 after waste and 1004259 after garnish.

        PRD 3.5: "The arithmetic proceeds in four ordered steps, each rounding
        half up to whole micro-dollars before the next step consumes it. First,
        take the recipe's `portion_cost_micros` and apply the freight uplift for
        the item's `region_code`"

        Design: Corner/calculations/plate_cost_applies_the_regional_uplift_and_waste_factor_sequentially
        """
        world = self._one_recipe_two_regions(api)
        assert_recipe(
            world["recipe"],
            cost_state=CostState.FRESH,
            portion_cost_micros=GRILL_PORTION_MICROS,
        )
        assert GRILL_PORTION_MICROS == 970_018

        costed = fixtures.plate_cost(api, world["mw_item"]["id"])

        landed = round_half_up(970_018 * (10_000 + 0), 10_000)
        waste_adjusted = round_half_up(landed * 10_200, 10_000)
        garnish = max(round_half_up(waste_adjusted * 150, 10_000), 8_000)
        assert (landed, waste_adjusted, garnish) == (970_018, 989_418, 14_841)
        assert_menu_item(
            costed,
            region_code=RegionCode.MW,
            plate_cost_micros=waste_adjusted + garnish,
        )
        assert_fields(costed, plate_cost_micros=1_004_259)

    def test_the_uplift_region_rounds_between_the_uplift_and_the_waste(
        self, api: ApiClient
    ) -> None:
        """1064515 in NE, not the 1047619 a single combined multiplier gives.

        PRD 3.5: "The uplift and the waste factor are applied *sequentially with
        a rounding between them*, so collapsing them into one multiplier built
        from the sum of the two basis-point figures produces a different and
        wrong answer."

        Design: Corner/calculations/plate_cost_applies_the_regional_uplift_and_waste_factor_sequentially
        """
        world = self._one_recipe_two_regions(api)

        costed = fixtures.plate_cost(api, world["ne_item"]["id"])

        landed = round_half_up(970_018 * (10_000 + 600), 10_000)
        waste_adjusted = round_half_up(landed * 10_200, 10_000)
        garnish = max(round_half_up(waste_adjusted * 150, 10_000), 8_000)
        assert (landed, waste_adjusted, garnish) == (1_028_219, 1_048_783, 15_732)
        collapsed = round_half_up(970_018 * (10_000 + 600 + 200), 10_000)
        assert collapsed == 1_047_619
        assert_menu_item(
            costed,
            region_code=RegionCode.NE,
            plate_cost_micros=waste_adjusted + garnish,
        )
        assert_fields(costed, plate_cost_micros=1_064_515)
        assert costed["plate_cost_micros"] != collapsed, (
            "the two factors must not be collapsed into one multiplier"
        )

    def test_the_three_reported_figures_follow_the_micro_dollar_total(
        self, api: ApiClient
    ) -> None:
        """100 cents at 2500 basis points in MW against 106 at 2650 in NE.

        PRD 3.5: "From `plate_cost_micros` three reported figures follow.
        `plate_cost_cents` is `plate_cost_micros` divided by 10000, rounded half
        up. `food_cost_bps` is `plate_cost_cents` multiplied by 10000 and divided
        by `current_price_cents`, rounded half up."

        Design: Corner/calculations/plate_cost_applies_the_regional_uplift_and_waste_factor_sequentially
        """
        world = self._one_recipe_two_regions(api)

        mw = fixtures.plate_cost(api, world["mw_item"]["id"])
        ne = fixtures.plate_cost(api, world["ne_item"]["id"])

        for item, expected_micros in ((mw, 1_004_259), (ne, 1_064_515)):
            cents = micros_to_cents(expected_micros)
            assert_menu_item(
                item,
                plate_cost_cents=cents,
                food_cost_bps=round_half_up(cents * 10_000, 400),
                contribution_margin_cents=400 - cents,
            )
        assert_fields(
            mw, plate_cost_cents=100, food_cost_bps=2500, contribution_margin_cents=300
        )
        assert_fields(
            ne, plate_cost_cents=106, food_cost_bps=2650, contribution_margin_cents=294
        )

    def test_plate_costing_copies_nutrition_and_leaves_the_class_alone(
        self, api: ApiClient
    ) -> None:
        """A DRAFT item gets FRESH figures, the recipe's basis, and no class.

        PRD 3.5: "The run also copies the recipe's `allergen_mask` onto the
        item's own `allergen_mask` and the recipe's `sodium_mcg_per_portion` onto
        the item's `sodium_mcg_per_portion`, sets `plate_cost_state` to `FRESH`
        and increments the item's `version`. `margin_class` is left exactly as it
        was: plate costing is not classification."

        Design: Corner/calculations/plate_cost_applies_the_regional_uplift_and_waste_factor_sequentially
        """
        world = self._one_recipe_two_regions(api)
        before = world["mw_item"]

        costed = fixtures.plate_cost(api, world["mw_item"]["id"])

        assert_menu_item(
            costed,
            status=MenuItemStatus.DRAFT,
            plate_cost_state=CostState.FRESH,
            cost_basis=CostBasis.LATEST_PUBLISHED,
            margin_class=MarginClass.UNCLASSIFIED,
            allergen_mask=world["recipe"]["allergen_mask"],
            sodium_mcg_per_portion=world["recipe"]["sodium_mcg_per_portion"],
            version=before["version"] + 1,
        )
        assert_fields(costed, allergen_mask=1, sodium_mcg_per_portion=620_000)


class TestGarnishFloorClampsACheapPortion:
    """A 100000-micro portion whose proportional garnish is below the floor."""

    @staticmethod
    def _salt_side_and_grill_plate(api: ApiClient):
        """One very cheap plated side and one ordinary plate, both FRESH."""
        salt = fixtures.create_ingredient(
            api,
            sku="SALT-KOSHER",
            name="Kosher Salt",
            base_uom=BaseUom.GRAM,
            pack_base_units=1000,
            allergen_mask=0,
            kcal_per_base_unit_micros=0,
            sodium_mcg_per_base_unit=390,
        )
        cheddar = fixtures.create_cheddar(api)
        feed = fixtures.open_price_feed(api, feed_date="2026-07-01T00:00:00.000Z")
        for ingredient, pack_cost in ((salt, 1_000_000), (cheddar, 22_000_000)):
            fixtures.add_price_line(
                api,
                feed["id"],
                ingredient["id"],
                pack_cost_micros=pack_cost,
                effective_from="2026-07-01T00:00:00.000Z",
            )
        fixtures.publish_price_feed(api, feed["id"])

        side = fixtures.create_recipe(
            api,
            code="SIDE-SALT",
            name="Salt Side",
            recipe_type=RecipeType.PLATED,
            base_uom=BaseUom.EACH,
            batch_yield_base_units=1,
            portions_per_batch=1,
        )
        fixtures.add_ingredient_component(
            api, side["id"], salt["id"], ep_quantity_base_units=100
        )
        side = fixtures.rollup(api, side["id"])
        side_item = fixtures.create_menu_item(
            api,
            side["id"],
            code="MI-SALT-MW",
            name="Salt Side Midwest",
            region_code=RegionCode.MW,
            current_price_cents=400,
            declared_allergen_mask=0,
        )

        plate = fixtures.create_recipe(api)
        fixtures.add_ingredient_component(
            api, plate["id"], cheddar["id"], ep_quantity_base_units=400
        )
        plate = fixtures.rollup(api, plate["id"])
        plate_item = fixtures.create_menu_item(
            api,
            plate["id"],
            code="MI-GRILL-MW",
            name="Grilled Cheese Midwest",
            region_code=RegionCode.MW,
            current_price_cents=400,
        )
        return {
            "salt": salt,
            "side": side,
            "side_item": side_item,
            "plate": plate,
            "plate_item": plate_item,
        }

    def test_the_cheap_recipe_rolls_up_to_exactly_one_hundred_thousand_micros(
        self, api: ApiClient
    ) -> None:
        """One hundred grams of salt at a whole micro-dollar per gram.

        PRD 3.3: "The recipe's `batch_cost_micros` is the sum of
        `extended_cost_micros` over its active components, and
        `portion_cost_micros` is `batch_cost_micros` divided by
        `portions_per_batch`, rounded half up."

        Design: Corner/calculations/plate_cost_garnish_allowance_is_clamped_by_the_floor_on_a_cheap_portion
        """
        world = self._salt_side_and_grill_plate(api)

        assert_recipe(
            world["side"],
            cost_state=CostState.FRESH,
            batch_cost_micros=round_half_up(100 * 1_000_000, 1_000),
            portion_cost_micros=round_half_up(100_000, 1),
        )
        assert_fields(
            world["side"], batch_cost_micros=100_000, portion_cost_micros=100_000
        )

    def test_the_proportional_garnish_loses_to_the_flat_floor(
        self, api: ApiClient
    ) -> None:
        """1530 micros of proportional garnish is clamped up to 8000.

        PRD 3.5: "Third, compute the garnish allowance as 150 basis points of the
        waste-adjusted figure — multiply by 150 and divide by 10000 — and then
        take whichever is larger, that proportional amount or the flat garnish
        floor of 8000 micro-dollars."

        Design: Corner/calculations/plate_cost_garnish_allowance_is_clamped_by_the_floor_on_a_cheap_portion
        """
        world = self._salt_side_and_grill_plate(api)

        costed = fixtures.plate_cost(api, world["side_item"]["id"])

        waste_adjusted = round_half_up(100_000 * 10_200, 10_000)
        proportional = round_half_up(waste_adjusted * 150, 10_000)
        assert (waste_adjusted, proportional) == (102_000, 1_530)
        assert proportional < 8_000
        assert_menu_item(
            costed, plate_cost_micros=waste_adjusted + max(proportional, 8_000)
        )
        assert_fields(costed, plate_cost_micros=110_000)
        assert costed["plate_cost_micros"] != waste_adjusted + proportional, (
            "the floor must win over the proportional garnish here"
        )

    def test_the_clamp_moves_the_reported_cent_figure(self, api: ApiClient) -> None:
        """11 cents rather than the 10 an unclamped garnish would report.

        PRD 3.5: "The garnish floor makes the plate cost a non-linear function of
        the portion cost: below a certain portion cost the garnish contributes
        the flat floor and above it the proportional term, so scaling a recipe's
        cost does not scale its plate cost."

        Design: Corner/calculations/plate_cost_garnish_allowance_is_clamped_by_the_floor_on_a_cheap_portion
        """
        world = self._salt_side_and_grill_plate(api)

        costed = fixtures.plate_cost(api, world["side_item"]["id"])

        assert micros_to_cents(103_530) == 10
        assert_menu_item(
            costed,
            plate_cost_cents=micros_to_cents(110_000),
            food_cost_bps=round_half_up(11 * 10_000, 400),
            contribution_margin_cents=400 - 11,
        )
        assert_fields(
            costed, plate_cost_cents=11, food_cost_bps=275, contribution_margin_cents=389
        )

    def test_the_cheap_plate_still_carries_its_own_nutrition(
        self, api: ApiClient
    ) -> None:
        """39000 micrograms of sodium and not one allergen bit.

        PRD 3.3: "The reported `kcal_per_portion_micros` is the batch energy
        total divided by `portions_per_batch`, rounded half up, and
        `sodium_mcg_per_portion` is the batch sodium total divided by
        `portions_per_batch`, rounded half up."

        Design: Corner/calculations/plate_cost_garnish_allowance_is_clamped_by_the_floor_on_a_cheap_portion
        """
        world = self._salt_side_and_grill_plate(api)

        costed = fixtures.plate_cost(api, world["side_item"]["id"])

        assert_recipe(
            world["side"],
            sodium_mcg_per_portion=round_half_up(100 * 390, 1),
            kcal_per_portion_micros=0,
            allergen_mask=0,
        )
        assert_menu_item(costed, sodium_mcg_per_portion=39_000, allergen_mask=0)

    def test_the_floor_arm_and_the_proportional_arm_coexist(
        self, api: ApiClient
    ) -> None:
        """Two items in one region, one clamped and one not.

        PRD 3.5: "Fourth, `plate_cost_micros` is the waste-adjusted figure plus
        the garnish allowance."

        Design: Corner/calculations/plate_cost_garnish_allowance_is_clamped_by_the_floor_on_a_cheap_portion
        """
        world = self._salt_side_and_grill_plate(api)

        cheap = fixtures.plate_cost(api, world["side_item"]["id"])
        ordinary = fixtures.plate_cost(api, world["plate_item"]["id"])

        assert cheap["plate_cost_micros"] == plate_cost_micros(
            100_000, RegionCode.MW
        )
        assert ordinary["plate_cost_micros"] == plate_cost_micros(
            GRILL_PORTION_MICROS, RegionCode.MW
        )
        assert_fields(cheap, plate_cost_micros=110_000)
        assert_fields(ordinary, plate_cost_micros=1_004_259)
        assert cheap["plate_cost_micros"] * 10 != ordinary["plate_cost_micros"], (
            "the plate cost is not linear in the portion cost"
        )


class TestCountSheetExpectedUsageReachesTheFixedPoint:
    """An oil the plated recipe never names, reached only through its sauce."""

    @staticmethod
    def _cheese_plate_over_a_peanut_sauce(api: ApiClient):
        """PLATE-CHEESE live over an ACTIVE SUB-SAUCE, sold 100 times."""
        cheddar = fixtures.create_cheddar(api)
        oil = fixtures.create_ingredient(
            api,
            sku="PEANUT-OIL",
            name="Peanut Oil",
            base_uom=BaseUom.MILLILITER,
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

        sauce = fixtures.create_sub_recipe(
            api,
            code="SUB-SAUCE",
            name="Peanut Sauce",
            base_uom=BaseUom.MILLILITER,
            batch_yield_base_units=2000,
            portions_per_batch=20,
        )
        fixtures.add_ingredient_component(
            api, sauce["id"], oil["id"], ep_quantity_base_units=100
        )
        sauce = fixtures.rollup(api, sauce["id"])
        fixtures.review_and_activate_recipe(api, sauce["id"])

        plate = fixtures.create_recipe(
            api,
            code="PLATE-CHEESE",
            name="Cheese Plate",
            batch_yield_base_units=5,
            portions_per_batch=5,
        )
        fixtures.add_ingredient_component(
            api, plate["id"], cheddar["id"], ep_quantity_base_units=400, sequence_no=1
        )
        fixtures.add_sub_recipe_component(
            api, plate["id"], sauce["id"], ep_quantity_base_units=500, sequence_no=2
        )
        plate = fixtures.rollup(api, plate["id"])
        fixtures.review_and_activate_recipe(api, plate["id"])

        item = fixtures.create_menu_item(
            api,
            plate["id"],
            code="MI-CHEESE-MW",
            name="Cheese Plate",
            region_code=RegionCode.MW,
            current_price_cents=400,
            declared_allergen_mask=9,
        )
        item = fixtures.plate_cost(api, item["id"])
        fixtures.activate_menu_item(api, item["id"])

        unit = fixtures.create_unit(api)
        review = fixtures.open_review(api, unit["id"])
        fixtures.load_mix_line(
            api, review["id"], item["id"], units_sold=100, gross_sales_cents=40_000
        )
        return {
            "cheddar": cheddar,
            "oil": oil,
            "sauce": sauce,
            "plate": plate,
            "item": item,
            "unit": unit,
            "review": review,
        }

    def test_the_plate_inherits_the_peanut_bit_only_through_the_child(
        self, api: ApiClient
    ) -> None:
        """4197196 in the batch, mask 9, depth 1 and 87 cents on the plate.

        PRD 3.3: "the extended cost is then `ep_quantity_base_units` multiplied
        by the child's `batch_cost_micros`, divided by the child's
        `batch_yield_base_units`, rounded half up."

        Design: Corner/calculations/count_sheet_expected_usage_reaches_fixed_point_through_the_sub_recipe_graph
        """
        world = self._cheese_plate_over_a_peanut_sauce(api)

        sauce_batch = round_half_up(100 * 12_000_000, 946)
        sub_extended = round_half_up(500 * sauce_batch, 2_000)
        assert (sauce_batch, sub_extended) == (1_268_499, 317_125)
        assert_recipe(world["sauce"], batch_cost_micros=sauce_batch)
        assert_recipe(
            world["plate"],
            batch_cost_micros=GRILL_BATCH_MICROS + sub_extended,
            portion_cost_micros=round_half_up(GRILL_BATCH_MICROS + sub_extended, 5),
            allergen_mask=1 | 8,
            depth=1,
        )
        assert_fields(
            world["plate"], batch_cost_micros=4_197_196, portion_cost_micros=839_439
        )
        assert_menu_item(
            world["item"],
            plate_cost_cents=micros_to_cents(plate_cost_micros(839_439, RegionCode.MW)),
        )
        assert_fields(world["item"], plate_cost_cents=87)

    def test_a_directly_referenced_ingredient_explodes_through_the_portion_divisor(
        self, api: ApiClient
    ) -> None:
        """80000000 micros of cheddar a portion makes 8000 grams expected.

        PRD 3.8: "An ingredient component on that very ingredient contributes its
        `ap_quantity_base_units` multiplied by 1000000, divided by the recipe's
        `portions_per_batch`, rounded half up."

        Design: Corner/calculations/count_sheet_expected_usage_reaches_fixed_point_through_the_sub_recipe_graph
        """
        world = self._cheese_plate_over_a_peanut_sauce(api)

        line = fixtures.record_count_line(
            api,
            world["review"]["id"],
            world["cheddar"]["id"],
            opening_base_units=10_000,
            received_base_units=0,
            counted_base_units=1_800,
        )

        per_portion_micros = round_half_up(400 * 1_000_000, 5)
        assert per_portion_micros == 80_000_000
        assert_count_line(
            line,
            used_base_units=10_000 + 0 - 1_800,
            expected_base_units=floor_div(100 * per_portion_micros, 1_000_000),
            variance_base_units=8_200 - 8_000,
        )
        assert_fields(
            line,
            used_base_units=8_200,
            expected_base_units=8_000,
            variance_base_units=200,
        )

    def test_an_ingredient_reached_only_through_the_sauce_still_explodes(
        self, api: ApiClient
    ) -> None:
        """Two different divisors, the child's yield and the parent's portions.

        PRD 3.8: "Ingredients that reach a plate only through a sub-recipe are
        picked up by this explosion exactly like directly referenced ones."

        Design: Corner/calculations/count_sheet_expected_usage_reaches_fixed_point_through_the_sub_recipe_graph
        """
        world = self._cheese_plate_over_a_peanut_sauce(api)

        line = fixtures.record_count_line(
            api,
            world["review"]["id"],
            world["oil"]["id"],
            opening_base_units=600,
            received_base_units=0,
            counted_base_units=90,
        )

        per_portion_micros = round_half_up(500 * 100 * 1_000_000, 2_000 * 5)
        assert per_portion_micros == 5_000_000
        assert_count_line(
            line,
            used_base_units=600 + 0 - 90,
            expected_base_units=floor_div(100 * per_portion_micros, 1_000_000),
            variance_base_units=510 - 500,
        )
        assert_fields(
            line,
            used_base_units=510,
            expected_base_units=500,
            variance_base_units=10,
        )
        assert line["expected_base_units"] > 0, (
            "the oil is consumed even though no plated component names it"
        )

    def test_both_count_lines_open_current_and_unvalued(
        self, api: ApiClient
    ) -> None:
        """Recording a count derives quantities but not money.

        PRD 3.8: "`valued_usage_micros` stays 0 until the close run values the
        line. Count lines are listed per review in `created_at` ascending order,
        filterable by `sync_state`."

        Design: Corner/calculations/count_sheet_expected_usage_reaches_fixed_point_through_the_sub_recipe_graph
        """
        world = self._cheese_plate_over_a_peanut_sauce(api)

        fixtures.record_count_line(
            api,
            world["review"]["id"],
            world["cheddar"]["id"],
            opening_base_units=10_000,
            received_base_units=0,
            counted_base_units=1_800,
        )
        fixtures.record_count_line(
            api,
            world["review"]["id"],
            world["oil"]["id"],
            opening_base_units=600,
            received_base_units=0,
            counted_base_units=90,
        )

        rows = fixtures.count_line_rows(api, world["review"]["id"])
        assert [row["ingredient_id"] for row in rows] == [
            world["cheddar"]["id"],
            world["oil"]["id"],
        ]
        for row in rows:
            assert_count_line(
                row, sync_state=SyncState.CURRENT, valued_usage_micros=0
            )


class TestSingleLineReviewIsAlwaysAStar:
    """The degenerate review that sits exactly on both thresholds."""

    @staticmethod
    def _one_line_review(api: ApiClient):
        """MI-GRILL-MW live at 100 cents, sold 100 times for 40000 cents."""
        world = fixtures.grill_world_active_item(api)
        unit = fixtures.create_unit(api)
        review = fixtures.open_review(api, unit["id"])
        mix_line = fixtures.load_mix_line(
            api, review["id"], world["menu_item"]["id"], units_sold=100,
            gross_sales_cents=40_000,
        )
        world.update({"unit": unit, "review": review, "mix_line": mix_line})
        return world

    def test_the_popularity_bar_is_the_whole_factor_over_one_line(
        self, api: ApiClient
    ) -> None:
        """One line puts the bar at the full 7000 basis points.

        PRD 3.8: "it computes `popularity_threshold_bps` as the popularity factor
        of 7000 basis points divided by the number of mix lines, rounded half up
        — so a two-line review sets the bar at 3500 basis points and a five-line
        review at 1400."

        Design: Corner/calculations/menu_mix_classification_single_line_review_is_always_a_star
        """
        world = self._one_line_review(api)

        classified = fixtures.classify_review(api, world["review"]["id"])

        assert_period_review(
            classified,
            status=ReviewStatus.CLASSIFIED,
            total_units_sold=100,
            popularity_threshold_bps=round_half_up(7_000, 1),
            margin_threshold_cents=round_half_up(100 * 300, 100),
        )
        assert_fields(
            classified, popularity_threshold_bps=7000, margin_threshold_cents=300
        )

    def test_the_lone_line_takes_the_whole_mix_share(self, api: ApiClient) -> None:
        """10000 basis points of mix and 300 cents of unit contribution.

        PRD 3.8: "`mix_pct_bps` is `units_sold` multiplied by 10000 and divided by
        the review's `total_units_sold`, rounded half up; and `cm_per_unit_cents`
        is `gross_sales_cents` divided by `units_sold` and rounded half up, minus
        that line's `plate_cost_cents_snapshot`"

        Design: Corner/calculations/menu_mix_classification_single_line_review_is_always_a_star
        """
        world = self._one_line_review(api)

        fixtures.classify_review(api, world["review"]["id"])

        line = single_row(fixtures.mix_line_rows(api, world["review"]["id"]))
        assert line["id"] == world["mix_line"]["id"]
        assert_mix_line(
            line,
            plate_cost_cents_snapshot=100,
            mix_pct_bps=round_half_up(100 * 10_000, 100),
            cm_per_unit_cents=round_half_up(40_000, 100) - 100,
        )
        assert_fields(line, mix_pct_bps=10_000, cm_per_unit_cents=300)

    def test_sitting_exactly_on_both_thresholds_is_still_a_star(
        self, api: ApiClient
    ) -> None:
        """Equality on both comparisons lands on the favourable side.

        PRD 3.8: "A single-line review always yields a `STAR`, because its mix
        share is 10000 basis points against a 7000-point bar and its contribution
        margin *is* the weighted average."

        Design: Corner/calculations/menu_mix_classification_single_line_review_is_always_a_star
        """
        world = self._one_line_review(api)

        classified = fixtures.classify_review(api, world["review"]["id"])

        line = single_row(fixtures.mix_line_rows(api, world["review"]["id"]))
        assert line["cm_per_unit_cents"] == classified["margin_threshold_cents"]
        assert line["mix_pct_bps"] >= classified["popularity_threshold_bps"]
        assert line["cm_per_unit_cents"] >= classified["margin_threshold_cents"]
        assert_mix_line(line, margin_class=MarginClass.STAR)

    def test_the_class_is_copied_onto_the_menu_item(self, api: ApiClient) -> None:
        """The only write classification makes outside the review.

        PRD 3.8: "Classification writes both thresholds onto the review and all
        three computed fields onto every line, copies each line's `margin_class`
        onto its menu item and increments each of those items' `version`, and
        increments the review's `version`."

        Design: Corner/calculations/menu_mix_classification_single_line_review_is_always_a_star
        """
        world = self._one_line_review(api)
        before = get_success_data(api.get_menu_item(world["menu_item"]["id"]))

        fixtures.classify_review(api, world["review"]["id"])

        assert_menu_item(
            get_success_data(api.get_menu_item(world["menu_item"]["id"])),
            margin_class=MarginClass.STAR,
            version=before["version"] + 1,
        )


class TestZeroTheoreticalCostReportsNoBasis:
    """A usage-based close whose only count line nothing on the menu consumes."""

    @staticmethod
    def _usage_review_over_an_unused_oil(api: ApiClient):
        """The grill world, an unconsumed oil, and a CLASSIFIED usage review."""
        world = fixtures.grill_world_active_item(api)
        oil = fixtures.create_ingredient(
            api,
            sku="PEANUT-OIL",
            name="Peanut Oil",
            base_uom=BaseUom.MILLILITER,
            pack_base_units=946,
            allergen_mask=8,
            kcal_per_base_unit_micros=8_000_000,
            sodium_mcg_per_base_unit=0,
        )
        fixtures.publish_price(
            api, oil["id"], 12_000_000, effective_from="2026-07-01T00:00:00.000Z"
        )
        unit = fixtures.create_unit(api)
        review = fixtures.open_review(api, unit["id"], basis=ReviewBasis.USAGE_BASED)
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
            oil["id"],
            opening_base_units=40,
            received_base_units=0,
            counted_base_units=0,
        )
        fixtures.classify_review(api, review["id"])
        world.update(
            {"oil": oil, "unit": unit, "review": review, "count_line": count_line}
        )
        return world

    def test_an_ingredient_no_mix_line_consumes_expects_nothing(
        self, api: ApiClient
    ) -> None:
        """Forty millilitres used against zero expected.

        PRD 3.8: "An ingredient that no mix line's recipe consumes therefore has
        `expected_base_units` 0 and a `variance_base_units` equal to the whole of
        `used_base_units`"

        Design: Corner/calculations/theoretical_vs_actual_variance_with_zero_theoretical_reports_no_basis
        """
        world = self._usage_review_over_an_unused_oil(api)

        assert_count_line(
            world["count_line"],
            used_base_units=40 + 0 - 0,
            expected_base_units=0,
            variance_base_units=40,
        )

    def test_the_usage_basis_reads_the_expectation_and_not_the_snapshot(
        self, api: ApiClient
    ) -> None:
        """One hundred sold portions contribute nothing to the theory.

        PRD 3.8: "Under `USAGE_BASED` it is computed from the count lines
        instead: for each line take `expected_base_units` multiplied by the
        selected price row's `pack_cost_micros`, divided by that line's
        `pack_base_units_snapshot`, rounded half up to micro-dollars; sum those;
        divide by 10000 and round half up to cents."

        Design: Corner/calculations/theoretical_vs_actual_variance_with_zero_theoretical_reports_no_basis
        """
        world = self._usage_review_over_an_unused_oil(api)

        closed = fixtures.close_review(api, world["review"]["id"])

        assert_period_review(
            closed,
            basis=ReviewBasis.USAGE_BASED,
            theoretical_food_cost_cents=0,
            total_units_sold=100,
        )

    def test_the_actual_side_is_a_non_zero_fifty_one_cents(
        self, api: ApiClient
    ) -> None:
        """507400 micros of oil valued at today's published price.

        PRD 3.8: "`actual_food_cost_cents` is the sum of `valued_usage_micros`
        over the review's count lines, divided by 10000 and rounded half up."

        Design: Corner/calculations/theoretical_vs_actual_variance_with_zero_theoretical_reports_no_basis
        """
        world = self._usage_review_over_an_unused_oil(api)

        closed = fixtures.close_review(api, world["review"]["id"])

        valued = round_half_up(40 * 12_000_000, 946)
        assert valued == 507_400
        assert_period_review(
            closed, actual_food_cost_cents=round_half_up(valued, 10_000)
        )
        assert_fields(closed, actual_food_cost_cents=51)

    def test_the_zero_theoretical_guard_replaces_the_percentage(
        self, api: ApiClient
    ) -> None:
        """No basis to be a percentage of, so no percentage is reported.

        PRD 3.8: "When `theoretical_food_cost_cents` is 0 the review reports
        `variance_bps` 0 and `variance_flag` `NO_BASIS` — there is nothing to be
        a percentage of."

        Design: Corner/calculations/theoretical_vs_actual_variance_with_zero_theoretical_reports_no_basis
        """
        world = self._usage_review_over_an_unused_oil(api)

        closed = fixtures.close_review(api, world["review"]["id"])

        assert_period_review(
            closed, variance_bps=0, variance_flag=VarianceFlag.NO_BASIS
        )
        assert closed["variance_flag"] not in (
            VarianceFlag.WITHIN_TOLERANCE,
            VarianceFlag.OVER_TOLERANCE,
        ), "NO_BASIS is neither side of the tolerance"

    def test_the_close_values_the_line_and_stamps_the_clock(
        self, api: ApiClient
    ) -> None:
        """The count line gets its money at the close, not at its creation.

        PRD 3.8: "The close stamps `closed_at` with the current logical clock,
        sets `status` to `CLOSED` and increments the review's `version`."

        Design: Corner/calculations/theoretical_vs_actual_variance_with_zero_theoretical_reports_no_basis
        """
        world = self._usage_review_over_an_unused_oil(api)
        assert world["count_line"]["valued_usage_micros"] == 0

        closed = fixtures.close_review(api, world["review"]["id"])

        assert_period_review(
            closed,
            status=ReviewStatus.CLOSED,
            closed_at="2026-08-01T00:00:00.000Z",
        )
        assert closed["version"] > world["review"]["version"]
        line = single_row(fixtures.count_line_rows(api, world["review"]["id"]))
        assert line["id"] == world["count_line"]["id"]
        assert_count_line(
            line, valued_usage_micros=507_400, sync_state=SyncState.CURRENT
        )


class TestProjectionBaselineComesFromTheLatestClosedReview:
    """Three reviews of the same item: 100 closed, 40 closed, 900 still open."""

    @staticmethod
    def _three_reviews_and_a_draft_proposal(api: ApiClient):
        """The clock at 2026-08-10 with two closed periods behind it."""
        fixtures.set_clock(api, "2026-08-10T00:00:00.000Z")
        world = fixtures.grill_world_active_item(api)
        unit = fixtures.create_unit(api)
        item_id = world["menu_item"]["id"]

        closed_periods = (
            ("2026-06-01T00:00:00.000Z", "2026-07-01T00:00:00.000Z", 100, 40_000, 8_000),
            ("2026-07-01T00:00:00.000Z", "2026-08-01T00:00:00.000Z", 40, 16_000, 3_200),
        )
        reviews = []
        for start, end, units, sales, opening in closed_periods:
            review = fixtures.open_review(
                api, unit["id"], period_start=start, period_end=end
            )
            fixtures.load_mix_line(
                api, review["id"], item_id, units_sold=units, gross_sales_cents=sales
            )
            fixtures.record_count_line(
                api,
                review["id"],
                world["cheddar"]["id"],
                opening_base_units=opening,
                received_base_units=0,
                counted_base_units=0,
            )
            fixtures.classify_review(api, review["id"])
            reviews.append(fixtures.close_review(api, review["id"]))

        open_review = fixtures.open_review(
            api,
            unit["id"],
            period_start="2026-08-01T00:00:00.000Z",
            period_end="2026-09-01T00:00:00.000Z",
        )
        fixtures.load_mix_line(
            api, open_review["id"], item_id, units_sold=900, gross_sales_cents=360_000
        )

        proposal = fixtures.open_proposal(
            api,
            item_id,
            proposed_price_cents=420,
            effective_from="2026-08-24T00:00:00.000Z",
            elasticity_bps=12_000,
        )
        world.update(
            {
                "unit": unit,
                "review_a": reviews[0],
                "review_b": reviews[1],
                "review_c": open_review,
                "proposal": proposal,
            }
        )
        return world

    def test_two_periods_close_and_the_largest_stays_loaded(
        self, api: ApiClient
    ) -> None:
        """900 units sit in a review that will never be consulted.

        PRD 3.8: "The **first** line auto-advances the review from `OPEN` to
        `MIX_LOADED` without any explicit request; later lines leave it in
        `MIX_LOADED`."

        Design: Corner/calculations/price_change_projection_baseline_units_come_from_the_latest_closed_review
        """
        world = self._three_reviews_and_a_draft_proposal(api)

        assert_menu_item(world["menu_item"], plate_cost_cents=100)
        assert_period_review(world["review_a"], status=ReviewStatus.CLOSED)
        assert_period_review(
            world["review_b"],
            status=ReviewStatus.CLOSED,
            closed_at="2026-08-10T00:00:00.000Z",
        )
        assert_period_review(
            get_success_data(api.get_period_review(world["review_c"]["id"])),
            status=ReviewStatus.MIX_LOADED,
            total_units_sold=900,
        )

    def test_creation_stores_no_projection_at_all(self, api: ApiClient) -> None:
        """A DRAFT proposal carries the request and nothing computed.

        PRD 3.7: "The new proposal opens in `DRAFT` with `revision_round` 0, null
        `submitted_by_user_id`, `approved_by_user_id`, `last_revision_reason` and
        `applied_at`, and no projection at all — every projection field stays
        unset until submission."

        Design: Corner/calculations/price_change_projection_baseline_units_come_from_the_latest_closed_review
        """
        world = self._three_reviews_and_a_draft_proposal(api)

        assert_proposal(
            world["proposal"],
            status=ProposalStatus.DRAFT,
            revision_round=0,
            proposed_price_cents=420,
            elasticity_bps=12_000,
            submitted_by_user_id=None,
            approved_by_user_id=None,
        )
        assert_projections_unset(world["proposal"])

    def test_the_baseline_is_the_later_closed_periods_units(
        self, api: ApiClient
    ) -> None:
        """Forty units win on period_end descending.

        PRD 3.7: "`baseline_units` is the `units_sold` of the mix line belonging
        to the most recent closed period review that contains a line for this
        menu item, where "most recent" ranks reviews by `period_end` descending
        and breaks ties by `created_at` ascending, first row winning; when no such
        line exists anywhere, `baseline_units` is the default baseline of 1000
        units."

        Design: Corner/calculations/price_change_projection_baseline_units_come_from_the_latest_closed_review
        """
        world = self._three_reviews_and_a_draft_proposal(api)

        submitted = fixtures.submit_proposal(api, world["proposal"]["id"])

        assert_proposal(
            submitted, status=ProposalStatus.SUBMITTED, baseline_units=40
        )
        assert submitted["baseline_units"] not in (100, 900, 1_000), (
            "neither the earlier closed period, the open one, nor the default"
        )

    def test_the_two_deltas_and_the_projected_volume_follow_the_baseline(
        self, api: ApiClient
    ) -> None:
        """A 500-point rise costs 600 points of volume, leaving 38 units.

        PRD 3.7: "Then `projected_units` is `baseline_units` multiplied by the sum
        of 10000 and `projected_unit_delta_bps`, divided by 10000, rounded half
        up, and floored at zero"

        Design: Corner/calculations/price_change_projection_baseline_units_come_from_the_latest_closed_review
        """
        world = self._three_reviews_and_a_draft_proposal(api)

        submitted = fixtures.submit_proposal(api, world["proposal"]["id"])

        price_delta_bps = round_half_up((420 - 400) * 10_000, 400)
        unit_delta_bps = -round_half_up(price_delta_bps * 12_000, 10_000)
        assert (price_delta_bps, unit_delta_bps) == (500, -600)
        assert_proposal(
            submitted,
            price_delta_bps=price_delta_bps,
            projected_unit_delta_bps=unit_delta_bps,
            projected_units=round_half_up(40 * (10_000 + unit_delta_bps), 10_000),
        )
        assert_fields(submitted, projected_units=38)

    def test_the_food_cost_reads_the_proposed_price_and_the_step_arm_caps(
        self, api: ApiClient
    ) -> None:
        """448 cents from the single-step arm, with no relief earned.

        PRD 3.7: "**Step five** computes `projected_food_cost_bps` as the item's
        `plate_cost_cents` multiplied by 10000, divided by
        `proposed_price_cents`, rounded half up — computed from the **proposed**
        price and never from any capped price."

        Design: Corner/calculations/price_change_projection_baseline_units_come_from_the_latest_closed_review
        """
        world = self._three_reviews_and_a_draft_proposal(api)

        submitted = fixtures.submit_proposal(api, world["proposal"]["id"])

        competitor_arm = round_half_up(1_500 * 11_000, 10_000)
        step_arm = round_half_up(400 * 11_200, 10_000)
        assert (competitor_arm, step_arm) == (1_650, 448)
        assert_proposal(
            submitted,
            projected_food_cost_bps=round_half_up(100 * 10_000, 420),
            market_cap_price_cents=min(competitor_arm, step_arm),
            effective_cap_price_cents=round_half_up(448 * (10_000 + 0), 10_000),
        )
        assert_fields(
            submitted,
            projected_food_cost_bps=2381,
            market_cap_price_cents=448,
            effective_cap_price_cents=448,
        )
        assert submitted["projected_food_cost_bps"] <= 3_000, (
            "no relief, because the projected food cost is not above target"
        )

    def test_the_contribution_delta_is_positive_despite_the_lost_volume(
        self, api: ApiClient
    ) -> None:
        """160 cents gained from 38 richer units against 40 poorer ones.

        PRD 3.7: "**Step seven** computes `projected_contribution_delta_cents` as
        `projected_units` multiplied by the difference between
        `proposed_price_cents` and `plate_cost_cents`, minus `baseline_units`
        multiplied by the difference between `current_price_cents` and
        `plate_cost_cents`"

        Design: Corner/calculations/price_change_projection_baseline_units_come_from_the_latest_closed_review
        """
        world = self._three_reviews_and_a_draft_proposal(api)

        submitted = fixtures.submit_proposal(api, world["proposal"]["id"])

        assert_proposal(
            submitted,
            projected_contribution_delta_cents=38 * (420 - 100) - 40 * (400 - 100),
            submitted_by_user_id=SUBMITTER_USER_ID,
        )
        assert_fields(submitted, projected_contribution_delta_cents=160)


class TestRollupRejectsAChildFreshUnderAnotherBasis:
    """A child whose two bases agree on the number and differ on the label."""

    @staticmethod
    def _sauce_weighted_under_an_uncosted_plate(api: ApiClient):
        """SUB-SAUCE FRESH under WEIGHTED_AVG_90D beneath a STALE PLATE-OILY.

        Left at the 2026-08-01 epoch reading of the logical clock (PRD 2.4): the
        one published window (effective from 2026-07-01, open-ended) is the sole
        candidate under both bases there, so the figure below is clock-independent.
        """
        oil = fixtures.create_ingredient(
            api,
            sku="PEANUT-OIL",
            name="Peanut Oil",
            base_uom=BaseUom.MILLILITER,
            pack_base_units=946,
            allergen_mask=8,
            kcal_per_base_unit_micros=8_000_000,
            sodium_mcg_per_base_unit=0,
        )
        fixtures.publish_price(
            api, oil["id"], 12_000_000, effective_from="2026-07-01T00:00:00.000Z"
        )
        sauce = fixtures.create_sub_recipe(
            api,
            code="SUB-SAUCE",
            name="Peanut Sauce",
            base_uom=BaseUom.MILLILITER,
            batch_yield_base_units=2000,
            portions_per_batch=20,
        )
        fixtures.add_ingredient_component(
            api, sauce["id"], oil["id"], ep_quantity_base_units=100
        )
        sauce = fixtures.rollup(api, sauce["id"], basis=CostBasis.WEIGHTED_AVG_90D)
        fixtures.review_and_activate_recipe(api, sauce["id"])

        plate = fixtures.create_recipe(
            api,
            code="PLATE-OILY",
            name="Oily Plate",
            batch_yield_base_units=5,
            portions_per_batch=5,
        )
        fixtures.add_sub_recipe_component(
            api, plate["id"], sauce["id"], ep_quantity_base_units=500
        )
        return {"oil": oil, "sauce": sauce, "plate": plate}

    def test_the_child_is_fresh_under_the_weighted_basis(
        self, api: ApiClient
    ) -> None:
        """One window covering the whole lookback gives 1268499 either way.

        PRD 3.3: "Because the figure is now expressed per million base units, the
        component's `pack_base_units_snapshot` is set to 1000000 so that the
        per-component arithmetic below is unchanged."

        Design: Corner/calculations/cost_rollup_with_a_child_fresh_under_a_different_basis_is_rejected
        """
        world = self._sauce_weighted_under_an_uncosted_plate(api)

        per_base_unit = round_half_up(12_000_000 * 1_000_000, 946)
        assert per_base_unit == 12_684_989_429
        assert_recipe(
            world["sauce"],
            cost_state=CostState.FRESH,
            cost_basis=CostBasis.WEIGHTED_AVG_90D,
            batch_cost_micros=round_half_up(100 * per_base_unit, 1_000_000),
        )
        assert_fields(world["sauce"], batch_cost_micros=1_268_499)

    def test_the_parent_roll_up_is_refused_on_the_basis_label_alone(
        self, api: ApiClient
    ) -> None:
        """The child is FRESH and its figure matches, and it is still refused.

        PRD 3.3: "Every active sub-recipe component's child recipe must already
        have `cost_state` `FRESH` *and* a `cost_basis` equal to the basis this
        roll-up was asked for; if any child fails either test the whole call fails
        with `ERR_COST_STALE`."

        Design: Corner/calculations/cost_rollup_with_a_child_fresh_under_a_different_basis_is_rejected
        """
        world = self._sauce_weighted_under_an_uncosted_plate(api)

        response = api.cost_rollup_recipe(
            world["plate"]["id"],
            {"basis": CostBasis.LATEST_PUBLISHED},
            COST_ANALYST,
        )

        validate_error(response, ApiErrorId.COST_STALE, 409)

    def test_the_refused_roll_up_writes_nothing_on_the_parent(
        self, api: ApiClient
    ) -> None:
        """No partial figures and no basis label on a failed call.

        PRD 2.10: "Requests are validated in one fixed order, and the **first**
        rule that fails determines the response; no later rule is evaluated and
        no partial mutation is persisted."

        Design: Corner/calculations/cost_rollup_with_a_child_fresh_under_a_different_basis_is_rejected
        """
        world = self._sauce_weighted_under_an_uncosted_plate(api)

        api.cost_rollup_recipe(
            world["plate"]["id"],
            {"basis": CostBasis.LATEST_PUBLISHED},
            COST_ANALYST,
        )

        assert_recipe(
            get_success_data(api.get_recipe(world["plate"]["id"])),
            cost_state=CostState.STALE,
            batch_cost_micros=0,
            portion_cost_micros=0,
            cost_basis=None,
        )

    def test_relabelling_the_child_lets_the_parent_through(
        self, api: ApiClient
    ) -> None:
        """The same 1268499 under the requested label costs the plate fine.

        PRD 3.3: "Children are never recomputed implicitly — a caller who wants a
        fresh three-level tree rolls up the deepest level first and works upward."

        Design: Corner/calculations/cost_rollup_with_a_child_fresh_under_a_different_basis_is_rejected
        """
        world = self._sauce_weighted_under_an_uncosted_plate(api)
        api.cost_rollup_recipe(
            world["plate"]["id"],
            {"basis": CostBasis.LATEST_PUBLISHED},
            COST_ANALYST,
        )

        relabelled = fixtures.rollup(
            api, world["sauce"]["id"], basis=CostBasis.LATEST_PUBLISHED
        )
        rolled = fixtures.rollup(
            api, world["plate"]["id"], basis=CostBasis.LATEST_PUBLISHED
        )

        assert_recipe(
            relabelled,
            cost_basis=CostBasis.LATEST_PUBLISHED,
            batch_cost_micros=world["sauce"]["batch_cost_micros"],
        )
        assert_recipe(
            rolled,
            cost_state=CostState.FRESH,
            cost_basis=CostBasis.LATEST_PUBLISHED,
            batch_cost_micros=round_half_up(500 * 1_268_499, 2_000),
            portion_cost_micros=round_half_up(317_125, 5),
        )
        assert_fields(
            rolled, batch_cost_micros=317_125, portion_cost_micros=63_425
        )


class TestLtoCostingHasNoProfitabilityGate:
    """An eighty-cent promotion on a hundred-cent plate."""

    @staticmethod
    def _loss_leader_planned(api: ApiClient):
        """A PLANNED campaign whose promo price is below the plate cost."""
        world = fixtures.grill_world_active_item(api)
        world["campaign"] = fixtures.plan_lto(
            api,
            world["menu_item"]["id"],
            window_start="2026-09-01T00:00:00.000Z",
            window_end="2026-10-01T00:00:00.000Z",
            promo_price_cents=80,
            forecast_units=10,
        )
        return world

    def test_planning_copies_the_region_and_zeroes_every_figure(
        self, api: ApiClient
    ) -> None:
        """MW comes from the item and nothing is computed yet.

        PRD 3.9: "It opens in `PLANNED` with `verdict` `PENDING`, a null
        `reviewed_at`, and `promo_plate_cost_cents`, `promo_food_cost_bps`,
        `forecast_contribution_cents`, `actual_units`,
        `actual_gross_sales_cents`, `promo_support_cost_cents`,
        `promo_contribution_cents` and `forecast_attainment_bps` all 0."

        Design: Corner/calculations/lto_costing_with_a_promo_price_below_the_plate_cost_still_succeeds
        """
        world = self._loss_leader_planned(api)

        assert_menu_item(world["menu_item"], plate_cost_cents=100)
        assert_lto_campaign(
            world["campaign"],
            status=LtoStatus.PLANNED,
            region_code=RegionCode.MW,
            verdict=LtoVerdict.PENDING,
            promo_plate_cost_cents=0,
            promo_food_cost_bps=0,
            forecast_contribution_cents=0,
            reviewed_at=None,
        )

    def test_the_food_cost_above_ten_thousand_is_not_clamped(
        self, api: ApiClient
    ) -> None:
        """12500 basis points of food cost, reported as it is.

        PRD 3.9: "computes `promo_food_cost_bps` as `promo_plate_cost_cents`
        multiplied by 10000, divided by `promo_price_cents`, rounded half up"

        Design: Corner/calculations/lto_costing_with_a_promo_price_below_the_plate_cost_still_succeeds
        """
        world = self._loss_leader_planned(api)

        costed = fixtures.cost_lto(api, world["campaign"]["id"])

        assert_lto_campaign(
            costed,
            promo_plate_cost_cents=100,
            promo_food_cost_bps=round_half_up(100 * 10_000, 80),
        )
        assert_fields(costed, promo_food_cost_bps=12_500)
        assert costed["promo_food_cost_bps"] > 10_000, "no clamp at parity"

    def test_the_negative_forecast_contribution_is_stored_as_such(
        self, api: ApiClient
    ) -> None:
        """Ten units at twenty cents of loss each.

        PRD 3.9: "Neither figure is constrained: a promotional price below the
        plate cost yields a negative `forecast_contribution_cents` and a
        `promo_food_cost_bps` above 10000, and the costing run still succeeds."

        Design: Corner/calculations/lto_costing_with_a_promo_price_below_the_plate_cost_still_succeeds
        """
        world = self._loss_leader_planned(api)

        costed = fixtures.cost_lto(api, world["campaign"]["id"])

        assert_lto_campaign(
            costed, forecast_contribution_cents=10 * (80 - 100)
        )
        assert_fields(costed, forecast_contribution_cents=-200)

    def test_the_campaign_reaches_costed_without_a_verdict(
        self, api: ApiClient
    ) -> None:
        """The director's judgement is not a validation.

        PRD 3.9: "Deciding whether a loss-leader is worth running is the
        director's judgement, not a validation. Costing increments the campaign's
        `version`."

        Design: Corner/calculations/lto_costing_with_a_promo_price_below_the_plate_cost_still_succeeds
        """
        world = self._loss_leader_planned(api)

        costed = fixtures.cost_lto(api, world["campaign"]["id"])

        assert_lto_campaign(
            costed,
            status=LtoStatus.COSTED,
            verdict=LtoVerdict.PENDING,
            version=world["campaign"]["version"] + 1,
        )


class TestLtoVerdictNeedsBothGates:
    """Two campaigns on one item, each failing a different gate."""

    @staticmethod
    def _campaign_a_launched(api: ApiClient):
        """A LAUNCHED August campaign with the clock parked at its window end.

        The logical clock reads 2026-08-01T00:00:00Z before the first clock write
        and is strictly monotonic (PRD 2.4), so the window sits at the epoch and
        the clock only ever moves forward from it.
        """
        world = fixtures.grill_world_active_item(api)
        campaign_a = fixtures.plan_lto(
            api,
            world["menu_item"]["id"],
            window_start="2026-08-01T00:00:00.000Z",
            window_end="2026-09-01T00:00:00.000Z",
            promo_price_cents=380,
            forecast_units=500,
        )
        costed_a = fixtures.cost_lto(api, campaign_a["id"])
        launched_a = fixtures.launch_lto(api, campaign_a["id"])
        fixtures.set_clock(api, "2026-09-01T00:00:00.000Z")
        world.update(
            {"campaign_a": campaign_a, "costed_a": costed_a, "launched_a": launched_a}
        )
        return world

    @staticmethod
    def _campaign_b_launched(api: ApiClient, world):
        """A September campaign planned after A has been closed and released.

        Its window abuts A's rather than overlapping it, so per PRD 3.9 it does
        not consume A's region capacity.
        """
        campaign_b = fixtures.plan_lto(
            api,
            world["menu_item"]["id"],
            window_start="2026-09-01T00:00:00.000Z",
            window_end="2026-10-01T00:00:00.000Z",
            promo_price_cents=380,
            forecast_units=100,
        )
        costed_b = fixtures.cost_lto(api, campaign_b["id"])
        fixtures.launch_lto(api, campaign_b["id"])
        fixtures.set_clock(api, "2026-10-01T00:00:00.000Z")
        return campaign_b, costed_b

    def test_the_first_campaign_costs_and_launches_on_a_healthy_forecast(
        self, api: ApiClient
    ) -> None:
        """2632 basis points of food cost against a 140000-cent forecast.

        PRD 3.9: "computes `forecast_contribution_cents` as `forecast_units`
        multiplied by the difference between `promo_price_cents` and
        `promo_plate_cost_cents`"

        Design: Corner/calculations/lto_post_promo_verdict_requires_both_the_contribution_and_attainment_gates
        """
        world = self._campaign_a_launched(api)

        assert_menu_item(world["menu_item"], plate_cost_cents=100)
        assert_lto_campaign(
            world["costed_a"],
            promo_food_cost_bps=round_half_up(100 * 10_000, 380),
            forecast_contribution_cents=500 * (380 - 100),
        )
        assert_fields(
            world["costed_a"],
            promo_food_cost_bps=2632,
            forecast_contribution_cents=140_000,
        )
        assert_lto_campaign(world["launched_a"], status=LtoStatus.LAUNCHED)

    def test_a_profitable_campaign_that_missed_its_forecast_is_unprofitable(
        self, api: ApiClient
    ) -> None:
        """80580 cents earned on 6000 basis points of attainment.

        PRD 3.9: "The `verdict` becomes `PROFITABLE` only when **both**
        conditions hold: `promo_contribution_cents` is at least the minimum
        contribution of 0 cents, and `forecast_attainment_bps` is at least the
        minimum attainment of 8000 basis points."

        Design: Corner/calculations/lto_post_promo_verdict_requires_both_the_contribution_and_attainment_gates
        """
        world = self._campaign_a_launched(api)

        closed = fixtures.close_lto_review(api, world["campaign_a"]["id"], 300, 114_000)

        support = round_half_up(114_000 * 300, 10_000)
        assert_lto_campaign(
            closed,
            status=LtoStatus.CLOSED,
            promo_support_cost_cents=support,
            promo_contribution_cents=114_000 - 300 * 100 - support,
            forecast_attainment_bps=round_half_up(300 * 10_000, 500),
            verdict=LtoVerdict.UNPROFITABLE,
            reviewed_at="2026-09-01T00:00:00.000Z",
        )
        assert_fields(
            closed,
            promo_support_cost_cents=3_420,
            promo_contribution_cents=80_580,
            forecast_attainment_bps=6_000,
        )
        assert closed["promo_contribution_cents"] >= 0, "the money gate passes"
        assert closed["forecast_attainment_bps"] < 8_000, "the volume gate fails"

    def test_the_close_review_releases_the_item(self, api: ApiClient) -> None:
        """The item stops promoting before the next campaign is planned.

        PRD 3.9: "The review stamps `reviewed_at`, sets the item's `is_lto` back
        to false, decrements the item's `open_lto_count`, increments the item's
        `version`, and increments the campaign's `version`."

        Design: Corner/calculations/lto_post_promo_verdict_requires_both_the_contribution_and_attainment_gates
        """
        world = self._campaign_a_launched(api)
        before = get_success_data(api.get_menu_item(world["menu_item"]["id"]))

        fixtures.close_lto_review(api, world["campaign_a"]["id"], 300, 114_000)

        assert_menu_item(
            get_success_data(api.get_menu_item(world["menu_item"]["id"])),
            is_lto=False,
            open_lto_count=0,
            version=before["version"] + 1,
        )

    def test_an_exactly_attained_campaign_that_lost_money_is_unprofitable(
        self, api: ApiClient
    ) -> None:
        """10000 basis points of attainment against a 1270-cent loss.

        PRD 3.9: "`promo_contribution_cents` is `actual_gross_sales_cents`, minus
        `actual_units` multiplied by `promo_plate_cost_cents`, minus
        `promo_support_cost_cents`"

        Design: Corner/calculations/lto_post_promo_verdict_requires_both_the_contribution_and_attainment_gates
        """
        world = self._campaign_a_launched(api)
        fixtures.close_lto_review(api, world["campaign_a"]["id"], 300, 114_000)
        campaign_b, costed_b = self._campaign_b_launched(api, world)

        closed = fixtures.close_lto_review(api, campaign_b["id"], 100, 9_000)

        support = round_half_up(9_000 * 300, 10_000)
        assert_lto_campaign(costed_b, forecast_contribution_cents=100 * (380 - 100))
        assert_fields(costed_b, forecast_contribution_cents=28_000)
        assert_lto_campaign(
            closed,
            status=LtoStatus.CLOSED,
            promo_support_cost_cents=support,
            promo_contribution_cents=9_000 - 100 * 100 - support,
            forecast_attainment_bps=round_half_up(100 * 10_000, 100),
            verdict=LtoVerdict.UNPROFITABLE,
        )
        assert_fields(
            closed,
            promo_support_cost_cents=270,
            promo_contribution_cents=-1_270,
            forecast_attainment_bps=10_000,
        )
        assert closed["forecast_attainment_bps"] >= 8_000, "the volume gate passes"
        assert closed["promo_contribution_cents"] < 0, "the money gate fails"

    def test_neither_gate_alone_earns_a_profitable_verdict(
        self, api: ApiClient
    ) -> None:
        """One campaign passed each gate and both read UNPROFITABLE.

        PRD 3.9: "Otherwise it becomes `UNPROFITABLE`. Both must hold because a
        promotion that made money on a fraction of its forecast volume
        cannibalised the base menu rather than growing it, and should not be
        renewed."

        Design: Corner/calculations/lto_post_promo_verdict_requires_both_the_contribution_and_attainment_gates
        """
        world = self._campaign_a_launched(api)
        closed_a = fixtures.close_lto_review(
            api, world["campaign_a"]["id"], 300, 114_000
        )
        campaign_b, _ = self._campaign_b_launched(api, world)

        closed_b = fixtures.close_lto_review(api, campaign_b["id"], 100, 9_000)

        assert closed_a["verdict"] == LtoVerdict.UNPROFITABLE
        assert closed_b["verdict"] == LtoVerdict.UNPROFITABLE
        assert (
            closed_a["promo_contribution_cents"] >= 0
            and closed_b["forecast_attainment_bps"] >= 8_000
        ), "each campaign satisfies exactly one of the two conditions"

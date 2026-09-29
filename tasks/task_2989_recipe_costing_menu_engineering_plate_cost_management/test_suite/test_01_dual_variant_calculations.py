"""Two calculations that each have two variants, priced from identical inputs.

The cost roll-up prices the same component set two ways, and a period review
values the same mix and the same physical count two ways.  In both pairs the
inputs are byte-for-byte identical and only the named variant differs, so any
implementation that collapses the two variants into one is caught here.
"""

from test_helpers import (
    ApiClient,
    CostBasis,
    CostState,
    MarginClass,
    ReviewBasis,
    ReviewStatus,
    VarianceFlag,
    assert_count_line,
    assert_fields,
    assert_mix_line,
    assert_period_review,
    assert_recipe,
    assert_recipe_component,
    fixtures,
    get_success_data,
    round_half_up,
    single_row,
)


class TestRollupBasisVariants:
    """LATEST_PUBLISHED against WEIGHTED_AVG_90D on one sub-recipe."""

    @staticmethod
    def _two_published_windows(api: ApiClient):
        """Cheddar with a bounded 22000000 window abutting an open-ended 25000000."""
        cheddar = fixtures.create_cheddar(api)
        fixtures.publish_price(
            api,
            cheddar["id"],
            22_000_000,
            effective_from="2026-05-01T00:00:00.000Z",
            effective_to="2026-07-01T00:00:00.000Z",
        )
        second_feed = fixtures.publish_price(
            api,
            cheddar["id"],
            25_000_000,
            effective_from="2026-07-01T00:00:00.000Z",
        )
        recipe = fixtures.create_sub_recipe(
            api,
            code="SUB-CHEESE",
            name="Cheese Sauce Base",
            batch_yield_base_units=1000,
            portions_per_batch=10,
        )
        component = fixtures.add_ingredient_component(
            api, recipe["id"], cheddar["id"], ep_quantity_base_units=500
        )
        return cheddar, second_feed, recipe, component

    def test_abutting_window_supersedes_nothing_so_both_rows_stay_published(
        self, api: ApiClient
    ) -> None:
        """The second publication truncates nothing, leaving two live windows.

        PRD 3.2: "A new line whose `effective_from` falls exactly on an existing
        bounded row's `effective_to` is *adjacent*, not overlapping, and is
        accepted."

        Design: Difficulty/dual_variant_calc/recipe_cost_rollup_latest_published_versus_weighted_average_on_recipe
        """
        _, second_feed, _, _ = self._two_published_windows(api)

        assert_fields(second_feed, superseded_price_count=0)

    def test_latest_published_reads_only_the_open_ended_row(
        self, api: ApiClient
    ) -> None:
        """One row wins outright: the newest window in force at the clock.

        PRD 3.3: "Surviving candidates are ranked by `effective_from` descending
        and then `created_at` ascending, and the first row wins."

        Design: Difficulty/dual_variant_calc/recipe_cost_rollup_latest_published_versus_weighted_average_on_recipe
        """
        _, _, recipe, component = self._two_published_windows(api)

        rolled = fixtures.rollup(api, recipe["id"], basis=CostBasis.LATEST_PUBLISHED)

        # ap 500 at 25000000 per 2268-gram pack, rounded half up, then per portion.
        assert_recipe(
            rolled,
            cost_basis=CostBasis.LATEST_PUBLISHED,
            cost_state=CostState.FRESH,
            batch_cost_micros=round_half_up(500 * 25_000_000, 2268),
            portion_cost_micros=round_half_up(
                round_half_up(500 * 25_000_000, 2268), 10
            ),
        )
        assert_fields(rolled, batch_cost_micros=5_511_464, portion_cost_micros=551_146)
        assert_recipe_component(
            get_success_data(api.get_recipe_component(component["id"])),
            unit_cost_micros_used=25_000_000,
            pack_base_units_snapshot=2268,
            extended_cost_micros=5_511_464,
        )

    def test_weighted_average_duration_weights_both_rows(
        self, api: ApiClient
    ) -> None:
        """Fifty-nine days of the old price against thirty-one of the new.

        PRD 3.3: "Multiply each candidate's per-base-unit figure by its weight,
        sum those products, sum the weights, divide the first sum by the second
        and round half up"

        Design: Difficulty/dual_variant_calc/recipe_cost_rollup_latest_published_versus_weighted_average_on_recipe
        """
        _, _, recipe, _ = self._two_published_windows(api)

        rolled = fixtures.rollup(api, recipe["id"], basis=CostBasis.WEIGHTED_AVG_90D)

        old_per_base_unit = round_half_up(22_000_000 * 1_000_000, 2268)
        new_per_base_unit = round_half_up(25_000_000 * 1_000_000, 2268)
        weighted = round_half_up(
            old_per_base_unit * 59 + new_per_base_unit * 31, 59 + 31
        )
        assert weighted == 10_155_790_712
        assert_recipe(
            rolled,
            cost_basis=CostBasis.WEIGHTED_AVG_90D,
            cost_state=CostState.FRESH,
            batch_cost_micros=round_half_up(500 * weighted, 1_000_000),
            portion_cost_micros=507_790,
        )
        assert_fields(rolled, batch_cost_micros=5_077_895)

    def test_weighted_average_repins_the_component_to_a_per_million_divisor(
        self, api: ApiClient
    ) -> None:
        """The component snapshot becomes 1000000 under the weighted basis.

        PRD 3.3: "Because the figure is now expressed per million base units,
        the component's `pack_base_units_snapshot` is set to 1000000 so that the
        per-component arithmetic below is unchanged."

        Design: Difficulty/dual_variant_calc/recipe_cost_rollup_latest_published_versus_weighted_average_on_recipe
        """
        _, _, recipe, component = self._two_published_windows(api)

        fixtures.rollup(api, recipe["id"], basis=CostBasis.LATEST_PUBLISHED)
        fixtures.rollup(api, recipe["id"], basis=CostBasis.WEIGHTED_AVG_90D)

        assert_recipe_component(
            get_success_data(api.get_recipe_component(component["id"])),
            unit_cost_micros_used=10_155_790_712,
            pack_base_units_snapshot=1_000_000,
            extended_cost_micros=5_077_895,
        )

    def test_the_two_bases_disagree_on_identical_component_data(
        self, api: ApiClient
    ) -> None:
        """Same component, same two price rows, two different batch costs.

        PRD 3.3: "The basis is either `LATEST_PUBLISHED` or `WEIGHTED_AVG_90D`,
        defaults to `LATEST_PUBLISHED` when omitted, and is recorded on the
        recipe as `cost_basis`."

        Design: Difficulty/dual_variant_calc/recipe_cost_rollup_latest_published_versus_weighted_average_on_recipe
        """
        _, _, recipe, _ = self._two_published_windows(api)

        latest = fixtures.rollup(
            api, recipe["id"], basis=CostBasis.LATEST_PUBLISHED
        )
        weighted = fixtures.rollup(
            api, recipe["id"], basis=CostBasis.WEIGHTED_AVG_90D
        )

        assert (
            latest["batch_cost_micros"] - weighted["batch_cost_micros"] == 433_569
        ), "the two bases must not collapse onto one figure"


class TestPeriodReviewBasisVariants:
    """SALES_MIX_BASED against USAGE_BASED over one identical period."""

    @staticmethod
    def _classified_review(api: ApiClient, world, unit_id: str, basis: str):
        """Open one review under the given basis and classify it."""
        review = fixtures.open_review(
            api,
            unit_id,
            period_start="2026-07-01T00:00:00.000Z",
            period_end="2026-08-01T00:00:00.000Z",
            basis=basis,
        )
        mix_line = fixtures.load_mix_line(
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
        fixtures.classify_review(api, review["id"])
        return review, mix_line, count_line

    @staticmethod
    def _twin_worlds(api: ApiClient):
        """One priced, plated, live menu item and one store to review it in."""
        world = fixtures.grill_world_active_item(api)
        unit = fixtures.create_unit(api, code="UNIT-MW-01", name="Downtown MW")
        return world, unit

    def test_sales_mix_basis_values_the_period_at_the_snapshot_plate_cost(
        self, api: ApiClient
    ) -> None:
        """Fifty units at the 100-cent snapshot is a 5000-cent theory.

        PRD 3.8: "Under `SALES_MIX_BASED` it is the sum over the mix lines of
        `units_sold` multiplied by `plate_cost_cents_snapshot`"

        Design: Difficulty/dual_variant_calc/theoretical_versus_actual_variance_sales_mix_versus_usage_basis_on_period_review
        """
        world, unit = self._twin_worlds(api)
        assert world["menu_item"]["plate_cost_cents"] == 100

        review, mix_line, _ = self._classified_review(
            api, world, unit["id"], ReviewBasis.SALES_MIX_BASED
        )
        closed = fixtures.close_review(api, review["id"])

        assert_mix_line(
            single_row(fixtures.mix_line_rows(api, review["id"])),
            plate_cost_cents_snapshot=100,
        )
        assert_period_review(
            closed,
            status=ReviewStatus.CLOSED,
            basis=ReviewBasis.SALES_MIX_BASED,
            theoretical_food_cost_cents=50 * 100,
            actual_food_cost_cents=5101,
            variance_bps=202,
            variance_flag=VarianceFlag.WITHIN_TOLERANCE,
        )
        assert mix_line["units_sold"] == 50

    def test_usage_basis_values_the_exploded_quantity_at_todays_price(
        self, api: ApiClient
    ) -> None:
        """The same period costs 4850 cents in theory under the usage basis.

        PRD 3.8: "Under `USAGE_BASED` it is computed from the count lines
        instead: for each line take `expected_base_units` multiplied by the
        selected price row's `pack_cost_micros`, divided by that line's
        `pack_base_units_snapshot`, rounded half up to micro-dollars; sum those;
        divide by 10000 and round half up to cents."

        Design: Difficulty/dual_variant_calc/theoretical_versus_actual_variance_sales_mix_versus_usage_basis_on_period_review
        """
        world, unit = self._twin_worlds(api)

        review, _, count_line = self._classified_review(
            api, world, unit["id"], ReviewBasis.USAGE_BASED
        )
        closed = fixtures.close_review(api, review["id"])

        assert count_line["expected_base_units"] == 5000
        assert_period_review(
            closed,
            basis=ReviewBasis.USAGE_BASED,
            theoretical_food_cost_cents=round_half_up(
                round_half_up(5000 * 22_000_000, 2268), 10_000
            ),
            variance_bps=518,
            variance_flag=VarianceFlag.OVER_TOLERANCE,
        )
        assert_fields(closed, theoretical_food_cost_cents=4850)

    def test_the_actual_side_is_basis_independent(self, api: ApiClient) -> None:
        """Both bases value the physical count identically and flag it oppositely.

        PRD 3.8: "**both** review bases use `LATEST_PUBLISHED` prices for this
        valuation; the review's `basis` selects the theoretical figure, not the
        valuation of actual usage"

        Design: Difficulty/dual_variant_calc/theoretical_versus_actual_variance_sales_mix_versus_usage_basis_on_period_review
        """
        world, unit = self._twin_worlds(api)

        sm_review, _, _ = self._classified_review(
            api, world, unit["id"], ReviewBasis.SALES_MIX_BASED
        )
        ub_review, _, _ = self._classified_review(
            api, world, unit["id"], ReviewBasis.USAGE_BASED
        )
        sm_closed = fixtures.close_review(api, sm_review["id"])
        ub_closed = fixtures.close_review(api, ub_review["id"])

        assert sm_closed["actual_food_cost_cents"] == 5101
        assert ub_closed["actual_food_cost_cents"] == 5101
        for review_id in (sm_review["id"], ub_review["id"]):
            assert_count_line(
                single_row(fixtures.count_line_rows(api, review_id)),
                used_base_units=5259,
                expected_base_units=5000,
                variance_base_units=259,
                valued_usage_micros=51_013_228,
            )
        assert sm_closed["variance_flag"] == VarianceFlag.WITHIN_TOLERANCE
        assert ub_closed["variance_flag"] == VarianceFlag.OVER_TOLERANCE

    def test_tolerance_is_judged_on_the_absolute_variance(
        self, api: ApiClient
    ) -> None:
        """202 basis points sits inside the tolerance, 518 outside it.

        PRD 3.8: "`variance_flag` is `OVER_TOLERANCE` when the **absolute**
        value of `variance_bps` exceeds the 300-basis-point tolerance, and
        `WITHIN_TOLERANCE` otherwise."

        Design: Difficulty/dual_variant_calc/theoretical_versus_actual_variance_sales_mix_versus_usage_basis_on_period_review
        """
        world, unit = self._twin_worlds(api)

        sm_review, _, _ = self._classified_review(
            api, world, unit["id"], ReviewBasis.SALES_MIX_BASED
        )
        ub_review, _, _ = self._classified_review(
            api, world, unit["id"], ReviewBasis.USAGE_BASED
        )
        sm_closed = fixtures.close_review(api, sm_review["id"])
        ub_closed = fixtures.close_review(api, ub_review["id"])

        assert abs(sm_closed["variance_bps"]) <= 300
        assert abs(ub_closed["variance_bps"]) > 300
        assert_fields(
            single_row(fixtures.mix_line_rows(api, sm_review["id"])),
            margin_class=MarginClass.STAR,
        )

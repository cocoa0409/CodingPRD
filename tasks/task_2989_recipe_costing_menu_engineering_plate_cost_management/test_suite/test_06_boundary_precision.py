"""Values sitting exactly on a limit rather than near one.

Both scenarios are arranged so that every division is exact, which leaves the
comparison itself as the only thing under test: one line lands precisely on a
popularity bar and one campaign lands precisely on a contribution floor and on
the inclusive edge of a temporal gate.
"""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    CULINARY_DIRECTOR,
    LtoDecision,
    LtoStatus,
    LtoVerdict,
    MarginClass,
    MenuItemStatus,
    ReviewStatus,
    assert_lto_campaign,
    assert_menu_item,
    assert_mix_line,
    assert_period_review,
    factories,
    fixtures,
    get_success_data,
    round_half_up,
    validate_error,
    validate_paginated,
)


class TestMixShareExactlyOnThePopularityBar:
    """Two lines, one of them at 3500 basis points to the point."""

    @staticmethod
    def _two_line_review(api: ApiClient):
        """Two items on one recipe, sold in an exactly divisible 1300/700 mix."""
        world = fixtures.grill_world_active_item(
            api,
            code="MI-GRILL-A",
            name="Grilled Cheese Large",
            current_price_cents=1099,
        )
        item_b = fixtures.add_menu_item_to_world(
            api,
            world,
            code="MI-GRILL-B",
            name="Grilled Cheese Small",
            current_price_cents=985,
        )
        unit = fixtures.create_unit(api, code="UNIT-MW-01", name="Downtown MW")
        review = fixtures.open_review(api, unit["id"])
        line_a = fixtures.load_mix_line(
            api,
            review["id"],
            world["menu_item"]["id"],
            units_sold=1300,
            gross_sales_cents=1_428_700,
        )
        after_first = get_success_data(api.get_period_review(review["id"]))
        line_b = fixtures.load_mix_line(
            api,
            review["id"],
            item_b["id"],
            units_sold=700,
            gross_sales_cents=689_500,
        )
        return {
            "item_a": world["menu_item"],
            "item_b": item_b,
            "review": review,
            "after_first": after_first,
            "line_a": line_a,
            "line_b": line_b,
        }

    @staticmethod
    def _classified_lines(api: ApiClient, world):
        """The review's two mix lines in their creation order."""
        rows = fixtures.mix_line_rows(api, world["review"]["id"])
        assert len(rows) == 2, f"expected two mix lines, got {len(rows)}"
        return rows[0], rows[1]

    def test_the_two_items_share_one_plate_cost_so_only_price_separates_them(
        self, api: ApiClient
    ) -> None:
        """Both items freeze a 100-cent snapshot off the same recipe.

        PRD 3.8: "The line freezes `plate_cost_cents_snapshot` from the item's
        `plate_cost_cents` at the moment of loading"

        Design: Difficulty/boundary_precision_check/mix_percentage_exactly_at_popularity_threshold_classifies_as_plowhorse
        """
        world = self._two_line_review(api)

        assert_menu_item(world["item_a"], plate_cost_cents=100, current_price_cents=1099)
        assert_menu_item(world["item_b"], plate_cost_cents=100, current_price_cents=985)
        assert_mix_line(world["line_a"], plate_cost_cents_snapshot=100)
        assert_mix_line(world["line_b"], plate_cost_cents_snapshot=100)

    def test_the_first_mix_line_auto_advances_the_review(
        self, api: ApiClient
    ) -> None:
        """No explicit request moves OPEN to MIX_LOADED.

        PRD 3.8: "The **first** line auto-advances the review from `OPEN` to
        `MIX_LOADED` without any explicit request; later lines leave it in
        `MIX_LOADED`."

        Design: Difficulty/boundary_precision_check/mix_percentage_exactly_at_popularity_threshold_classifies_as_plowhorse
        """
        world = self._two_line_review(api)

        assert_period_review(world["after_first"], status=ReviewStatus.MIX_LOADED)
        assert_period_review(
            get_success_data(api.get_period_review(world["review"]["id"])),
            status=ReviewStatus.MIX_LOADED,
            total_units_sold=2000,
            total_gross_sales_cents=1_428_700 + 689_500,
        )

    def test_a_two_line_review_sets_the_bar_at_three_thousand_five_hundred(
        self, api: ApiClient
    ) -> None:
        """7000 over two lines, and a 959-cent weighted average margin.

        PRD 3.8: "it computes `popularity_threshold_bps` as the popularity factor
        of 7000 basis points divided by the number of mix lines, rounded half up
        — so a two-line review sets the bar at 3500 basis points and a five-line
        review at 1400."

        Design: Difficulty/boundary_precision_check/mix_percentage_exactly_at_popularity_threshold_classifies_as_plowhorse
        """
        world = self._two_line_review(api)

        classified = fixtures.classify_review(api, world["review"]["id"])

        assert_period_review(
            classified,
            status=ReviewStatus.CLASSIFIED,
            total_units_sold=2000,
            popularity_threshold_bps=round_half_up(7000, 2),
            margin_threshold_cents=round_half_up(1300 * 999 + 700 * 885, 2000),
        )
        assert classified["popularity_threshold_bps"] == 3500
        assert classified["margin_threshold_cents"] == 959, (
            "959.1 rounds half up to 959"
        )

    def test_the_dominant_line_is_popular_and_high_margin(
        self, api: ApiClient
    ) -> None:
        """6500 basis points of the mix at 999 cents of contribution is a STAR.

        PRD 3.8: "The quadrant follows: `STAR` when popular and high-margin,
        `PLOWHORSE` when popular but not high-margin, `PUZZLE` when high-margin
        but not popular, and `DOG` when neither."

        Design: Difficulty/boundary_precision_check/mix_percentage_exactly_at_popularity_threshold_classifies_as_plowhorse
        """
        world = self._two_line_review(api)

        fixtures.classify_review(api, world["review"]["id"])

        line_a, _ = self._classified_lines(api, world)
        assert line_a["id"] == world["line_a"]["id"], (
            "mix lines are listed created_at ascending"
        )
        assert_mix_line(
            line_a,
            mix_pct_bps=round_half_up(1300 * 10_000, 2000),
            cm_per_unit_cents=round_half_up(1_428_700, 1300) - 100,
            margin_class=MarginClass.STAR,
        )
        assert_mix_line(line_a, mix_pct_bps=6500, cm_per_unit_cents=999)

    def test_the_line_exactly_on_the_bar_counts_as_popular(
        self, api: ApiClient
    ) -> None:
        """3500 against 3500 is PLOWHORSE, which an exclusive test would call DOG.

        PRD 3.8: "A line is popular when its `mix_pct_bps` is greater than **or
        equal to** `popularity_threshold_bps`, and high-margin when its
        `cm_per_unit_cents` is greater than **or equal to**
        `margin_threshold_cents`. Both comparisons are inclusive, so a line
        sitting exactly on a threshold falls on the favourable side of it."

        Design: Difficulty/boundary_precision_check/mix_percentage_exactly_at_popularity_threshold_classifies_as_plowhorse
        """
        world = self._two_line_review(api)

        fixtures.classify_review(api, world["review"]["id"])

        _, line_b = self._classified_lines(api, world)
        assert line_b["id"] == world["line_b"]["id"]
        assert_mix_line(
            line_b,
            mix_pct_bps=round_half_up(700 * 10_000, 2000),
            cm_per_unit_cents=round_half_up(689_500, 700) - 100,
            margin_class=MarginClass.PLOWHORSE,
        )
        assert line_b["mix_pct_bps"] == 3500, "exactly on the bar, not either side"
        assert line_b["cm_per_unit_cents"] == 885
        assert line_b["cm_per_unit_cents"] < 959, "strictly below the margin bar"
        assert line_b["margin_class"] != MarginClass.DOG

    def test_each_class_is_copied_onto_its_own_menu_item(
        self, api: ApiClient
    ) -> None:
        """The items end up STAR and PLOWHORSE respectively.

        PRD 3.8: "Classification writes both thresholds onto the review and all
        three computed fields onto every line, copies each line's `margin_class`
        onto its menu item and increments each of those items' `version`, and
        increments the review's `version`."

        Design: Difficulty/boundary_precision_check/mix_percentage_exactly_at_popularity_threshold_classifies_as_plowhorse
        """
        world = self._two_line_review(api)

        fixtures.classify_review(api, world["review"]["id"])

        assert_menu_item(
            get_success_data(api.get_menu_item(world["item_a"]["id"])),
            margin_class=MarginClass.STAR,
        )
        assert_menu_item(
            get_success_data(api.get_menu_item(world["item_b"]["id"])),
            margin_class=MarginClass.PLOWHORSE,
        )


class TestZeroUnitCloseReviewIsUnprofitable:
    """A contribution met at its limit is not enough on its own."""

    @staticmethod
    def _launched_campaign(api: ApiClient):
        """A LAUNCHED promotion with the clock parked exactly on window_end."""
        world = fixtures.grill_world_active_item(api)
        planned = fixtures.plan_lto(
            api,
            world["menu_item"]["id"],
            window_start="2026-08-10T00:00:00.000Z",
            window_end="2026-08-20T00:00:00.000Z",
            promo_price_cents=380,
            forecast_units=500,
        )
        costed = fixtures.cost_lto(api, planned["id"])
        launched = fixtures.launch_lto(api, planned["id"])
        fixtures.set_clock(api, "2026-08-20T00:00:00.000Z")
        world.update(
            {"planned": planned, "costed": costed, "launched": launched}
        )
        return world

    def test_the_campaign_reaches_launched_on_pinned_forecast_figures(
        self, api: ApiClient
    ) -> None:
        """PLANNED, then 2632 basis points and 140000 cents, then LAUNCHED.

        PRD 3.9: "computes `promo_food_cost_bps` as `promo_plate_cost_cents`
        multiplied by 10000, divided by `promo_price_cents`, rounded half up; and
        computes `forecast_contribution_cents` as `forecast_units` multiplied by
        the difference between `promo_price_cents` and `promo_plate_cost_cents`."

        Design: Difficulty/boundary_precision_check/lto_close_review_with_zero_actual_units_is_unprofitable_at_the_contribution_boundary
        """
        world = self._launched_campaign(api)

        assert_lto_campaign(
            world["planned"], status=LtoStatus.PLANNED, verdict=LtoVerdict.PENDING
        )
        assert_lto_campaign(
            world["costed"],
            status=LtoStatus.COSTED,
            promo_plate_cost_cents=100,
            promo_food_cost_bps=round_half_up(100 * 10_000, 380),
            forecast_contribution_cents=500 * (380 - 100),
        )
        assert world["costed"]["promo_food_cost_bps"] == 2632
        assert world["costed"]["forecast_contribution_cents"] == 140_000
        assert_lto_campaign(world["launched"], status=LtoStatus.LAUNCHED)

    def test_a_clock_exactly_on_window_end_satisfies_the_temporal_gate(
        self, api: ApiClient
    ) -> None:
        """The review is admitted rather than refused as premature.

        PRD 3.9: "The current logical clock must have reached `window_end`,
        otherwise `ERR_EFFECTIVE_DATE_NOT_REACHED`: a promotion is judged only
        after it is over."

        Design: Difficulty/boundary_precision_check/lto_close_review_with_zero_actual_units_is_unprofitable_at_the_contribution_boundary
        """
        world = self._launched_campaign(api)

        closed = fixtures.close_lto_review(
            api, world["planned"]["id"], actual_units=0, actual_gross_sales_cents=0
        )

        assert_lto_campaign(
            closed,
            status=LtoStatus.CLOSED,
            actual_units=0,
            actual_gross_sales_cents=0,
        )

    def test_a_zero_sales_close_produces_a_contribution_of_exactly_zero(
        self, api: ApiClient
    ) -> None:
        """Support 0 and contribution 0, the inclusive limit of the first arm.

        PRD 3.9: "`promo_contribution_cents` is `actual_gross_sales_cents`, minus
        `actual_units` multiplied by `promo_plate_cost_cents`, minus
        `promo_support_cost_cents`"

        Design: Difficulty/boundary_precision_check/lto_close_review_with_zero_actual_units_is_unprofitable_at_the_contribution_boundary
        """
        world = self._launched_campaign(api)

        closed = fixtures.close_lto_review(
            api, world["planned"]["id"], actual_units=0, actual_gross_sales_cents=0
        )

        assert_lto_campaign(
            closed,
            promo_support_cost_cents=round_half_up(0 * 300, 10_000),
            promo_contribution_cents=0 - 0 * 100 - 0,
            forecast_attainment_bps=round_half_up(0 * 10_000, 500),
        )
        assert closed["promo_contribution_cents"] == 0
        assert closed["forecast_attainment_bps"] == 0

    def test_the_verdict_is_an_and_of_both_arms_not_a_sign_test(
        self, api: ApiClient
    ) -> None:
        """The met contribution floor loses to the failed attainment floor.

        PRD 3.9: "A campaign with zero actual units and zero gross sales has a
        contribution of exactly 0, which satisfies the contribution floor, but an
        attainment of 0 basis points, which does not — so it is `UNPROFITABLE`."

        Design: Difficulty/boundary_precision_check/lto_close_review_with_zero_actual_units_is_unprofitable_at_the_contribution_boundary
        """
        world = self._launched_campaign(api)

        closed = fixtures.close_lto_review(
            api, world["planned"]["id"], actual_units=0, actual_gross_sales_cents=0
        )

        assert closed["promo_contribution_cents"] >= 0, "the first arm is satisfied"
        assert closed["forecast_attainment_bps"] < 8000, "the second arm is not"
        assert_lto_campaign(closed, verdict=LtoVerdict.UNPROFITABLE)

    def test_renewing_an_unprofitable_promotion_is_refused(
        self, api: ApiClient
    ) -> None:
        """The RENEW arm reports a state error rather than minting a successor.

        PRD 3.9: "The `RENEW` arm requires the campaign's `verdict` to be
        `PROFITABLE`; renewing an unprofitable promotion is refused with
        `ERR_LTO_INVALID_STATE`."

        Design: Difficulty/boundary_precision_check/lto_close_review_with_zero_actual_units_is_unprofitable_at_the_contribution_boundary
        """
        world = self._launched_campaign(api)
        fixtures.close_lto_review(
            api, world["planned"]["id"], actual_units=0, actual_gross_sales_cents=0
        )

        response = api.decide_lto_campaign(
            world["planned"]["id"],
            factories.decide_payload(LtoDecision.RENEW),
            CULINARY_DIRECTOR,
        )

        validate_error(response, ApiErrorId.LTO_INVALID_STATE)
        rows, meta = validate_paginated(
            api.list_lto_campaigns({"menu_item_id": world["menu_item"]["id"]})
        )
        assert meta["total_count"] == 1, "the refused decision minted no successor"
        assert_lto_campaign(rows[0], status=LtoStatus.CLOSED)

    def test_the_failed_decision_never_reaches_the_retire_suspension(
        self, api: ApiClient
    ) -> None:
        """The item is released by the close and left sellable.

        PRD 3.9: "The review stamps `reviewed_at`, sets the item's `is_lto` back
        to false, decrements the item's `open_lto_count`, increments the item's
        `version`, and increments the campaign's `version`."

        Design: Difficulty/boundary_precision_check/lto_close_review_with_zero_actual_units_is_unprofitable_at_the_contribution_boundary
        """
        world = self._launched_campaign(api)
        fixtures.close_lto_review(
            api, world["planned"]["id"], actual_units=0, actual_gross_sales_cents=0
        )

        api.decide_lto_campaign(
            world["planned"]["id"],
            factories.decide_payload(LtoDecision.RENEW),
            CULINARY_DIRECTOR,
        )

        assert_menu_item(
            get_success_data(api.get_menu_item(world["menu_item"]["id"])),
            status=MenuItemStatus.ACTIVE,
            is_lto=False,
            open_lto_count=0,
        )

"""Immediate consistency: derived fields in the write's own body, cascades settled on return.

One world is driven through a count-line write, a classification run and a price
publication, and after every one of those calls the very next read is asserted
without a retry, a second attempt or a re-read. What must *not* move in the same
breath is pinned just as hard: a price move is not a specification move.
"""

from test_helpers import (
    ApiClient,
    CLOCK_EPOCH,
    COST_ANALYST,
    CostState,
    IngredientPriceStatus,
    MarginClass,
    MenuItemStatus,
    PriceFeedStatus,
    RecipeStatus,
    RegionCode,
    ReviewStatus,
    SyncState,
    assert_count_line,
    assert_fields,
    assert_instant_equals,
    assert_menu_item,
    assert_mix_line,
    assert_page_meta,
    assert_period_review,
    assert_price_feed,
    assert_recipe,
    factories,
    fixtures,
    floor_div,
    get_success_data,
    micros_to_cents,
    plate_cost_micros,
    round_half_up,
    validate_paginated,
)

SECOND_FEED_DATE = "2026-07-15T00:00:00.000Z"
SECOND_FEED_PACK_COST_MICROS = 33_000_000

OPENING_BASE_UNITS = 10_500
RECEIVED_BASE_UNITS = 0
COUNTED_BASE_UNITS = 300


class TestEveryCascadeIsVisibleToTheVeryNextRead:
    """No lag, no retry loop, and no collateral invalidation either."""

    @staticmethod
    def _july_world(api: ApiClient):
        """MI-GRILL-MW ACTIVE at the July price, with one store and one loaded mix."""
        world = fixtures.grill_world_active_item(api)
        world["unit"] = fixtures.create_unit(api)
        world["review"] = fixtures.open_review(api, world["unit"]["id"])
        world["mix_line"] = fixtures.load_mix_line(
            api, world["review"]["id"], world["menu_item"]["id"]
        )
        return world

    @staticmethod
    def _second_feed(api: ApiClient, ingredient_id: str):
        """A mid-July re-price at 33000000 micros, held in DRAFT until the trigger."""
        feed = fixtures.open_price_feed(api, feed_date=SECOND_FEED_DATE)
        line = fixtures.add_price_line(
            api,
            feed["id"],
            ingredient_id,
            pack_cost_micros=SECOND_FEED_PACK_COST_MICROS,
            effective_from=SECOND_FEED_DATE,
        )
        return feed, line

    @staticmethod
    def _count_line_response(api: ApiClient, period_review_id: str, ingredient_id: str):
        return api.add_count_line(
            period_review_id,
            factories.count_line_payload(
                ingredient_id,
                opening_base_units=OPENING_BASE_UNITS,
                received_base_units=RECEIVED_BASE_UNITS,
                counted_base_units=COUNTED_BASE_UNITS,
            ),
            COST_ANALYST,
        )

    @staticmethod
    def _per_portion_micro_figure() -> int:
        """The explosion's per-portion figure for cheddar in PLATE-GRILL."""
        return round_half_up(400 * 1_000_000, 4)

    @staticmethod
    def _plate_cost_cents() -> int:
        return micros_to_cents(
            plate_cost_micros(round_half_up(3_880_071, 4), RegionCode.MW)
        )

    def test_the_count_line_write_answers_with_its_own_usage_and_variance(
        self, api: ApiClient
    ) -> None:
        """The POST body already carries used, expected, variance and sync_state.

        PRD 3.8: "From those, `used_base_units` is `opening_base_units` plus
        `received_base_units` minus `counted_base_units`, floored at zero so an
        impossible count never reports negative consumption. Creation also derives
        `expected_base_units` from the currently loaded mix by the explosion described
        next, sets `variance_base_units` to `used_base_units` minus
        `expected_base_units`, sets `sync_state` to `CURRENT`"

        Design: Corner/consistency_model/every_cascade_and_every_derived_field_is_visible_to_the_very_next_read
        """
        world = self._july_world(api)
        written = get_success_data(
            self._count_line_response(api, world["review"]["id"], world["cheddar"]["id"]),
            201,
        )
        assert_count_line(
            written,
            used_base_units=OPENING_BASE_UNITS + RECEIVED_BASE_UNITS - COUNTED_BASE_UNITS,
            expected_base_units=10_000,
            variance_base_units=200,
            sync_state=SyncState.CURRENT,
        )
        assert written["used_base_units"] == 10_200, "10500 + 0 - 300"

    def test_the_expected_usage_is_exploded_before_the_write_returns(
        self, api: ApiClient
    ) -> None:
        """400 grams over 4 portions, sold 100 times, resolved in micro-units.

        PRD 3.8: "An ingredient component on that very ingredient contributes its
        `ap_quantity_base_units` multiplied by 1000000, divided by the recipe's
        `portions_per_batch`, rounded half up."

        Design: Corner/consistency_model/every_cascade_and_every_derived_field_is_visible_to_the_very_next_read
        """
        world = self._july_world(api)
        written = get_success_data(
            self._count_line_response(api, world["review"]["id"], world["cheddar"]["id"]),
            201,
        )
        per_portion = self._per_portion_micro_figure()
        assert per_portion == 100_000_000, "round_half_up(400 * 1000000, 4)"
        assert_fields(
            written,
            expected_base_units=floor_div(100 * per_portion, 1_000_000),
            ingredient_id=world["cheddar"]["id"],
        )
        assert written["expected_base_units"] == 10_000, "floor(100 * 100.0 grams)"

    def test_the_count_line_defers_its_valuation_to_the_close(
        self, api: ApiClient
    ) -> None:
        """No background job values the line; the figure is simply 0 on arrival.

        PRD 3.8: "`valued_usage_micros` stays 0 until the close run values the line."

        Design: Corner/consistency_model/every_cascade_and_every_derived_field_is_visible_to_the_very_next_read
        """
        world = self._july_world(api)
        written = get_success_data(
            self._count_line_response(api, world["review"]["id"], world["cheddar"]["id"]),
            201,
        )
        assert_count_line(written, valued_usage_micros=0)

        rows = fixtures.count_line_rows(api, world["review"]["id"])
        assert_fields(rows[0], id=written["id"], valued_usage_micros=0)

    def test_the_classify_call_itself_returns_both_thresholds(
        self, api: ApiClient
    ) -> None:
        """A single-line review sets the bar at 7000 bps and the margin at 300 cents.

        PRD 3.8: "On a review with at least one line it computes
        `popularity_threshold_bps` as the popularity factor of 7000 basis points
        divided by the number of mix lines, rounded half up"

        Design: Corner/consistency_model/every_cascade_and_every_derived_field_is_visible_to_the_very_next_read
        """
        world = self._july_world(api)
        self._count_line_response(api, world["review"]["id"], world["cheddar"]["id"])
        classified = fixtures.classify_review(api, world["review"]["id"])
        assert_period_review(
            classified,
            status=ReviewStatus.CLASSIFIED,
            popularity_threshold_bps=round_half_up(7_000, 1),
            margin_threshold_cents=round_half_up(
                100 * (round_half_up(40_000, 100) - self._plate_cost_cents()), 100
            ),
        )
        assert classified["popularity_threshold_bps"] == 7_000, "7000 / 1 line"
        assert classified["margin_threshold_cents"] == 300, "400 - 100, weighted by 100"

    def test_the_item_read_right_after_the_classify_already_shows_the_star(
        self, api: ApiClient
    ) -> None:
        """The classification lands on the menu item, not just on the review.

        PRD 3.8: "Classification writes both thresholds onto the review and all three
        computed fields onto every line, copies each line's `margin_class` onto its
        menu item and increments each of those items' `version`, and increments the
        review's `version`."

        Design: Corner/consistency_model/every_cascade_and_every_derived_field_is_visible_to_the_very_next_read
        """
        world = self._july_world(api)
        self._count_line_response(api, world["review"]["id"], world["cheddar"]["id"])
        fixtures.classify_review(api, world["review"]["id"])

        item = get_success_data(api.get_menu_item(world["menu_item"]["id"], COST_ANALYST))
        assert_menu_item(
            item,
            margin_class=MarginClass.STAR,
            plate_cost_cents=self._plate_cost_cents(),
            plate_cost_state=CostState.FRESH,
            status=MenuItemStatus.ACTIVE,
        )
        assert item["plate_cost_cents"] == 100, "the July plate cost in cents"

    def test_the_second_feeds_line_waits_in_pending_until_publication(
        self, api: ApiClient
    ) -> None:
        """A loaded line changes nothing about anyone's cost until the feed publishes.

        PRD 3.2: "A new line's `status` is `PENDING`. Loading a line increments the
        feed's `line_count` and its `version`."

        Design: Corner/consistency_model/every_cascade_and_every_derived_field_is_visible_to_the_very_next_read
        """
        world = self._july_world(api)
        feed, line = self._second_feed(api, world["cheddar"]["id"])
        assert_fields(
            line,
            status=IngredientPriceStatus.PENDING,
            pack_cost_micros=SECOND_FEED_PACK_COST_MICROS,
            effective_from=SECOND_FEED_DATE,
        )

        held = get_success_data(api.get_price_feed(feed["id"], COST_ANALYST))
        assert_price_feed(held, status=PriceFeedStatus.DRAFT, line_count=1)

        recipe = get_success_data(api.get_recipe(world["recipe"]["id"], COST_ANALYST))
        assert_recipe(recipe, cost_state=CostState.FRESH, batch_cost_micros=3_880_071)

    def _through_the_publication(self, api: ApiClient):
        """Count, classify, then publish the mid-July re-price — nothing else."""
        world = self._july_world(api)
        world["count_line"] = get_success_data(
            self._count_line_response(api, world["review"]["id"], world["cheddar"]["id"]),
            201,
        )
        world["review"] = fixtures.classify_review(api, world["review"]["id"])
        feed, line = self._second_feed(api, world["cheddar"]["id"])
        world["feed2"] = feed
        world["line2"] = line
        world["published"] = fixtures.publish_price_feed(api, feed["id"])
        return world

    def test_the_publish_response_carries_the_whole_first_hop(
        self, api: ApiClient
    ) -> None:
        """Status, clock stamp and supersession count all arrive in that one body.

        PRD 3.2: "The **first hop** flips the feed's `status` to `PUBLISHED`, stamps
        `published_at` from the logical clock, and moves every one of the feed's lines
        from `PENDING` to `PUBLISHED`."

        Design: Corner/consistency_model/every_cascade_and_every_derived_field_is_visible_to_the_very_next_read
        """
        world = self._through_the_publication(api)
        published = world["published"]
        assert_price_feed(
            published,
            status=PriceFeedStatus.PUBLISHED,
            line_count=1,
            superseded_price_count=1,
            affected_recipe_count=1,
            affected_menu_item_count=1,
        )
        assert_instant_equals(published["published_at"], CLOCK_EPOCH, "published_at")

    def test_the_very_next_recipe_read_is_stale_with_its_last_rollup_intact(
        self, api: ApiClient
    ) -> None:
        """Invalidation is immediate; recomputation stays explicit.

        PRD 3.2: "Every recipe that holds an active ingredient component pointing at
        that ingredient, and whose `cost_state` is currently `FRESH`, flips to `STALE`.
        Its cost figures are untouched and still show what the last roll-up wrote."

        Design: Corner/consistency_model/every_cascade_and_every_derived_field_is_visible_to_the_very_next_read
        """
        world = self._through_the_publication(api)
        recipe = get_success_data(api.get_recipe(world["recipe"]["id"], COST_ANALYST))
        assert_recipe(
            recipe,
            cost_state=CostState.STALE,
            batch_cost_micros=round_half_up(400 * 22_000_000, 2_268),
            status=RecipeStatus.ACTIVE,
        )
        assert recipe["batch_cost_micros"] == 3_880_071, "still the July roll-up"

    def test_the_very_next_item_read_has_already_lost_its_margin_class(
        self, api: ApiClient
    ) -> None:
        """The fifth hop is done before the publish call returns.

        PRD 3.2: "The **fifth hop** exists because those menu items' plate costs went
        stale: each of them has its `margin_class` reset to `UNCLASSIFIED`. Every
        entity touched in any of the five hops has its `version` incremented."

        Design: Corner/consistency_model/every_cascade_and_every_derived_field_is_visible_to_the_very_next_read
        """
        world = self._through_the_publication(api)
        item = get_success_data(api.get_menu_item(world["menu_item"]["id"], COST_ANALYST))
        assert_menu_item(
            item,
            margin_class=MarginClass.UNCLASSIFIED,
            plate_cost_state=CostState.STALE,
            plate_cost_cents=self._plate_cost_cents(),
            status=MenuItemStatus.ACTIVE,
        )
        assert item["plate_cost_cents"] == 100, "the stale figure is kept, not cleared"

    def test_a_price_move_leaves_the_count_sheet_current(self, api: ApiClient) -> None:
        """Count sheets go out of date on a specification change, not on a re-price.

        PRD 3.6: "Hop 2 also enqueues the propagation work: it flips the recipe's prep
        guide `sync_state` to `OUT_OF_DATE`, and it flips `sync_state` to
        `OUT_OF_DATE` on every count sheet line that belongs to a period review whose
        `status` is not `CLOSED` and whose `ingredient_id` is consumed by an active
        component of this recipe."

        Design: Corner/consistency_model/every_cascade_and_every_derived_field_is_visible_to_the_very_next_read
        """
        world = self._through_the_publication(api)
        rows, meta = validate_paginated(
            api.list_count_lines(world["review"]["id"], {"limit": 10, "offset": 0}, COST_ANALYST)
        )
        assert_page_meta(meta, total_count=1, limit=10, offset=0, has_more=False)
        assert_count_line(
            rows[0],
            id=world["count_line"]["id"],
            sync_state=SyncState.CURRENT,
            expected_base_units=floor_div(100 * self._per_portion_micro_figure(), 1_000_000),
            used_base_units=10_200,
        )
        assert rows[0]["expected_base_units"] == 10_000, "the specification did not move"

    def test_the_mix_line_keeps_its_class_and_its_frozen_snapshot(
        self, api: ApiClient
    ) -> None:
        """Immediately visible never means retroactively rewritten.

        PRD 3.8: "The line freezes `plate_cost_cents_snapshot` from the item's
        `plate_cost_cents` at the moment of loading, and every later classification
        and close values that line with the snapshot rather than with the item's live
        plate cost."

        Design: Corner/consistency_model/every_cascade_and_every_derived_field_is_visible_to_the_very_next_read
        """
        world = self._through_the_publication(api)
        rows, meta = validate_paginated(
            api.list_mix_lines(world["review"]["id"], {"limit": 10, "offset": 0}, COST_ANALYST)
        )
        assert_page_meta(meta, total_count=1, limit=10, offset=0, has_more=False)
        assert_mix_line(
            rows[0],
            id=world["mix_line"]["id"],
            margin_class=MarginClass.STAR,
            plate_cost_cents_snapshot=self._plate_cost_cents(),
            units_sold=100,
            gross_sales_cents=40_000,
        )
        assert rows[0]["plate_cost_cents_snapshot"] == 100, "frozen at load time"

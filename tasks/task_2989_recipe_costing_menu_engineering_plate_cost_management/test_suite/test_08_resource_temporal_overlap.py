"""Half-open intervals competing for the same resource.

One scenario puts four price windows on a single ingredient-and-region axis to
separate adjacency, truncation and collision; the other puts four promotion
windows in a single region to pin what a concurrency ceiling counts.  Adjacency
is the shared hinge: a start equal to a neighbour's end is never an overlap.
"""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    CULINARY_DIRECTOR,
    COST_ANALYST,
    IngredientPriceStatus,
    LtoStatus,
    PriceFeedStatus,
    RegionCode,
    assert_fields,
    assert_ingredient_price,
    assert_lto_campaign,
    assert_menu_item,
    assert_ordered_by,
    assert_price_feed,
    fixtures,
    get_success_data,
    ids_of,
    validate_error,
    validate_paginated,
)


class TestPriceWindowAdjacencyTruncationAndCollision:
    """Four MW cheddar windows, published in window order."""

    @staticmethod
    def _four_staged_windows(api: ApiClient):
        """All four lines loaded while every feed is still DRAFT."""
        cheddar = fixtures.create_cheddar(api)
        feed_a = fixtures.stage_price_feed(
            api,
            cheddar["id"],
            22_000_000,
            effective_from="2026-05-01T00:00:00.000Z",
            effective_to="2026-06-01T00:00:00.000Z",
        )
        feed_b = fixtures.stage_price_feed(
            api, cheddar["id"], 23_000_000, effective_from="2026-06-01T00:00:00.000Z"
        )
        feed_c = fixtures.stage_price_feed(
            api, cheddar["id"], 25_000_000, effective_from="2026-07-01T00:00:00.000Z"
        )
        feed_d = fixtures.stage_price_feed(
            api, cheddar["id"], 24_000_000, effective_from="2026-06-15T00:00:00.000Z"
        )
        return {
            "cheddar": cheddar,
            "feed_a": feed_a,
            "feed_b": feed_b,
            "feed_c": feed_c,
            "feed_d": feed_d,
        }

    @staticmethod
    def _price_rows(api: ApiClient, cheddar_id: str):
        rows, meta = validate_paginated(api.list_ingredient_prices(cheddar_id))
        return rows, meta

    def test_a_start_equal_to_a_bounded_rows_end_is_adjacency(
        self, api: ApiClient
    ) -> None:
        """2026-06-01 abuts the first window and truncates nothing.

        PRD 3.2: "A new line whose `effective_from` falls exactly on an existing
        bounded row's `effective_to` is *adjacent*, not overlapping, and is
        accepted."

        Design: Difficulty/resource_temporal_overlap/ingredient_price_windows_are_half_open_adjacent_accepted_open_ended_truncated_interior_window_collides
        """
        world = self._four_staged_windows(api)

        published_a = fixtures.publish_price_feed(api, world["feed_a"]["id"])
        published_b = fixtures.publish_price_feed(api, world["feed_b"]["id"])

        assert_price_feed(
            published_a, status=PriceFeedStatus.PUBLISHED, superseded_price_count=0
        )
        assert_price_feed(
            published_b, status=PriceFeedStatus.PUBLISHED, superseded_price_count=0
        )

    def test_a_later_start_truncates_the_open_ended_incumbent(
        self, api: ApiClient
    ) -> None:
        """The 2026-06-01 row is closed at 2026-07-01 and marked SUPERSEDED.

        PRD 3.2: "its `effective_to` becomes the new line's `effective_from` and
        its `status` becomes `SUPERSEDED`."

        Design: Difficulty/resource_temporal_overlap/ingredient_price_windows_are_half_open_adjacent_accepted_open_ended_truncated_interior_window_collides
        """
        world = self._four_staged_windows(api)
        fixtures.publish_price_feed(api, world["feed_a"]["id"])
        fixtures.publish_price_feed(api, world["feed_b"]["id"])

        published_c = fixtures.publish_price_feed(api, world["feed_c"]["id"])

        assert_price_feed(
            published_c, status=PriceFeedStatus.PUBLISHED, superseded_price_count=1
        )
        rows, _ = self._price_rows(api, world["cheddar"]["id"])
        assert_ingredient_price(
            rows[1],
            pack_cost_micros=23_000_000,
            effective_from="2026-06-01T00:00:00.000Z",
            effective_to="2026-07-01T00:00:00.000Z",
            status=IngredientPriceStatus.SUPERSEDED,
        )
        assert_ingredient_price(
            rows[0],
            pack_cost_micros=22_000_000,
            effective_to="2026-06-01T00:00:00.000Z",
            status=IngredientPriceStatus.PUBLISHED,
        )

    def test_a_start_before_a_published_start_is_a_collision(
        self, api: ApiClient
    ) -> None:
        """2026-06-15 sits before the live 2026-07-01 row and is refused.

        PRD 3.2: "A new line whose `effective_from` is at or before an existing
        row's `effective_from`, or falls strictly inside a bounded existing
        window, is a genuine collision and the publication is refused with
        `ERR_PRICE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/ingredient_price_windows_are_half_open_adjacent_accepted_open_ended_truncated_interior_window_collides
        """
        world = self._four_staged_windows(api)
        for key in ("feed_a", "feed_b", "feed_c"):
            fixtures.publish_price_feed(api, world[key]["id"])

        response = api.publish_price_feed(world["feed_d"]["id"], COST_ANALYST)

        validate_error(response, ApiErrorId.PRICE_WINDOW_OVERLAP)

    def test_the_price_history_records_all_four_windows_in_time_order(
        self, api: ApiClient
    ) -> None:
        """Three settled rows plus the pending one that never published.

        PRD 3.2: "The full set of price rows quoted for one ingredient — across
        every feed and every region — is readable as a list ordered by
        `effective_from` ascending and then `created_at` ascending"

        Design: Difficulty/resource_temporal_overlap/ingredient_price_windows_are_half_open_adjacent_accepted_open_ended_truncated_interior_window_collides
        """
        world = self._four_staged_windows(api)
        for key in ("feed_a", "feed_b", "feed_c"):
            fixtures.publish_price_feed(api, world[key]["id"])
        api.publish_price_feed(world["feed_d"]["id"], COST_ANALYST)

        rows, meta = self._price_rows(api, world["cheddar"]["id"])

        assert meta["total_count"] == 4
        assert_ordered_by(rows, "effective_from")
        assert [row["pack_cost_micros"] for row in rows] == [
            22_000_000,
            23_000_000,
            24_000_000,
            25_000_000,
        ]
        assert [row["status"] for row in rows] == [
            IngredientPriceStatus.PUBLISHED,
            IngredientPriceStatus.SUPERSEDED,
            IngredientPriceStatus.PENDING,
            IngredientPriceStatus.PUBLISHED,
        ]
        assert_ingredient_price(
            rows[2],
            effective_from="2026-06-15T00:00:00.000Z",
            effective_to=None,
        )
        assert_ingredient_price(
            rows[3],
            effective_from="2026-07-01T00:00:00.000Z",
            effective_to=None,
        )

    def test_the_collided_feed_is_left_unpublished(self, api: ApiClient) -> None:
        """Its own line never leaves PENDING and the feed never leaves DRAFT.

        PRD 3.2: "A new feed opens with `status` `DRAFT`, `line_count` 0,
        `published_at` null"

        Design: Difficulty/resource_temporal_overlap/ingredient_price_windows_are_half_open_adjacent_accepted_open_ended_truncated_interior_window_collides
        """
        world = self._four_staged_windows(api)
        for key in ("feed_a", "feed_b", "feed_c"):
            fixtures.publish_price_feed(api, world[key]["id"])

        api.publish_price_feed(world["feed_d"]["id"], COST_ANALYST)

        assert_price_feed(
            get_success_data(api.get_price_feed(world["feed_d"]["id"])),
            status=PriceFeedStatus.DRAFT,
            published_at=None,
            line_count=1,
        )
        lines, _ = validate_paginated(
            api.list_price_feed_lines(world["feed_d"]["id"])
        )
        assert_fields(lines[0], status=IngredientPriceStatus.PENDING)


class TestPromotionLaunchCapacityCountsOverlappingLaunches:
    """Four MW windows against a ceiling of two concurrent launches."""

    @staticmethod
    def _four_costed_campaigns(api: ApiClient):
        """C1..C4 all COSTED, with the clock still ahead of every window."""
        world = fixtures.grill_world_active_item(api)
        windows = (
            ("2026-08-10T00:00:00.000Z", "2026-08-20T00:00:00.000Z"),
            ("2026-08-12T00:00:00.000Z", "2026-08-22T00:00:00.000Z"),
            ("2026-08-15T00:00:00.000Z", "2026-08-25T00:00:00.000Z"),
            ("2026-08-22T00:00:00.000Z", "2026-08-30T00:00:00.000Z"),
        )
        planned = [
            fixtures.plan_lto(
                api,
                world["menu_item"]["id"],
                window_start=start,
                window_end=end,
                promo_price_cents=380,
                forecast_units=500,
            )
            for start, end in windows
        ]
        costed = [fixtures.cost_lto(api, campaign["id"]) for campaign in planned]
        world.update({"planned": planned, "costed": costed})
        return world

    def test_every_campaign_inherits_the_items_region(self, api: ApiClient) -> None:
        """All four occupy MW capacity because MW is where the item sells.

        PRD 3.9: "The campaign copies its `region_code` from the menu item, so it
        occupies that region's concurrent-promotion capacity, and it increments
        the item's `open_lto_count` and `version`."

        Design: Difficulty/resource_temporal_overlap/lto_launch_capacity_counts_only_overlapping_launched_windows_in_the_region
        """
        world = self._four_costed_campaigns(api)

        for campaign in world["planned"]:
            assert_lto_campaign(
                campaign, region_code=RegionCode.MW, status=LtoStatus.PLANNED
            )
        assert_menu_item(
            get_success_data(api.get_menu_item(world["menu_item"]["id"])),
            open_lto_count=4,
            is_lto=False,
        )

    def test_the_first_two_overlapping_windows_launch(self, api: ApiClient) -> None:
        """Zero, then exactly one, LAUNCHED neighbour intersects.

        PRD 3.9: "the number of campaigns already in `LAUNCHED` that share this
        campaign's `region_code` and whose window intersects this campaign's
        window must be fewer than two, otherwise `ERR_LTO_WINDOW_CAPACITY`."

        Design: Difficulty/resource_temporal_overlap/lto_launch_capacity_counts_only_overlapping_launched_windows_in_the_region
        """
        world = self._four_costed_campaigns(api)

        first = fixtures.launch_lto(api, world["planned"][0]["id"])
        second = fixtures.launch_lto(api, world["planned"][1]["id"])

        assert_lto_campaign(first, status=LtoStatus.LAUNCHED)
        assert_lto_campaign(second, status=LtoStatus.LAUNCHED)

    def test_the_third_overlapping_window_exhausts_the_ceiling(
        self, api: ApiClient
    ) -> None:
        """Two intersecting launches make the strict comparison fail.

        PRD 2.10: "Launching would not exceed the per-region ceiling on
        overlapping launched campaigns — `ERR_LTO_WINDOW_CAPACITY`, 409."

        Design: Difficulty/resource_temporal_overlap/lto_launch_capacity_counts_only_overlapping_launched_windows_in_the_region
        """
        world = self._four_costed_campaigns(api)
        fixtures.launch_lto(api, world["planned"][0]["id"])
        fixtures.launch_lto(api, world["planned"][1]["id"])

        response = api.launch_lto_campaign(
            world["planned"][2]["id"], CULINARY_DIRECTOR
        )

        validate_error(response, ApiErrorId.LTO_WINDOW_CAPACITY)

    def test_the_refused_launch_leaves_the_campaign_costed_and_intact(
        self, api: ApiClient
    ) -> None:
        """It keeps its 100-cent snapshot and is not itself counted later.

        PRD 3.9: "campaigns in other regions or in other statuses are never
        counted"

        Design: Difficulty/resource_temporal_overlap/lto_launch_capacity_counts_only_overlapping_launched_windows_in_the_region
        """
        world = self._four_costed_campaigns(api)
        fixtures.launch_lto(api, world["planned"][0]["id"])
        fixtures.launch_lto(api, world["planned"][1]["id"])

        api.launch_lto_campaign(world["planned"][2]["id"], CULINARY_DIRECTOR)

        assert_lto_campaign(
            get_success_data(api.get_lto_campaign(world["planned"][2]["id"])),
            status=LtoStatus.COSTED,
            promo_plate_cost_cents=100,
        )

    def test_an_adjacent_window_launches_freely(self, api: ApiClient) -> None:
        """A start equal to a launched window's end intersects nothing.

        PRD 3.9: "Intersection is judged on the half-open windows, so a campaign
        starting exactly when another ends does not intersect it and does not
        consume capacity"

        Design: Difficulty/resource_temporal_overlap/lto_launch_capacity_counts_only_overlapping_launched_windows_in_the_region
        """
        world = self._four_costed_campaigns(api)
        fixtures.launch_lto(api, world["planned"][0]["id"])
        fixtures.launch_lto(api, world["planned"][1]["id"])
        api.launch_lto_campaign(world["planned"][2]["id"], CULINARY_DIRECTOR)

        fourth = fixtures.launch_lto(api, world["planned"][3]["id"])

        assert_lto_campaign(fourth, status=LtoStatus.LAUNCHED)

    def test_the_launched_set_is_exactly_the_three_that_succeeded(
        self, api: ApiClient
    ) -> None:
        """C1, C2 and C4 in window order, and the item flagged as promoting.

        PRD 3.9: "Campaigns are listed ordered `window_start` ascending then
        `created_at` ascending, filterable by `menu_item_id`, `region_code` and
        `status`."

        Design: Difficulty/resource_temporal_overlap/lto_launch_capacity_counts_only_overlapping_launched_windows_in_the_region
        """
        world = self._four_costed_campaigns(api)
        fixtures.launch_lto(api, world["planned"][0]["id"])
        fixtures.launch_lto(api, world["planned"][1]["id"])
        api.launch_lto_campaign(world["planned"][2]["id"], CULINARY_DIRECTOR)
        fixtures.launch_lto(api, world["planned"][3]["id"])

        rows, meta = validate_paginated(
            api.list_lto_campaigns({"status": LtoStatus.LAUNCHED})
        )

        assert meta["total_count"] == 3
        assert_ordered_by(rows, "window_start")
        assert ids_of(rows) == [
            world["planned"][0]["id"],
            world["planned"][1]["id"],
            world["planned"][3]["id"],
        ]
        assert_menu_item(
            get_success_data(api.get_menu_item(world["menu_item"]["id"])),
            open_lto_count=4,
            is_lto=True,
        )

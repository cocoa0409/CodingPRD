"""Requests that violate two rules at once, resolved by the global order.

Each scenario is built so that both violations are demonstrably live: clearing
the winner's cause makes the loser's error appear, and reproducing only the
loser's cause on a second row reports it directly.  The two pairs are mirror
images on HTTP status — the first winner carries the lower code, the second the
higher — so a status code can never stand in for a priority.
"""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    BaseUom,
    COST_ANALYST,
    CostState,
    IngredientPriceStatus,
    IngredientStatus,
    MenuItemStatus,
    PriceFeedStatus,
    ProposalStatus,
    RECIPE_DEVELOPER,
    assert_fields,
    assert_ingredient,
    assert_ingredient_price,
    assert_menu_item,
    assert_price_feed,
    assert_projections_unset,
    assert_proposal,
    assert_recipe,
    fixtures,
    get_success_data,
    round_half_up,
    validate_error,
    validate_paginated,
)


class TestCostStaleOutranksMarketCap:
    """Position 26 beats position 47 on one submission."""

    @staticmethod
    def _stale_item_with_an_over_cap_proposal(api: ApiClient):
        """A 600-cent proposal against an item whose plate cost just went stale."""
        world = fixtures.grill_world_active_item(api)
        proposal = fixtures.open_proposal(
            api, world["menu_item"]["id"], proposed_price_cents=600
        )
        second_feed = fixtures.publish_price(
            api,
            world["cheddar"]["id"],
            25_000_000,
            effective_from="2026-07-15T00:00:00.000Z",
        )
        world.update({"proposal": proposal, "second_feed": second_feed})
        return world

    def test_the_publication_is_what_makes_the_plate_cost_stale(
        self, api: ApiClient
    ) -> None:
        """One menu item is invalidated and keeps its 100-cent figure.

        PRD 3.2: "Every menu item whose backing recipe is one of them, and whose
        `plate_cost_state` is currently `FRESH`, flips to `STALE`; the feed's
        `affected_menu_item_count` records how many."

        Design: Difficulty/priority_pair_validation_conflict/proposal_submit_reports_cost_stale_state_error_before_market_cap_fiscal_error
        """
        world = self._stale_item_with_an_over_cap_proposal(api)

        assert_price_feed(world["second_feed"], affected_menu_item_count=1)
        assert_menu_item(
            get_success_data(api.get_menu_item(world["menu_item"]["id"])),
            plate_cost_state=CostState.STALE,
            plate_cost_cents=100,
        )

    def test_the_state_error_is_reported_even_though_the_cap_is_breached(
        self, api: ApiClient
    ) -> None:
        """The 409 wins over a 422 that is equally live.

        PRD 2.10: "The cost figures the operation consumes are not stale —
        `ERR_COST_STALE`, 409 — on recipe roll-up, recipe review submission,
        recipe activation, plate-cost recomputation, menu-item activation,
        proposal submission, proposal approval and promotion costing."

        Design: Difficulty/priority_pair_validation_conflict/proposal_submit_reports_cost_stale_state_error_before_market_cap_fiscal_error
        """
        world = self._stale_item_with_an_over_cap_proposal(api)

        response = api.submit_proposal(world["proposal"]["id"], RECIPE_DEVELOPER)

        validate_error(response, ApiErrorId.COST_STALE)

    def test_refreshing_the_cost_exposes_the_fiscal_error_underneath(
        self, api: ApiClient
    ) -> None:
        """The identical request now reports the cap breach.

        PRD 2.10: "The proposed price is within the effective cap price —
        `ERR_MARKET_CAP_EXCEEDED`, 422, on proposal submission."

        Design: Difficulty/priority_pair_validation_conflict/proposal_submit_reports_cost_stale_state_error_before_market_cap_fiscal_error
        """
        world = self._stale_item_with_an_over_cap_proposal(api)
        api.submit_proposal(world["proposal"]["id"], RECIPE_DEVELOPER)

        rolled = fixtures.rollup(api, world["recipe"]["id"])
        recosted = fixtures.plate_cost(api, world["menu_item"]["id"])
        response = api.submit_proposal(world["proposal"]["id"], RECIPE_DEVELOPER)

        assert_recipe(
            rolled,
            cost_state=CostState.FRESH,
            batch_cost_micros=round_half_up(400 * 25_000_000, 2268),
            portion_cost_micros=round_half_up(4_409_171, 4),
        )
        assert_fields(
            rolled, batch_cost_micros=4_409_171, portion_cost_micros=1_102_293
        )
        assert_menu_item(
            recosted,
            plate_cost_state=CostState.FRESH,
            plate_cost_micros=1_141_204,
            plate_cost_cents=114,
            food_cost_bps=2850,
        )
        validate_error(response, ApiErrorId.MARKET_CAP_EXCEEDED)

    def test_neither_failure_writes_a_projection_or_moves_the_price(
        self, api: ApiClient
    ) -> None:
        """The proposal is still DRAFT with every projection field unset.

        PRD 2.10: "the **first** rule that fails determines the response; no
        later rule is evaluated and no partial mutation is persisted"

        Design: Difficulty/priority_pair_validation_conflict/proposal_submit_reports_cost_stale_state_error_before_market_cap_fiscal_error
        """
        world = self._stale_item_with_an_over_cap_proposal(api)
        api.submit_proposal(world["proposal"]["id"], RECIPE_DEVELOPER)
        fixtures.rollup(api, world["recipe"]["id"])
        fixtures.plate_cost(api, world["menu_item"]["id"])

        api.submit_proposal(world["proposal"]["id"], RECIPE_DEVELOPER)

        after = get_success_data(api.get_proposal(world["proposal"]["id"]))
        assert_proposal(after, status=ProposalStatus.DRAFT, revision_round=0)
        assert_projections_unset(after)
        assert_menu_item(
            get_success_data(api.get_menu_item(world["menu_item"]["id"])),
            current_price_cents=400,
            status=MenuItemStatus.ACTIVE,
        )


class TestIngredientRetiredOutranksWindowOverlap:
    """Position 31 beats position 45, across two feeds."""

    @staticmethod
    def _two_feeds_with_the_same_collision(api: ApiClient):
        """One retired ingredient and one active one, each with a colliding line."""
        sauce = fixtures.create_ingredient(
            api,
            sku="TOMATO-SAUCE",
            name="Tomato Sauce",
            pack_base_units=3785,
            cook_shrink_bps=500,
            kcal_per_base_unit_micros=300_000,
            sodium_mcg_per_base_unit=4100,
        )
        oil = fixtures.create_peanut_oil(api, base_uom=BaseUom.GRAM)
        feed = fixtures.open_price_feed(api, feed_date="2026-07-01T00:00:00.000Z")
        fixtures.add_price_line(
            api,
            feed["id"],
            sauce["id"],
            pack_cost_micros=9_500_000,
            effective_from="2026-07-01T00:00:00.000Z",
        )
        fixtures.add_price_line(
            api,
            feed["id"],
            oil["id"],
            pack_cost_micros=12_000_000,
            effective_from="2026-07-01T00:00:00.000Z",
        )
        published = fixtures.publish_price_feed(api, feed["id"])
        retired = fixtures.retire_ingredient(api, sauce["id"])
        retired_feed = fixtures.stage_price_feed(
            api,
            sauce["id"],
            9_000_000,
            effective_from="2026-06-01T00:00:00.000Z",
        )
        active_feed = fixtures.stage_price_feed(
            api,
            oil["id"],
            11_000_000,
            effective_from="2026-06-01T00:00:00.000Z",
        )
        return {
            "sauce": sauce,
            "oil": oil,
            "published": published,
            "retired": retired,
            "retired_feed": retired_feed,
            "active_feed": active_feed,
        }

    def test_the_first_feed_publishes_two_open_ended_windows_cleanly(
        self, api: ApiClient
    ) -> None:
        """Nothing was in force before it, so nothing is superseded.

        PRD 3.2: "The feed's `superseded_price_count` records how many rows were
        superseded this way."

        Design: Difficulty/priority_pair_validation_conflict/feed_publish_reports_ingredient_retired_referential_error_before_window_overlap_temporal_error
        """
        world = self._two_feeds_with_the_same_collision(api)

        assert_price_feed(
            world["published"],
            status=PriceFeedStatus.PUBLISHED,
            superseded_price_count=0,
            line_count=2,
        )
        assert_ingredient(world["retired"], status=IngredientStatus.RETIRED)

    def test_the_referential_error_outranks_the_equally_live_temporal_error(
        self, api: ApiClient
    ) -> None:
        """A retired ingredient reports 422 ahead of a 409 window collision.

        PRD 2.10: "No ingredient the operation depends on is `RETIRED` —
        `ERR_INGREDIENT_RETIRED`, 422 — on ingredient retirement (so a second
        retirement is refused rather than silently repeated), component creation,
        recipe activation, specification-change-order approval of an ingredient
        addition, and feed publication."

        Design: Difficulty/priority_pair_validation_conflict/feed_publish_reports_ingredient_retired_referential_error_before_window_overlap_temporal_error
        """
        world = self._two_feeds_with_the_same_collision(api)

        response = api.publish_price_feed(
            world["retired_feed"]["id"], COST_ANALYST
        )

        validate_error(response, ApiErrorId.INGREDIENT_RETIRED)

    def test_the_same_collision_on_an_active_ingredient_isolates_the_temporal_rule(
        self, api: ApiClient
    ) -> None:
        """An earlier start against an open-ended row is a genuine collision.

        PRD 3.2: "A new line whose `effective_from` is at or before an existing
        row's `effective_from`, or falls strictly inside a bounded existing
        window, is a genuine collision and the publication is refused with
        `ERR_PRICE_WINDOW_OVERLAP`."

        Design: Difficulty/priority_pair_validation_conflict/feed_publish_reports_ingredient_retired_referential_error_before_window_overlap_temporal_error
        """
        world = self._two_feeds_with_the_same_collision(api)

        response = api.publish_price_feed(world["active_feed"]["id"], COST_ANALYST)

        validate_error(response, ApiErrorId.PRICE_WINDOW_OVERLAP)

    def test_a_refused_publication_advances_neither_feed_nor_line(
        self, api: ApiClient
    ) -> None:
        """Both feeds stay DRAFT, both new lines stay PENDING, no row is truncated.

        PRD 3.2: "Nothing a draft feed contains has any effect on any cost."

        Design: Difficulty/priority_pair_validation_conflict/feed_publish_reports_ingredient_retired_referential_error_before_window_overlap_temporal_error
        """
        world = self._two_feeds_with_the_same_collision(api)

        api.publish_price_feed(world["retired_feed"]["id"], COST_ANALYST)
        api.publish_price_feed(world["active_feed"]["id"], COST_ANALYST)

        for feed_id in (world["retired_feed"]["id"], world["active_feed"]["id"]):
            assert_price_feed(
                get_success_data(api.get_price_feed(feed_id)),
                status=PriceFeedStatus.DRAFT,
                published_at=None,
            )
            lines, _ = validate_paginated(api.list_price_feed_lines(feed_id))
            assert_fields(lines[0], status=IngredientPriceStatus.PENDING)
        for ingredient_id in (world["sauce"]["id"], world["oil"]["id"]):
            rows, _ = validate_paginated(
                api.list_ingredient_prices(
                    ingredient_id, {"status": IngredientPriceStatus.PUBLISHED}
                )
            )
            assert_ingredient_price(
                rows[0],
                effective_from="2026-07-01T00:00:00.000Z",
                effective_to=None,
                status=IngredientPriceStatus.PUBLISHED,
            )

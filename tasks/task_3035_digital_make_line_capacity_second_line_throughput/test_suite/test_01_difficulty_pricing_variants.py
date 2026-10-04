"""Dual-variant pricing: marketplace markup-plus-commission vs first-party flat."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import (
    assert_cents,
    factories as f,
    fixtures,
    make_marketplace_channel_headers,
)


def _world_with_channel(api, **store_overrides):
    """A stocked store with a BOWL (chicken 120g @ 2.1c, rice 180g @ 0.8c) and an
    active DASH channel at markup 0.18 / commission 0.22."""
    fixtures.set_clock(api, fixtures.MORNING)
    world = fixtures.store_with_bowl(api, store_overrides=store_overrides or None)
    rice = fixtures.create_ingredient(
        api,
        ingredient_code="RICE",
        display_name="White Rice",
        unit_cost_cents_per_gram=0.8,
        par_level_grams=5000,
        hold_time_minutes=90,
        batch_size_grams=4000,
    )
    fixtures.cook_batch(api, rice["id"], world["store_id"], grams_cooked=10000)
    fixtures.add_recipe_component(api, world["item_id"], rice["id"], standard_grams=180)
    channel = fixtures.create_marketplace_channel(
        api, channel_code="DASH", markup_pct=0.18, commission_pct=0.22, active=True
    )
    world["rice_id"] = rice["id"]
    world["channel"] = channel
    world["channel_id"] = channel["id"]
    return world


def _two_line_basket(item_id):
    return [
        f.order_line_payload(item_id, quantity=2),
        f.order_line_payload(item_id, quantity=1),
    ]


class TestMarketplaceVsFirstPartyNetRevenueDiverges:
    """Two tests for the marketplace-vs-first-party pricing divergence."""

    def test_same_basket_marketplace_carries_markup_and_commission(self, api):
        """The marketplace variant marks each line's gross up and withholds a per-line commission.

        PRD §3.2: "For a marketplace order, each order line's gross unit price is the item's `base_price_cents` multiplied by one plus the channel's `markup_pct`, rounded half-up to a whole cent and then multiplied by the line's quantity; the line's commission is the line gross multiplied by the channel's `commission_pct`, again rounded half-up to a whole cent *per line before any summing*."
        PRD §3.2: "The order's `subtotal_cents` is the sum of the per-line grosses, its `commission_cents` the sum of the per-line commissions, and its `net_revenue_cents` the subtotal minus the commission."
        Design: Difficulty/dual_variant_calc/marketplace_vs_first_party_net_revenue_diverges
        """
        world = _world_with_channel(api)
        order = get_success_data(
            api.create_order(
                world["store_id"],
                f.order_payload(
                    "MARKETPLACE",
                    _two_line_basket(world["item_id"]),
                    marketplace_channel_id=world["channel_id"],
                    external_order_ref="DASH-1001",
                ),
                make_marketplace_channel_headers(world["channel_id"]),
            )
        )
        # 1095 * 1.18 = 1292.1 -> 1292 per unit; lines 2x1292=2584, 1x1292=1292.
        # Per-line commission: round_half_up(2584*0.22)=round_half_up(568.48)=568;
        # round_half_up(1292*0.22)=round_half_up(284.24)=284.
        assert_cents(order["subtotal_cents"], 3876, "subtotal_cents")
        assert_cents(order["commission_cents"], 852, "commission_cents")
        assert_cents(order["net_revenue_cents"], 3024, "net_revenue_cents")

    def test_same_basket_first_party_digital_pays_no_commission(self, api):
        """The first-party variant skips markup and commission, so the same basket nets differently.

        PRD §3.2: "For first-party digital and in-store orders there is no markup and no commission: the line's `unit_price_cents` is simply `base_price_cents`, `commission_cents` is zero, and `net_revenue_cents` equals `subtotal_cents` — so the same basket yields a different net revenue under the two variants."
        Design: Difficulty/dual_variant_calc/marketplace_vs_first_party_net_revenue_diverges
        """
        world = _world_with_channel(api)
        marketplace = get_success_data(
            api.create_order(
                world["store_id"],
                f.order_payload(
                    "MARKETPLACE",
                    _two_line_basket(world["item_id"]),
                    marketplace_channel_id=world["channel_id"],
                    external_order_ref="DASH-1002",
                ),
                make_marketplace_channel_headers(world["channel_id"]),
            )
        )
        first_party = get_success_data(
            api.create_order(
                world["store_id"],
                f.order_payload("FIRST_PARTY_DIGITAL", _two_line_basket(world["item_id"])),
                fixtures.STORE_MANAGER_HEADERS,
            )
        )
        assert_cents(first_party["subtotal_cents"], 3285, "first-party subtotal")
        assert_cents(first_party["commission_cents"], 0, "first-party commission")
        assert_cents(first_party["net_revenue_cents"], 3285, "first-party net")
        assert marketplace["net_revenue_cents"] != first_party["net_revenue_cents"], (
            "the same basket must net differently under the two pricing variants"
        )


class TestProvisionalVsSettledFoodCostVariance:
    """Two tests for the provisional-vs-frozen food-cost variance variant."""

    def _world_with_three_pickups_and_waste(self, api):
        """Store S2 scenario: three in-store bowls picked up, 360g chicken wasted,
        and a rice batch that expires with 600g remaining when the clock moves."""
        fixtures.set_clock(api, fixtures.MORNING)
        world = fixtures.store_with_bowl(api, store_overrides={"store_code": "S2"})
        rice = fixtures.create_ingredient(
            api,
            ingredient_code="RICE",
            display_name="White Rice",
            unit_cost_cents_per_gram=0.8,
            par_level_grams=5000,
            hold_time_minutes=90,
            batch_size_grams=4000,
        )
        # 1140g: three bowls consume 540g, leaving exactly 600g to expire.
        rice_batch = fixtures.cook_batch(
            api, rice["id"], world["store_id"], grams_cooked=1140
        )
        fixtures.add_recipe_component(api, world["item_id"], rice["id"], standard_grams=180)
        world["rice_id"] = rice["id"]
        world["rice_batch_id"] = rice_batch["id"]
        fixtures.locked_deployment(api, world["store_id"], world["store_version"])
        for _ in range(3):
            fixtures.order_picked_up(api, world)
        fixtures.record_waste(
            api, world["store_id"], world["batch_id"], 360, "OVERPRODUCTION"
        )
        return world

    def test_provisional_variance_includes_unsettled_waste(self, api):
        """Before close, the live variance absorbs the waste and the expired batch.

        PRD §3.9: "The store's `food_cost_variance_bps` is the actual minus the theoretical, divided by the theoretical (or by one if the theoretical is zero), scaled by ten thousand, and rounded half-up to a whole basis point."
        PRD §3.9: "Read before close, the variance is provisional — it includes unsettled waste; closing the day freezes the snapshot, and waste recorded afterward posts to the next day."
        Design: Difficulty/dual_variant_calc/provisional_vs_settled_food_cost_variance
        """
        world = self._world_with_three_pickups_and_waste(api)
        # Move past the rice batch's discard_at (09:00 + 90min = 10:30) so its
        # remaining 600g expires; the window's start (10:15) is also passed so it
        # cuts off, then its end (10:30) passes so it settles.
        fixtures.set_clock(api, "2026-09-01T10:31:00Z")
        store = fixtures.read_store(api, world["store_id"])
        # theoretical = 3 * (252 + 144) = 1188
        assert_cents(store["theoretical_food_cost_cents"], 1188, "theoretical")
        # actual = 3 * 396 consumed + 756 waste + 480 expiry = 2424
        assert_cents(store["actual_food_cost_cents"], 2424, "actual")
        # round_half_up(10000 * (2424 - 1188) / 1188) = 10404
        assert store["food_cost_variance_bps"] == 10404, (
            f"provisional variance: expected 10404 bps, got {store['food_cost_variance_bps']}"
        )

    def test_day_close_freezes_the_provisional_snapshot(self, api):
        """The day-close record freezes the live variance at the moment of close.

        PRD §3.9: "A successful close settles any remaining `CUTOFF` windows (moving them to `SETTLED` and reconciling each window's `digital_completed` against `digital_committed`, with shortfalls recorded on the close record), persists a `DayClose` capturing the `business_day` being closed, the `orders_accepted` and `orders_completed` counts for the day, the `digital_net_revenue_cents` across digital and marketplace orders and the `instore_net_revenue_cents` across in-store orders, and a snapshot of `food_cost_variance_bps` at close."
        Design: Difficulty/dual_variant_calc/provisional_vs_settled_food_cost_variance
        """
        world = self._world_with_three_pickups_and_waste(api)
        fixtures.set_clock(api, "2026-09-01T10:31:00Z")
        live = fixtures.read_store(api, world["store_id"])
        assert live["food_cost_variance_bps"] == 10404
        close = fixtures.close_day(api, world["store_id"])
        assert_cents(close["food_cost_variance_bps"], 10404, "frozen variance")
        assert close["orders_completed"] == 3
        assert close["business_day"] == fixtures.BUSINESS_DAY

    def test_post_close_waste_posts_to_next_day_and_leaves_snapshot(self, api):
        """Waste after the close moves the live counter but not the frozen record.

        PRD §3.9: "Read before close, the variance is provisional — it includes unsettled waste; closing the day freezes the snapshot, and waste recorded afterward posts to the next day."
        Design: Difficulty/dual_variant_calc/provisional_vs_settled_food_cost_variance
        """
        world = self._world_with_three_pickups_and_waste(api)
        fixtures.set_clock(api, "2026-09-01T10:31:00Z")
        close = fixtures.close_day(api, world["store_id"])
        assert_cents(close["food_cost_variance_bps"], 10404, "frozen variance")

        # A further 50g of chicken at 2.1c per gram costs 105 cents, posted after close.
        store_before = fixtures.read_store(api, world["store_id"])
        fixtures.record_waste(
            api, world["store_id"], world["batch_id"], 50, "CONTAMINATION"
        )
        store_after = fixtures.read_store(api, world["store_id"])
        assert store_after["actual_food_cost_cents"] == store_before["actual_food_cost_cents"] + 105

        frozen = fixtures.read_day_close(api, close["id"])
        assert_cents(frozen["food_cost_variance_bps"], 10404, "frozen variance after late waste")
        assert store_after["food_cost_variance_bps"] != 10404, (
            "the live variance must move once post-close waste lands"
        )

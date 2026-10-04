"""Combinatorial pricing and the promise-slotting waterfall."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import (
    assert_cents,
    assert_instant,
    factories as f,
    fixtures,
    make_marketplace_channel_headers,
)


def _store_with_channel(api, **store_overrides):
    """A stocked store with BOWL (chicken 120g @ 2.1c) and an active DASH channel."""
    fixtures.set_clock(api, fixtures.MORNING)
    world = fixtures.store_with_bowl(api, store_overrides=store_overrides or None)
    channel = fixtures.create_marketplace_channel(
        api, channel_code="DASH", markup_pct=0.18, commission_pct=0.22, active=True
    )
    world["channel_id"] = channel["id"]
    return world


class TestPerLineCommissionRounding:
    """Per-line round-half-up must be applied before summing."""

    def test_two_line_marketplace_order_commission_is_852_not_853(self, api):
        """Rounding each line's commission half-up before summing beats aggregate rounding.

        PRD §3.2: "the line's commission is the line gross multiplied by the channel's `commission_pct`, again rounded half-up to a whole cent *per line before any summing*. The order's `subtotal_cents` is the sum of the per-line grosses, its `commission_cents` the sum of the per-line commissions, and its `net_revenue_cents` the subtotal minus the commission."
        Design: Difficulty/combinatorial_formula/per_line_commission_rounding_beats_aggregate
        """
        world = _store_with_channel(api, store_code="S3")
        order = get_success_data(
            api.create_order(
                world["store_id"],
                f.order_payload(
                    "MARKETPLACE",
                    [
                        f.order_line_payload(world["item_id"], quantity=2),
                        f.order_line_payload(world["item_id"], quantity=1),
                    ],
                    marketplace_channel_id=world["channel_id"],
                    external_order_ref="DASH-2001",
                ),
                make_marketplace_channel_headers(world["channel_id"]),
            )
        )
        assert_cents(order["subtotal_cents"], 3876, "subtotal_cents")
        assert_cents(order["commission_cents"], 852, "commission_cents")
        assert order["commission_cents"] != 853, (
            "aggregate rounding of the whole subtotal would yield 853; the contract "
            "pins per-line round-half-up which yields 852"
        )
        assert_cents(order["net_revenue_cents"], 3024, "net_revenue_cents")

    def test_single_line_marketplace_order_commission_matches_per_line_rule(self, api):
        """On one line the pinned rule degenerates to a single round-half-up of that line.

        PRD §3.2: "the line's commission is the line gross multiplied by the channel's `commission_pct`, again rounded half-up to a whole cent *per line before any summing*."
        Design: Difficulty/combinatorial_formula/per_line_commission_rounding_beats_aggregate
        """
        world = _store_with_channel(api, store_code="S3")
        order = get_success_data(
            api.create_order(
                world["store_id"],
                f.order_payload(
                    "MARKETPLACE",
                    [f.order_line_payload(world["item_id"], quantity=1)],
                    marketplace_channel_id=world["channel_id"],
                    external_order_ref="DASH-2002",
                ),
                make_marketplace_channel_headers(world["channel_id"]),
            )
        )
        assert_cents(order["subtotal_cents"], 1292, "subtotal_cents")
        assert_cents(order["commission_cents"], 284, "commission_cents")
        assert_cents(order["net_revenue_cents"], 1008, "net_revenue_cents")


class TestPromiseSlottingWaterfall:
    """The waterfall walks windows in start order and skips a full current window."""

    def _two_window_store(self, api):
        """A store with digital capacity 2, threshold 1.0 (collapsed band) and two
        adjacent OPEN windows; W1 is then filled by a 2-entree digital order."""
        fixtures.set_clock(api, fixtures.MORNING)
        world = fixtures.store_with_bowl(
            api,
            with_window=False,
            store_overrides={
                "store_code": "S4",
                "digital_line_capacity_per_interval": 2,
                "overage_threshold_pct": 1.0,
            },
        )
        window1 = fixtures.open_window(
            api, world["store_id"], "2026-09-01T10:15:00Z", "2026-09-01T10:30:00Z"
        )
        window2 = fixtures.open_window(
            api, world["store_id"], "2026-09-01T10:30:00Z", "2026-09-01T10:45:00Z"
        )
        world["window1_id"] = window1["id"]
        world["window2_id"] = window2["id"]
        fill = fixtures.place_order(
            api,
            world["store_id"],
            world["item_id"],
            channel="FIRST_PARTY_DIGITAL",
            quantity=2,
        )
        world["fill_order"] = fill
        return world

    def test_full_current_window_overflows_to_next_open_window(self, api):
        """With the current window at capacity, the next digital order slots into the next open window.

        PRD §3.3: "The server walks the store's windows in ascending `interval_start` order — never by identifier — and considers a window eligible when it is `OPEN`, its `interval_end` is after the order's `placed_at`, and its `digital_committed` plus the order's `entree_count` does not exceed its `digital_capacity`."
        PRD §3.3: "The first eligible window in start order wins, and the order's `promised_at` is stamped as that window's `interval_end`."
        Design: Difficulty/combinatorial_formula/promise_slotting_waterfall_skips_full_window
        """
        world = self._two_window_store(api)
        fill = world["fill_order"]
        assert_instant(fill["promised_at"], "2026-09-01T10:30:00Z", "fill promised_at")
        assert fill["production_window_id"] == world["window1_id"]

        late = fixtures.place_order(
            api,
            world["store_id"],
            world["item_id"],
            channel="FIRST_PARTY_DIGITAL",
            quantity=1,
        )
        assert_instant(late["promised_at"], "2026-09-01T10:45:00Z", "late promised_at")
        assert late["production_window_id"] == world["window2_id"]

    def test_current_window_at_capacity_reads_closed(self, api):
        """A committed load exactly equal to capacity reads CLOSED on the current window.

        PRD §2.9: "When the current window's `digital_committed` is at or above the store's `digital_line_capacity_per_interval`, the state is `CLOSED`."
        PRD §2.9: "The boundary is inclusive on both bands: a committed load exactly equal to the threshold is `THROTTLED`, and a load exactly equal to capacity is `CLOSED`."
        Design: Difficulty/combinatorial_formula/promise_slotting_waterfall_skips_full_window
        """
        world = self._two_window_store(api)
        store = fixtures.read_store(api, world["store_id"])
        assert store["throttle_state"] == "CLOSED", (
            f"with load 2 == capacity 2 the current window must read CLOSED, got "
            f"{store['throttle_state']}"
        )
        # A further order still finds room in the second window rather than failing.
        late = fixtures.place_order(
            api,
            world["store_id"],
            world["item_id"],
            channel="FIRST_PARTY_DIGITAL",
            quantity=1,
        )
        assert late["production_window_id"] == world["window2_id"]

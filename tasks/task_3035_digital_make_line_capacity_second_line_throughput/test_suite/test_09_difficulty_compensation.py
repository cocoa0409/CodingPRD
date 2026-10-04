"""Compensating invariants: cancel restores capacity and grams; day close freezes variance."""

from test_helpers import (
    assert_cents,
    fixtures,
)


class TestCancelRestoresCapacityAndGrams:
    """Cancelling an accepted digital order returns both conserved counters to baseline."""

    def test_cancel_releases_interval_load(self, api):
        """A placed-then-cancelled order leaves the digital interval load at zero.

        PRD §3.6: "Cancellation is fully compensating: the committed entrees are released back to the production window's committed counter and to the store's interval load, the throttle band is re-evaluated, the grams the order consumed are restored to the newest `ACTIVE` batch of each ingredient (ties on `created_at` broken by the latest `cooked_at`), suppression states are re-evaluated against the restored stock, and `payment_status` moves to `VOIDED`."
        Design: Difficulty/compensating_invariant/order_cancel_restores_capacity_and_grams
        """
        fixtures.set_clock(api, fixtures.MORNING)
        world = fixtures.store_with_bowl(api, store_overrides={"store_code": "S17"})

        order = fixtures.place_order(
            api, world["store_id"], world["item_id"], channel="FIRST_PARTY_DIGITAL", quantity=3
        )
        store = fixtures.read_store(api, world["store_id"])
        assert store["digital_interval_load"] == 3
        ingredient = fixtures.read_ingredient(api, world["ingredient_id"])
        assert ingredient["on_hand_grams"] == 9640

        cancelled = fixtures.cancel(api, world["store_id"], order["id"])
        assert cancelled["fulfillment_status"] == "CANCELLED"
        assert cancelled["payment_status"] == "VOIDED"

        store_after = fixtures.read_store(api, world["store_id"])
        assert store_after["digital_interval_load"] == 0, (
            f"cancel must restore the interval load to its baseline, got "
            f"{store_after['digital_interval_load']}"
        )

    def test_cancel_restores_consumed_grams(self, api):
        """A placed-then-cancelled order leaves the ingredient's on-hand at baseline.

        PRD §3.6: "Cancellation is fully compensating: the committed entrees are released back to the production window's committed counter and to the store's interval load, the throttle band is re-evaluated, the grams the order consumed are restored to the newest `ACTIVE` batch of each ingredient (ties on `created_at` broken by the latest `cooked_at`), suppression states are re-evaluated against the restored stock, and `payment_status` moves to `VOIDED`."
        Design: Difficulty/compensating_invariant/order_cancel_restores_capacity_and_grams
        """
        fixtures.set_clock(api, fixtures.MORNING)
        world = fixtures.store_with_bowl(api, store_overrides={"store_code": "S17"})

        order = fixtures.place_order(
            api, world["store_id"], world["item_id"], channel="FIRST_PARTY_DIGITAL", quantity=3
        )
        assert fixtures.read_ingredient(api, world["ingredient_id"])["on_hand_grams"] == 9640

        fixtures.cancel(api, world["store_id"], order["id"])

        ingredient = fixtures.read_ingredient(api, world["ingredient_id"])
        assert ingredient["on_hand_grams"] == 10000, (
            f"cancel must restore consumed grams to the newest active batch, got "
            f"{ingredient['on_hand_grams']}"
        )
        window = fixtures.read_window(api, world["window_id"])
        assert window["digital_committed"] == 0


class TestDayCloseFreezesVarianceAgainstLateWaste:
    """The day-close snapshot is immutable; post-close waste moves only the live counters."""

    def _world(self, api):
        """Three bowls picked up (theoretical 396) and 300g of chicken wasted (330c).

        The chicken unit cost is pinned to 1.1 cents/g — under the PRD §2.5
        rule that unit-cost fields preserve their input precision, the recipe
        sum is 120 x 1.1 = 132c exactly, x3 = 396c; 300g of waste costs 330c,
        for actual 396 + 330 = 726 and variance 10000*(726-396)/396 ==
        8333.33..., which rounds half-up to 8333 basis points.
        """
        fixtures.set_clock(api, fixtures.MORNING)
        world = fixtures.store_with_locked_deployment(
            api,
            chicken_unit_cost=1.1,
            store_overrides={"store_code": "S18"},
        )
        fixtures.order_picked_up(api, world, quantity=3)
        fixtures.record_waste(api, world["store_id"], world["batch_id"], 300, "OVERPRODUCTION")
        return world

    def test_day_close_freezes_the_variance_snapshot(self, api):
        """The close records round-half-up of 10000*(726-396)/396 == 8333 basis points.

        PRD §3.9: "The store's `food_cost_variance_bps` is the actual minus the theoretical, divided by the theoretical (or by one if the theoretical is zero), scaled by ten thousand, and rounded half-up to a whole basis point."
        PRD §3.9: "A successful close settles any remaining `CUTOFF` windows (moving them to `SETTLED` and reconciling each window's `digital_completed` against `digital_committed`, with shortfalls recorded on the close record), persists a `DayClose` capturing the `business_day` being closed, the `orders_accepted` and `orders_completed` counts for the day, the `digital_net_revenue_cents` across digital and marketplace orders and the `instore_net_revenue_cents` across in-store orders, and a snapshot of `food_cost_variance_bps` at close."
        Design: Difficulty/compensating_invariant/day_close_freezes_variance_against_late_waste
        """
        world = self._world(api)
        # Advance past the window's end (10:30) so it can settle before close.
        fixtures.set_clock(api, "2026-09-01T10:31:00Z")
        store = fixtures.read_store(api, world["store_id"])
        assert_cents(store["theoretical_food_cost_cents"], 396, "theoretical")
        assert_cents(store["actual_food_cost_cents"], 726, "actual")
        assert store["food_cost_variance_bps"] == 8333

        close = fixtures.close_day(api, world["store_id"])
        assert close["food_cost_variance_bps"] == 8333, (
            f"the close must freeze the live variance 8333, got {close['food_cost_variance_bps']}"
        )
        assert close["status"] == "CLOSED"

    def test_post_close_waste_leaves_the_snapshot_unchanged(self, api):
        """A waste event after close moves the live actuals but not the frozen record.

        PRD §3.9: "Read before close, the variance is provisional — it includes unsettled waste; closing the day freezes the snapshot, and waste recorded afterward posts to the next day."
        Design: Difficulty/compensating_invariant/day_close_freezes_variance_against_late_waste
        """
        world = self._world(api)
        fixtures.set_clock(api, "2026-09-01T10:31:00Z")
        close = fixtures.close_day(api, world["store_id"])
        assert close["food_cost_variance_bps"] == 8333

        before = fixtures.read_store(api, world["store_id"])
        fixtures.record_waste(api, world["store_id"], world["batch_id"], 50, "CONTAMINATION")
        after = fixtures.read_store(api, world["store_id"])
        # 50g at 1.1 cents per gram = 55 cents.
        assert after["actual_food_cost_cents"] == before["actual_food_cost_cents"] + 55

        frozen = fixtures.read_day_close(api, close["id"])
        assert frozen["food_cost_variance_bps"] == 8333, (
            "post-close waste must not disturb the frozen day-close snapshot"
        )
        assert after["food_cost_variance_bps"] != 8333, (
            "the live variance must move once post-close waste lands"
        )

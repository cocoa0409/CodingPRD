"""Boundary precision: the throttle engages at exactly the threshold; waste at exactly zero."""

from prd_bench_local_runner.testing import validate_error, validate_error_is_one_of

from test_helpers import (
    ApiErrorId,
    factories as f,
    fixtures,
)


class TestThrottleEngagesAtExactlyThreshold:
    """With capacity 10 and threshold 0.8, load 7 is OPEN and load 8 is THROTTLED."""

    def _world(self, api):
        """A store with digital capacity 10, threshold 0.8 and two open windows."""
        fixtures.set_clock(api, fixtures.MORNING)
        world = fixtures.store_with_bowl(
            api,
            chicken_grams=100000,
            chicken_par=50000,
            with_window=False,
            store_overrides={"store_code": "S11"},
        )
        fixtures.open_window(api, world["store_id"], "2026-09-01T10:15:00Z", "2026-09-01T10:30:00Z")
        fixtures.open_window(api, world["store_id"], "2026-09-01T10:30:00Z", "2026-09-01T10:45:00Z")
        return world

    def test_load_seven_below_threshold_stays_open(self, api):
        """Seven committed entrees is below ceil(0.8*10)=8, so the band stays OPEN.

        PRD §2.9: "When the committed load is below capacity but at or above the threshold formed by rounding the product of `overage_threshold_pct` and `digital_line_capacity_per_interval` up to a whole number of entrees, the state is `THROTTLED`. Below that threshold the state is `OPEN`."
        Design: Difficulty/boundary_precision_check/throttle_engages_at_exactly_ceil_threshold
        """
        world = self._world(api)
        fixtures.place_order(
            api, world["store_id"], world["item_id"], channel="FIRST_PARTY_DIGITAL", quantity=7
        )
        store = fixtures.read_store(api, world["store_id"])
        assert store["throttle_state"] == "OPEN", (
            f"load 7 is below the threshold 8 and must read OPEN, got {store['throttle_state']}"
        )

    def test_load_eight_at_threshold_engages_throttled(self, api):
        """The entree that takes the load to exactly 8 flips the band to THROTTLED.

        PRD §2.9: "The boundary is inclusive on both bands: a committed load exactly equal to the threshold is `THROTTLED`, and a load exactly equal to capacity is `CLOSED`."
        Design: Difficulty/boundary_precision_check/throttle_engages_at_exactly_ceil_threshold
        """
        world = self._world(api)
        fixtures.place_order(
            api, world["store_id"], world["item_id"], channel="FIRST_PARTY_DIGITAL", quantity=7
        )
        assert fixtures.read_store(api, world["store_id"])["throttle_state"] == "OPEN"

        eighth = fixtures.place_order(
            api, world["store_id"], world["item_id"], channel="FIRST_PARTY_DIGITAL", quantity=1
        )
        assert eighth["fulfillment_status"] == "ACCEPTED", (
            "a second open window exists, so the order at the threshold is still accepted"
        )
        store = fixtures.read_store(api, world["store_id"])
        assert store["throttle_state"] == "THROTTLED", (
            f"load 8 == ceil(0.8*10) must read THROTTLED, got {store['throttle_state']}"
        )


class TestFullBatchWasteAndZeroBoundary:
    """A full-batch waste lands the batch on WASTED with zero remaining."""

    def _world(self, api):
        """A store with a single 500g chicken batch."""
        fixtures.set_clock(api, fixtures.MORNING)
        return fixtures.store_with_bowl(
            api, chicken_grams=500, with_window=False, store_overrides={"store_code": "S12"}
        )

    def test_full_batch_waste_transitions_batch_to_wasted(self, api):
        """Wasting exactly grams_remaining transitions the batch to WASTED.

        PRD §3.7: "A partial waste leaves the batch `ACTIVE`; a full-batch waste — grams equal to `grams_remaining`, with a `CONTAMINATION` or `OVERPRODUCTION` reason — transitions the batch from `ACTIVE` to `WASTED`."
        PRD §3.7: "The event's `cost_cents` is the wasted grams multiplied by the ingredient's `unit_cost_cents_per_gram`, rounded half-up; the ingredient's `on_hand_grams` and the batch's `grams_remaining` fall by the wasted amount, the batch's `discarded_grams` grows by the same, and the store's `actual_food_cost_cents` absorbs `cost_cents`."
        Design: Difficulty/boundary_precision_check/zero_gram_batch_boundary_and_full_waste
        """
        world = self._world(api)
        waste = fixtures.record_waste(
            api, world["store_id"], world["batch_id"], 500, "CONTAMINATION"
        )
        assert waste["cost_cents"] == 1050, (
            f"500g at 2.1 cents per gram must cost 1050, got {waste['cost_cents']}"
        )

        batch = fixtures.read_batch(api, world["batch_id"])
        assert batch["status"] == "WASTED"
        assert batch["grams_remaining"] == 0
        assert batch["discarded_grams"] == 500

        ingredient = fixtures.read_ingredient(api, world["ingredient_id"])
        assert ingredient["on_hand_grams"] == 0

    def test_further_waste_against_empty_batch_is_rejected(self, api):
        """One more gram against a batch at zero remaining is rejected.

        PRD §3.7: "Recording waste in excess of the batch's `grams_remaining` is rejected with `ERR_WASTE_EXCEEDS_BATCH`."
        PRD §3.7: "a full-batch waste — grams equal to `grams_remaining`, with a `CONTAMINATION` or `OVERPRODUCTION` reason — transitions the batch from `ACTIVE` to `WASTED`."
        Note: the request is simultaneously against a terminal (WASTED) batch
        and in excess of grams_remaining; the PRD does not pin which of the
        two errors pre-empts, so either terminal-state or excess rejection is
        faithful.
        Design: Difficulty/boundary_precision_check/zero_gram_batch_boundary_and_full_waste
        """
        world = self._world(api)
        fixtures.record_waste(api, world["store_id"], world["batch_id"], 500, "CONTAMINATION")
        assert fixtures.read_batch(api, world["batch_id"])["grams_remaining"] == 0

        response = api.create_waste_event(
            world["store_id"],
            f.waste_event_payload(world["batch_id"], 1, "CONTAMINATION"),
            fixtures.LINE_WORKER_HEADERS,
        )
        validate_error_is_one_of(
            response,
            [ApiErrorId.WASTE_EXCEEDS_BATCH.value, ApiErrorId.ALREADY_TERMINAL.value],
        )

"""Interval semantics: half-open production-window adjacency vs inclusive batch TTL."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ApiErrorId,
    factories as f,
    fixtures,
)


class TestProductionWindowHalfOpenOverlap:
    """Half-open [start, end) semantics: overlap rejects, zero-gap adjacency permits."""

    def test_overlapping_window_is_rejected_and_adjacent_is_accepted(self, api):
        """A window 10:20-10:35 overlaps the existing 10:15-10:30; 10:30-10:45 is adjacent.

        PRD §3.3: "A `StoreManager` or `PlatformAdmin` opens a production window for a store by giving its `interval_start` (inclusive) and `interval_end` (exclusive); the end must be exactly the store's `pacing_interval_minutes` after the start, and the new interval must not overlap any existing window for the store — half-open adjacency, where one window's start equals another's end, is permitted, while a true overlap is rejected with `ERR_WINDOW_OVERLAP`."
        Design: Difficulty/resource_temporal_overlap/production_window_half_open_overlap_rejected
        """
        fixtures.set_clock(api, fixtures.MORNING)
        world = fixtures.store_with_bowl(api, with_window=False, store_overrides={"store_code": "S15"})
        first = fixtures.open_window(
            api, world["store_id"], "2026-09-01T10:15:00Z", "2026-09-01T10:30:00Z"
        )
        assert first["status"] == "OPEN"

        overlap = api.create_production_window(
            world["store_id"],
            f.production_window_payload(
                interval_start="2026-09-01T10:20:00Z", interval_end="2026-09-01T10:35:00Z"
            ),
            fixtures.STORE_MANAGER_HEADERS,
        )
        validate_error(overlap, ApiErrorId.WINDOW_OVERLAP.value)

        adjacent = validate_success(
            api.create_production_window(
                world["store_id"],
                f.production_window_payload(
                    interval_start="2026-09-01T10:30:00Z", interval_end="2026-09-01T10:45:00Z"
                ),
                fixtures.STORE_MANAGER_HEADERS,
            ),
            expected_status=201,
        )
        assert adjacent["status"] == "OPEN"

    def test_adjacent_window_back_to_back_on_both_sides_is_accepted(self, api):
        """Both [10:00,10:15) before and [10:30,10:45) after coexist with [10:15,10:30).

        PRD §3.3: "the new interval must not overlap any existing window for the store — half-open adjacency, where one window's start equals another's end, is permitted, while a true overlap is rejected with `ERR_WINDOW_OVERLAP`."
        Design: Difficulty/resource_temporal_overlap/production_window_half_open_overlap_rejected
        """
        fixtures.set_clock(api, fixtures.MORNING)
        world = fixtures.store_with_bowl(api, with_window=False, store_overrides={"store_code": "S15"})
        fixtures.open_window(api, world["store_id"], "2026-09-01T10:15:00Z", "2026-09-01T10:30:00Z")

        before = validate_success(
            api.create_production_window(
                world["store_id"],
                f.production_window_payload(
                    interval_start="2026-09-01T10:00:00Z", interval_end="2026-09-01T10:15:00Z"
                ),
                fixtures.STORE_MANAGER_HEADERS,
            ),
            expected_status=201,
        )
        after = validate_success(
            api.create_production_window(
                world["store_id"],
                f.production_window_payload(
                    interval_start="2026-09-01T10:30:00Z", interval_end="2026-09-01T10:45:00Z"
                ),
                fixtures.STORE_MANAGER_HEADERS,
            ),
            expected_status=201,
        )
        # The clock (10:00) has already passed the "before" window's
        # interval_start, so it is CUTOFF by the clock-driven transition of
        # §3.3; what matters for adjacency is that creation was accepted.
        assert before["status"] == "CUTOFF"
        assert after["status"] == "OPEN"


class TestHoldTimeDiscardFiresExactlyAtDiscardAt:
    """The batch TTL fires inclusively: one second before is ACTIVE; at discard_at it expires."""

    def _world(self, api):
        """Chicken batch 1000g cooked at 09:00 with a 60-minute hold: discard at 10:00."""
        fixtures.set_clock(api, "2026-09-01T09:00:00Z")
        return fixtures.store_with_bowl(
            api,
            chicken_grams=1000,
            chicken_hold_minutes=60,
            store_overrides={"store_code": "S16"},
            cooked_at="2026-09-01T09:00:00Z",
        )

    def test_one_second_before_discard_at_batch_is_still_active(self, api):
        """At 09:59:59 the batch has not yet reached its discard instant.

        PRD §2.4: "Advancing the clock fires three families of automatic transitions: any `ACTIVE` batch whose `discard_at` has been reached becomes `EXPIRED`; any `READY` order whose promise time plus forty-five minutes has passed without pickup becomes `EXPIRED`; and any `OPEN` production window whose `interval_start` has been reached moves to `CUTOFF`."
        Design: Difficulty/resource_temporal_overlap/hold_time_discard_fires_at_exactly_discard_at
        """
        world = self._world(api)
        fixtures.set_clock(api, "2026-09-01T09:59:59Z")
        batch = fixtures.read_batch(api, world["batch_id"])
        assert batch["status"] == "ACTIVE", (
            f"one second before discard_at the batch must still be ACTIVE, got {batch['status']}"
        )
        assert batch["grams_remaining"] == 1000

    def test_at_exactly_discard_at_batch_expires(self, api):
        """At 10:00:00 — exactly discard_at — the batch has expired.

        PRD §2.4: "Advancing the clock fires three families of automatic transitions: any `ACTIVE` batch whose `discard_at` has been reached becomes `EXPIRED`; any `READY` order whose promise time plus forty-five minutes has passed without pickup becomes `EXPIRED`; and any `OPEN` production window whose `interval_start` has been reached moves to `CUTOFF`."
        PRD §3.7: "Separately, when the logical clock reaches an `ACTIVE` batch's `discard_at` with grams still remaining, the batch expires: a waste event is created with reason `HOLD_TIME_EXPIRED` covering the full `grams_remaining`, `on_hand_grams` falls accordingly, the expired grams at unit cost post to `actual_food_cost_cents`, `discarded_grams` absorbs the former remainder, `grams_remaining` is set to zero, and the batch becomes `EXPIRED`."
        Design: Difficulty/resource_temporal_overlap/hold_time_discard_fires_at_exactly_discard_at
        """
        world = self._world(api)
        fixtures.set_clock(api, "2026-09-01T09:59:59Z")
        assert fixtures.read_batch(api, world["batch_id"])["status"] == "ACTIVE"

        fixtures.set_clock(api, "2026-09-01T10:00:00Z")
        batch = fixtures.read_batch(api, world["batch_id"])
        assert batch["status"] == "EXPIRED", (
            f"at exactly discard_at the batch must be EXPIRED, got {batch['status']}"
        )
        assert batch["grams_remaining"] == 0
        assert batch["discarded_grams"] == 1000

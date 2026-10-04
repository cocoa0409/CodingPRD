"""Breadth coverage of the pinned calculations: FIFO consumption, cascade recovery,
and the staffing round-then-complement split."""

from prd_bench_local_runner.testing import validate_paginated

from test_helpers import (
    fixtures,
)


class TestFifoConsumptionDrainsOldestFirst:
    def test_order_consumes_the_oldest_batch_before_the_newer_one(self, api):
        """FIFO drains the earliest-cooked ACTIVE batch first; a drained batch is DEPLETED.

        PRD §3.4: "Consumption follows strict first-in-first-out: grams are drawn from the ingredient's `ACTIVE` batches in ascending `cooked_at` order, with ascending `created_at` as the tie-break — never by identifier — taking from each batch the smaller of what is needed and that batch's `grams_remaining` until each line's required grams are satisfied. Each draw decrements the batch's `grams_remaining` and the ingredient's `on_hand_grams`; a batch drained to zero transitions from `ACTIVE` to `DEPLETED`, which may trip the shortage cascade of §3.7."
        Design: Corner/calculations/fifo_consumption_drains_oldest_batch_first
        """
        fixtures.set_clock(api, fixtures.MORNING)
        store = fixtures.create_store(api, store_code="FF")
        chicken = fixtures.create_ingredient(api)
        oldest = fixtures.cook_batch(
            api, chicken["id"], store["id"], cooked_at="2026-09-01T09:00:00Z", grams_cooked=200
        )
        newest = fixtures.cook_batch(
            api, chicken["id"], store["id"], cooked_at="2026-09-01T09:30:00Z", grams_cooked=500
        )
        item = fixtures.create_menu_item(api, store["id"])
        fixtures.add_recipe_component(api, item["id"], chicken["id"], standard_grams=250)
        fixtures.open_window(api, store["id"])

        fixtures.place_order(api, store["id"], item["id"])

        oldest_now = fixtures.read_batch(api, oldest["id"])
        newest_now = fixtures.read_batch(api, newest["id"])
        assert oldest_now["grams_remaining"] == 0
        assert oldest_now["status"] == "DEPLETED"
        assert newest_now["grams_remaining"] == 450
        assert newest_now["status"] == "ACTIVE"
        assert fixtures.read_ingredient(api, chicken["id"])["on_hand_grams"] == 450


class TestSuppressionCascadeRecoversOnNewBatch:
    def test_fresh_batch_above_half_par_resolves_shortage_suppressions(self, api):
        """Recovery resolves the shortage events and returns the item to SELLABLE.

        PRD §3.7: "Suppression events are born `ACTIVE`; recovery is also automatic — when a new batch cook pushes `on_hand_grams` back to at least half of par, the ingredient's `ACTIVE` shortage-caused events resolve to `RESOLVED`, and each item's `suppression_state` is recomputed, returning to `SELLABLE` when no other active event covers it."
        PRD §3.7: "While on-hand is at least half of par the ingredient is `STOCKED`."
        Design: Corner/calculations/suppression_cascade_recovers_on_new_batch
        """
        fixtures.set_clock(api, fixtures.MORNING)
        world = fixtures.store_with_bowl(
            api, chicken_grams=2560, store_overrides={"store_code": "RC"}
        )
        # Consume 120g: on-hand 2440 < 2500 (half of par) -> LOW and marketplace suppression.
        fixtures.place_order(
            api, world["store_id"], world["item_id"], channel="FIRST_PARTY_DIGITAL"
        )
        ingredient = fixtures.read_ingredient(api, world["ingredient_id"])
        assert ingredient["on_hand_grams"] == 2440
        assert ingredient["shortage_state"] == "LOW"
        assert (
            fixtures.read_menu_item(api, world["item_id"])["suppression_state"]
            == "SUPPRESSED_MARKETPLACE"
        )

        # A fresh 3000g cook pushes on-hand back to 5440, above half of par.
        fixtures.cook_batch(
            api,
            world["ingredient_id"],
            world["store_id"],
            cooked_at="2026-09-01T10:05:00Z",
            grams_cooked=3000,
        )

        ingredient = fixtures.read_ingredient(api, world["ingredient_id"])
        assert ingredient["on_hand_grams"] == 5440
        assert ingredient["shortage_state"] == "STOCKED"
        item = fixtures.read_menu_item(api, world["item_id"])
        assert item["suppression_state"] == "SELLABLE"

        events, _meta = validate_paginated(
            api.list_suppression_events_for_store(
                world["store_id"], fixtures.STORE_MANAGER_HEADERS
            )
        )
        shortage_events = [
            e
            for e in events
            if e["menu_item_id"] == world["item_id"] and e["cause"] == "SHORTAGE"
        ]
        assert len(shortage_events) == 1
        assert shortage_events[0]["status"] == "RESOLVED"


class TestStaffingSplitRoundThenComplement:
    def test_odd_headcount_splits_round_half_up_then_complement(self, api):
        """Seven heads at a 0.5 digital mix split 4 and 3, not 4 and 4.

        PRD §3.8: "Publishing, also by a `StoreManager`, moves a deployment from `DRAFT` to `PUBLISHED` under the same consistency rules — the mix fractions summing to one and a headcount of at least two — and computes the line split: `digital_headcount` is the `headcount` multiplied by `predicted_digital_mix_pct` rounded half-up to a whole person, and `instore_headcount` is the remainder of `headcount` once the digital share is removed, so the two always sum exactly to the scheduled total."
        Design: Corner/calculations/staffing_split_round_then_complement
        """
        fixtures.set_clock(api, fixtures.MORNING)
        store = fixtures.create_store(api, store_code="SS")
        deployment = fixtures.create_deployment(
            api, store["id"], store["version"], headcount=7
        )
        assert deployment["digital_headcount"] == 4
        assert deployment["instore_headcount"] == 3
        assert deployment["digital_headcount"] + deployment["instore_headcount"] == 7

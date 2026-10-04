"""Validation precedence: state beats safety; suppression beats capacity."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    factories as f,
    fixtures,
)


class TestStateBeatsBusinessSafety:
    """A mark-ready that fails both the state gate and the safety gate reports the state error."""

    def test_mark_ready_on_accepted_order_reports_invalid_state(self, api):
        """An ACCEPTED (never started) order fails mark-ready with the state error.

        PRD §2.7: "Beyond existence, every endpoint applies its checks in a fixed priority order: first the presence and validity of the authentication headers, then role permission for the endpoint, then path-resource existence left to right, then the optimistic-concurrency version check where one applies, then the target entity's state precondition for the requested transition, and only then the business rules specific to the operation (accuracy gating, suppression screening, ingredient sufficiency, window capacity, deployment consistency, segregation of duties, day-close preconditions, and marketplace reference validity, in that relative order where several apply to the same endpoint)."
        PRD §3.5: "A `LineWorker` may then mark the order ready, moving it from `IN_PRODUCTION` to `READY`, only when every line's `accuracy_check` is `MATCHED` following at least one `PASS` verification; otherwise the transition is rejected with `ERR_ACCURACY_UNVERIFIED`."
        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_on_mark_ready
        """
        fixtures.set_clock(api, fixtures.MORNING)
        world = fixtures.store_with_locked_deployment(api, store_overrides={"store_code": "S9"})
        order = fixtures.place_order(api, world["store_id"], world["item_id"])
        assert order["fulfillment_status"] == "ACCEPTED"
        assert order["accuracy_status"] == "UNVERIFIED"

        response = api.mark_ready(
            world["store_id"], order["id"], fixtures.LINE_WORKER_HEADERS
        )
        validate_error(response, ApiErrorId.INVALID_STATE.value)

        current = fixtures.read_order(api, order["id"])
        assert current["fulfillment_status"] == "ACCEPTED"

    def test_mark_ready_on_placed_order_stays_accepted_after_rejection(self, api):
        """The rejected mark-ready must not disturb the order's acceptance state.

        PRD §3.5: "Production begins when a `LineWorker` starts an `ACCEPTED` order, moving `fulfillment_status` from `ACCEPTED` to `IN_PRODUCTION`."
        PRD §2.7: "Beyond existence, every endpoint applies its checks in a fixed priority order: first the presence and validity of the authentication headers, then role permission for the endpoint, then path-resource existence left to right, then the optimistic-concurrency version check where one applies, then the target entity's state precondition for the requested transition, and only then the business rules specific to the operation (accuracy gating, suppression screening, ingredient sufficiency, window capacity, deployment consistency, segregation of duties, day-close preconditions, and marketplace reference validity, in that relative order where several apply to the same endpoint)."
        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_on_mark_ready
        """
        fixtures.set_clock(api, fixtures.MORNING)
        world = fixtures.store_with_locked_deployment(api, store_overrides={"store_code": "S9"})
        order = fixtures.place_order(api, world["store_id"], world["item_id"])

        response = api.mark_ready(
            world["store_id"], order["id"], fixtures.LINE_WORKER_HEADERS
        )
        validate_error(response, ApiErrorId.INVALID_STATE.value)

        # After the rejection the normal path must still work: start, verify, ready.
        started = fixtures.start_production(api, world["store_id"], order["id"])
        assert started["fulfillment_status"] == "IN_PRODUCTION"
        fixtures.verify_pass(api, world["store_id"], order["id"], world["item_id"])
        ready = fixtures.mark_ready(api, world["store_id"], order["id"])
        assert ready["fulfillment_status"] == "READY"


class TestSuppressionBeatsCapacity:
    """A suppressed item reports ERR_ITEM_SUPPRESSED even when the line is also full."""

    def _world(self, api):
        """Store with digital capacity 1; chicken batch of 1300g that will expire at
        10:00; two windows both filled with RICECUP orders before suppression."""
        fixtures.set_clock(api, "2026-09-01T09:30:00Z")
        world = fixtures.store_with_bowl(
            api,
            chicken_grams=1300,
            chicken_hold_minutes=60,
            with_window=False,
            store_overrides={
                "store_code": "S10",
                "digital_line_capacity_per_interval": 1,
                "instore_line_capacity_per_interval": 50,
                "overage_threshold_pct": 1.0,
            },
        )
        rice = fixtures.create_ingredient(
            api,
            ingredient_code="RICE",
            display_name="White Rice",
            unit_cost_cents_per_gram=0.8,
            par_level_grams=5000,
            hold_time_minutes=240,
            batch_size_grams=4000,
        )
        fixtures.cook_batch(api, rice["id"], world["store_id"], grams_cooked=10000)
        rice_cup = fixtures.create_menu_item(
            api, world["store_id"], item_code="RICECUP", display_name="Rice Cup",
            base_price_cents=300,
        )
        fixtures.add_recipe_component(api, rice_cup["id"], rice["id"], standard_grams=180)
        world["rice_cup_id"] = rice_cup["id"]
        fixtures.open_window(api, world["store_id"], "2026-09-01T10:15:00Z", "2026-09-01T10:30:00Z")
        fixtures.open_window(api, world["store_id"], "2026-09-01T10:30:00Z", "2026-09-01T10:45:00Z")
        # Consume 120g of chicken so the 10:00 expiry leaves zero on hand.
        fixtures.place_order(api, world["store_id"], world["item_id"], channel="IN_STORE")
        # Fill both digital windows with the non-suppressed rice cup.
        fixtures.place_order(api, world["store_id"], rice_cup["id"], channel="FIRST_PARTY_DIGITAL")
        fixtures.place_order(api, world["store_id"], rice_cup["id"], channel="FIRST_PARTY_DIGITAL")
        # Cross the chicken batch's discard_at so it expires and suppresses BOWL on all channels.
        fixtures.set_clock(api, "2026-09-01T10:01:00Z")
        return world

    def test_suppressed_and_full_line_reports_item_suppressed(self, api):
        """Suppression screening runs before the capacity waterfall in the acceptance chain.

        PRD §3.4: "Acceptance runs a fixed chain of checks, in order: suppression screening first, then ingredient sufficiency, then window capacity. Every line's menu item must permit the order's channel — `SELLABLE` items permit all channels, `SUPPRESSED_MARKETPLACE` blocks marketplace only, and `SUPPRESSED_ALL` blocks everything; a `SUPPRESSED_DIGITAL` item blocks the digital line — otherwise the order is rejected with `ERR_ITEM_SUPPRESSED`."
        Design: Difficulty/priority_pair_validation_conflict/business_referential_beats_business_temporal_on_order_place
        """
        world = self._world(api)
        item = fixtures.read_menu_item(api, world["item_id"])
        assert item["suppression_state"] == "SUPPRESSED_ALL"

        response = api.create_order(
            world["store_id"],
            f.order_payload(
                "FIRST_PARTY_DIGITAL", [f.order_line_payload(world["item_id"])]
            ),
            fixtures.STORE_MANAGER_HEADERS,
        )
        validate_error(response, ApiErrorId.ITEM_SUPPRESSED.value)

    def test_unsuppressed_item_at_capacity_reports_capacity_exceeded(self, api):
        """With every open window full, an unsuppressed item reaches the capacity check.

        PRD §3.3: "If no open window is eligible, placement is rejected with `ERR_LINE_CAPACITY_EXCEEDED`."
        PRD §3.4: "Acceptance runs a fixed chain of checks, in order: suppression screening first, then ingredient sufficiency, then window capacity."
        Design: Difficulty/priority_pair_validation_conflict/business_referential_beats_business_temporal_on_order_place
        """
        world = self._world(api)
        response = api.create_order(
            world["store_id"],
            f.order_payload(
                "FIRST_PARTY_DIGITAL", [f.order_line_payload(world["rice_cup_id"])]
            ),
            fixtures.STORE_MANAGER_HEADERS,
        )
        validate_error(response, ApiErrorId.LINE_CAPACITY_EXCEEDED.value)

"""Transitive cascades: consumption-driven and expiry-driven suppression."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
)

from test_helpers import (
    ApiErrorId,
    factories as f,
    fixtures,
    make_marketplace_channel_headers,
)


class TestConsumptionCascadeToMarketplaceSuppression:
    """Order consumption drops stock below half of par and suppresses the marketplace."""

    def _world(self, api):
        """Chicken cooked with exactly 2560g — just above the 2500g half-of-par line."""
        fixtures.set_clock(api, fixtures.MORNING)
        world = fixtures.store_with_bowl(
            api, chicken_grams=2560, store_overrides={"store_code": "S7"}
        )
        channel = fixtures.create_marketplace_channel(
            api, channel_code="DASH", markup_pct=0.18, commission_pct=0.22, active=True
        )
        world["channel_id"] = channel["id"]
        return world

    def test_crossing_below_half_par_creates_marketplace_scoped_suppression(self, api):
        """Dropping on-hand below half of par flips the item to SUPPRESSED_MARKETPLACE.

        PRD §3.7: "Once on-hand falls below half of par but stays at or above a quarter of par, the ingredient is `LOW`, and the cascade fires: for every menu item whose recipe includes the ingredient, if the item `is_digital_eligible` the system creates a `SuppressionEvent` with `scope` `MARKETPLACE` and `cause` `SHORTAGE`, and the item's `suppression_state` becomes `SUPPRESSED_MARKETPLACE`."
        Design: Difficulty/transitive_cascade/ingredient_depletion_cascades_to_marketplace_suppression
        """
        world = self._world(api)
        fixtures.place_order(
            api, world["store_id"], world["item_id"], channel="FIRST_PARTY_DIGITAL"
        )

        ingredient = fixtures.read_ingredient(api, world["ingredient_id"])
        assert ingredient["on_hand_grams"] == 2440
        assert ingredient["shortage_state"] == "LOW"

        item = fixtures.read_menu_item(api, world["item_id"])
        assert item["suppression_state"] == "SUPPRESSED_MARKETPLACE"

        events, _meta = validate_paginated(
            api.list_suppression_events_for_store(
                world["store_id"], fixtures.STORE_MANAGER_HEADERS
            )
        )
        matching = [
            e
            for e in events
            if e["menu_item_id"] == world["item_id"]
            and e["scope"] == "MARKETPLACE"
            and e["cause"] == "SHORTAGE"
            and e["status"] == "ACTIVE"
        ]
        assert len(matching) == 1, (
            f"expected exactly one ACTIVE SHORTAGE MARKETPLACE event, got {matching}"
        )

    def test_marketplace_order_blocked_but_first_party_still_accepted(self, api):
        """The marketplace-scoped suppression blocks only the marketplace channel.

        PRD §3.4: "Every line's menu item must permit the order's channel — `SELLABLE` items permit all channels, `SUPPRESSED_MARKETPLACE` blocks marketplace only, and `SUPPRESSED_ALL` blocks everything; a `SUPPRESSED_DIGITAL` item blocks the digital line — otherwise the order is rejected with `ERR_ITEM_SUPPRESSED`."
        Design: Difficulty/transitive_cascade/ingredient_depletion_cascades_to_marketplace_suppression
        """
        world = self._world(api)
        fixtures.place_order(
            api, world["store_id"], world["item_id"], channel="FIRST_PARTY_DIGITAL"
        )
        assert (
            fixtures.read_menu_item(api, world["item_id"])["suppression_state"]
            == "SUPPRESSED_MARKETPLACE"
        )

        rejected = api.create_order(
            world["store_id"],
            f.order_payload(
                "MARKETPLACE",
                [f.order_line_payload(world["item_id"])],
                marketplace_channel_id=world["channel_id"],
                external_order_ref="DASH-3001",
            ),
            make_marketplace_channel_headers(world["channel_id"]),
        )
        validate_error(rejected, ApiErrorId.ITEM_SUPPRESSED.value)

        accepted = fixtures.place_order(
            api, world["store_id"], world["item_id"], channel="FIRST_PARTY_DIGITAL"
        )
        assert accepted["fulfillment_status"] == "ACCEPTED", (
            "a marketplace-scoped suppression must leave the first-party digital channel open"
        )


class TestHoldTimeExpiryCascade:
    """Clock-driven expiry empties the ingredient and suppresses every channel."""

    def _world(self, api):
        """Chicken par 5000, hold 60 minutes; 1300g cooked at 09:00 (discard 10:00);
        one order consumes 120g so 1180g remains to expire."""
        fixtures.set_clock(api, "2026-09-01T09:30:00Z")
        world = fixtures.store_with_bowl(
            api,
            chicken_grams=1300,
            chicken_hold_minutes=60,
            store_overrides={"store_code": "S8"},
        )
        fixtures.place_order(api, world["store_id"], world["item_id"], channel="IN_STORE")
        return world

    def test_expiry_posts_waste_and_collapses_on_hand(self, api):
        """At discard_at the batch expires, posting a full-remainder HOLD_TIME_EXPIRED waste event.

        PRD §3.7: "Separately, when the logical clock reaches an `ACTIVE` batch's `discard_at` with grams still remaining, the batch expires: a waste event is created with reason `HOLD_TIME_EXPIRED` covering the full `grams_remaining`, `on_hand_grams` falls accordingly, the expired grams at unit cost post to `actual_food_cost_cents`, `discarded_grams` absorbs the former remainder, `grams_remaining` is set to zero, and the batch becomes `EXPIRED`."
        Design: Difficulty/transitive_cascade/hold_time_expiry_cascades_through_waste_to_suppression
        """
        world = self._world(api)
        fixtures.set_clock(api, "2026-09-01T10:01:00Z")

        batch = fixtures.read_batch(api, world["batch_id"])
        assert batch["status"] == "EXPIRED"
        assert batch["grams_remaining"] == 0
        assert batch["discarded_grams"] == 1180

        events, _meta = validate_paginated(
            api.list_waste_events_for_store(world["store_id"], fixtures.GENERAL_MANAGER_HEADERS)
        )
        expiry_events = [e for e in events if e["reason"] == "HOLD_TIME_EXPIRED"]
        assert len(expiry_events) == 1, f"expected one HOLD_TIME_EXPIRED event, got {expiry_events}"
        assert expiry_events[0]["grams"] == 1180
        assert expiry_events[0]["ingredient_batch_id"] == world["batch_id"]

        ingredient = fixtures.read_ingredient(api, world["ingredient_id"])
        assert ingredient["on_hand_grams"] == 0
        assert ingredient["shortage_state"] == "DEPLETED"

    def test_depletion_escalates_to_all_channels_and_blocks_in_store(self, api):
        """Below a quarter of par the cascade escalates to scope ALL and blocks even in-store.

        PRD §3.7: "If on-hand falls below a quarter of par the ingredient is `DEPLETED`: every `ACTIVE` shortage-driven suppression event for the ingredient escalates to `scope` `ALL`, and affected items become `SUPPRESSED_ALL`."
        PRD §3.4: "Every line's menu item must permit the order's channel — `SELLABLE` items permit all channels, `SUPPRESSED_MARKETPLACE` blocks marketplace only, and `SUPPRESSED_ALL` blocks everything; a `SUPPRESSED_DIGITAL` item blocks the digital line — otherwise the order is rejected with `ERR_ITEM_SUPPRESSED`."
        Design: Difficulty/transitive_cascade/hold_time_expiry_cascades_through_waste_to_suppression
        """
        world = self._world(api)
        fixtures.set_clock(api, "2026-09-01T10:01:00Z")

        item = fixtures.read_menu_item(api, world["item_id"])
        assert item["suppression_state"] == "SUPPRESSED_ALL"

        rejected = api.create_order(
            world["store_id"],
            f.order_payload("IN_STORE", [f.order_line_payload(world["item_id"])]),
            fixtures.LINE_WORKER_HEADERS,
        )
        validate_error(rejected, ApiErrorId.ITEM_SUPPRESSED.value)

        events, _meta = validate_paginated(
            api.list_suppression_events_for_store(
                world["store_id"], fixtures.STORE_MANAGER_HEADERS
            )
        )
        escalated = [
            e
            for e in events
            if e["menu_item_id"] == world["item_id"]
            and e["scope"] == "ALL"
            and e["cause"] == "SHORTAGE"
            and e["status"] == "ACTIVE"
        ]
        assert len(escalated) == 1, (
            f"expected the shortage event escalated to scope ALL, got {escalated}"
        )

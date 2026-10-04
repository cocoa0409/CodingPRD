"""Cross-entity state gates: deployment presence gates production; suppression gates acceptance."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    factories as f,
    fixtures,
)


class TestStartProductionRequiresPublishedDeployment:
    """An ACCEPTED order cannot start production while its only deployment is DRAFT."""

    def test_draft_deployment_blocks_start_production(self, api):
        """Without a PUBLISHED or LOCKED deployment for the day, the start is refused.

        PRD §3.5: "Two preconditions gate the start: the order must currently be `ACCEPTED` (any other state is `ERR_INVALID_STATE`, and any terminal state is `ERR_ALREADY_TERMINAL`), and a staffing deployment covering the order's line must exist in `PUBLISHED` or `LOCKED` status for a `shift_date` equal to the store's `current_business_day` — without one the start is refused with `ERR_DEPLOYMENT_MISSING`."
        Design: Difficulty/cross_entity_state_dependency/start_production_requires_locked_deployment
        """
        fixtures.set_clock(api, fixtures.MORNING)
        world = fixtures.store_with_bowl(api, store_overrides={"store_code": "S13"})
        # A deployment exists but is never published.
        deployment = fixtures.create_deployment(
            api, world["store_id"], world["store_version"]
        )
        assert deployment["status"] == "DRAFT"

        order = fixtures.place_order(api, world["store_id"], world["item_id"])
        response = api.start_production(
            world["store_id"], order["id"], fixtures.LINE_WORKER_HEADERS
        )
        assert response.status_code == 409, (
            f"expected 409, got {response.status_code}: {response.text}"
        )
        assert response.json()["data"]["error_id"] == "ERR_DEPLOYMENT_MISSING"

        current = fixtures.read_order(api, order["id"])
        assert current["fulfillment_status"] == "ACCEPTED"

    def test_publish_and_lock_unblocks_start_production(self, api):
        """Once the deployment is published and locked by another user, the start succeeds.

        PRD §3.5: "a staffing deployment covering the order's line must exist in `PUBLISHED` or `LOCKED` status for a `shift_date` equal to the store's `current_business_day` — without one the start is refused with `ERR_DEPLOYMENT_MISSING`."
        PRD §3.8: "a `GeneralManager` — necessarily a different person than the publisher, per the segregation-of-duties rule of §2.10 — locks a `PUBLISHED` deployment, moving it to `LOCKED`; a same-user lock is refused with `ERR_SEGREGATION_OF_DUTIES`."
        Design: Difficulty/cross_entity_state_dependency/start_production_requires_locked_deployment
        """
        fixtures.set_clock(api, fixtures.MORNING)
        world = fixtures.store_with_bowl(api, store_overrides={"store_code": "S13"})
        deployment = fixtures.create_deployment(
            api, world["store_id"], world["store_version"]
        )
        order = fixtures.place_order(api, world["store_id"], world["item_id"])

        response = api.start_production(
            world["store_id"], order["id"], fixtures.LINE_WORKER_HEADERS
        )
        assert response.status_code == 409
        assert response.json()["data"]["error_id"] == "ERR_DEPLOYMENT_MISSING"

        fixtures.publish_deployment(api, world["store_id"], deployment["id"], publisher_id="sm-pat")
        locked = fixtures.lock_deployment(api, world["store_id"], deployment["id"], locker_id="gm-quinn")
        assert locked["status"] == "LOCKED"

        started = fixtures.start_production(api, world["store_id"], order["id"])
        assert started["fulfillment_status"] == "IN_PRODUCTION"
        assert started["payment_status"] == "CAPTURED"


class TestAcceptanceGatedOnSuppression:
    """A SUPPRESSED_ALL item blocks order acceptance on every channel."""

    def _suppressed_world(self, api):
        """Chicken batch 1300g (hold 60min); one order consumes 120g; clock then crosses
        discard_at so the batch expires and the item is SUPPRESSED_ALL."""
        fixtures.set_clock(api, "2026-09-01T09:30:00Z")
        world = fixtures.store_with_bowl(
            api,
            chicken_grams=1300,
            chicken_hold_minutes=60,
            store_overrides={"store_code": "S14"},
        )
        fixtures.place_order(api, world["store_id"], world["item_id"], channel="IN_STORE")
        fixtures.set_clock(api, "2026-09-01T10:01:00Z")
        return world

    def test_suppressed_all_item_blocks_in_store_order(self, api):
        """SUPPRESSED_ALL blocks every channel, including the in-store line.

        PRD §3.4: "Every line's menu item must permit the order's channel — `SELLABLE` items permit all channels, `SUPPRESSED_MARKETPLACE` blocks marketplace only, and `SUPPRESSED_ALL` blocks everything; a `SUPPRESSED_DIGITAL` item blocks the digital line — otherwise the order is rejected with `ERR_ITEM_SUPPRESSED`."
        Design: Difficulty/cross_entity_state_dependency/order_acceptance_gated_on_menuitem_suppression
        """
        world = self._suppressed_world(api)
        item = fixtures.read_menu_item(api, world["item_id"])
        assert item["suppression_state"] == "SUPPRESSED_ALL"

        response = api.create_order(
            world["store_id"],
            f.order_payload("IN_STORE", [f.order_line_payload(world["item_id"])]),
            fixtures.LINE_WORKER_HEADERS,
        )
        validate_error(response, ApiErrorId.ITEM_SUPPRESSED.value)

    def test_rejected_order_leaves_no_order_row(self, api):
        """The rejected placement persists nothing: the store's order list stays put.

        PRD §3.4: "Acceptance runs a fixed chain of checks, in order: suppression screening first, then ingredient sufficiency, then window capacity. Every line's menu item must permit the order's channel — `SELLABLE` items permit all channels, `SUPPRESSED_MARKETPLACE` blocks marketplace only, and `SUPPRESSED_ALL` blocks everything; a `SUPPRESSED_DIGITAL` item blocks the digital line — otherwise the order is rejected with `ERR_ITEM_SUPPRESSED`."
        Design: Difficulty/cross_entity_state_dependency/order_acceptance_gated_on_menuitem_suppression
        """
        world = self._suppressed_world(api)
        from prd_bench_local_runner.testing import validate_paginated

        before, meta_before = validate_paginated(
            api.list_orders_for_store(world["store_id"], fixtures.STORE_MANAGER_HEADERS)
        )
        response = api.create_order(
            world["store_id"],
            f.order_payload("IN_STORE", [f.order_line_payload(world["item_id"])]),
            fixtures.LINE_WORKER_HEADERS,
        )
        validate_error(response, ApiErrorId.ITEM_SUPPRESSED.value)

        after, meta_after = validate_paginated(
            api.list_orders_for_store(world["store_id"], fixtures.STORE_MANAGER_HEADERS)
        )
        assert meta_after["total_count"] == meta_before["total_count"], (
            "a rejected placement must not persist an order row"
        )
        assert {o["id"] for o in after} == {o["id"] for o in before}

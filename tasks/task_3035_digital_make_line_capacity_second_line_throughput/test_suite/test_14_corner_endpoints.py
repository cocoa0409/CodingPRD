"""Breadth coverage of endpoint behavior: menu-item creation defaults and the
append-only verification history read."""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import (
    factories as f,
    fixtures,
)


class TestCreateMenuItemInitializesComputedFields:
    def test_new_menu_item_starts_sellable_with_zero_theoretical_cost(self, api):
        """A created menu item starts SELLABLE with no theoretical cost yet.

        PRD §3.2: "Each menu item carries an `item_code`, a customer-facing `display_name`, a `base_price_cents` that serves both walk-in and first-party digital guests, and an `is_digital_eligible` flag (defaulting to true) controlling whether the item may be sold on the digital make-line. A new item's `suppression_state` is `SELLABLE` and its `theoretical_cost_cents` is zero until its recipe is defined."
        Design: Corner/endpoints/create_menu_item_is_action_endpoint_with_computed_cost
        """
        fixtures.set_clock(api, fixtures.MORNING)
        store = fixtures.create_store(api, store_code="EP")
        item = validate_success(
            api.create_menu_item(
                store["id"],
                f.menu_item_payload(item_code="TACO", display_name="Taco", base_price_cents=850),
                fixtures.STORE_MANAGER_HEADERS,
            ),
            expected_status=201,
        )
        assert item["theoretical_cost_cents"] == 0
        assert item["suppression_state"] == "SELLABLE"
        assert item["base_price_cents"] == 850


class TestVerificationsListIsComputedRead:
    def test_verifications_list_returns_the_recorded_fail(self, api):
        """The order's verification history returns the recorded pass as an array.

        PRD §3.5: "A `LineWorker` submits a verification pass with per-line match results (`line_results`); the server counts the order's lines into `checked_components`, counts the lines whose checked contents diverge from the standard recipe as modified by their customizations into `mismatched_lines`, records the acting worker's `X-User-ID` as `verified_by`, and keeps a `created_at_note` reserved for the verification pass ordinal."
        PRD §3.5: "When at least one line mismatches, the result is `FAIL`, the offending lines' `accuracy_check` becomes `MISMATCHED`, and the order's `accuracy_status` becomes `MISMATCHED`; the order remains `IN_PRODUCTION`, and after rework it may be verified again — the accuracy axis is cyclic, so `MISMATCHED` may legitimately return to `VERIFIED` on a later pass."
        Design: Corner/endpoints/verifications_list_is_computed_read
        """
        fixtures.set_clock(api, fixtures.MORNING)
        world = fixtures.store_with_locked_deployment(api, store_overrides={"store_code": "VR"})
        order = fixtures.order_in_production(api, world)
        fixtures.verify_fail(api, world["store_id"], order["id"], world["item_id"])

        rows, meta = validate_paginated(
            api.list_verifications_for_order(order["id"], fixtures.GENERAL_MANAGER_HEADERS)
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert rows[0]["result"] == "FAIL"
        assert rows[0]["mismatched_lines"] == 1
        assert rows[0]["checked_components"] == 1
        assert rows[0]["order_id"] == order["id"]

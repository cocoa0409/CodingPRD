"""Non-linear order state: parallel payment/fulfillment axes and the cyclic accuracy axis."""


from test_helpers import (
    fixtures,
)


class TestParallelPaymentFulfillmentAxes:
    """Fulfillment walks forward while payment evolves on its own axis."""

    def test_ready_order_expiry_moves_fulfillment_forward_and_refunds_payment(self, api):
        """Promise expiry ends the order EXPIRED while payment flips to REFUNDED.

        PRD §3.5: "If a ready order is never collected, the system expires it once the logical clock passes `promised_at` plus forty-five minutes: `fulfillment_status` moves from `READY` to `EXPIRED`, the captured payment is refunded (`CAPTURED` to `REFUNDED`), and the store's interval load is released."
        Design: Difficulty/non_linear_state_machine/order_parallel_payment_fulfillment_axes
        """
        fixtures.set_clock(api, fixtures.MORNING)
        world = fixtures.store_with_locked_deployment(api, store_overrides={"store_code": "S5"})
        order = fixtures.order_ready(api, world)
        assert order["fulfillment_status"] == "READY"
        assert order["payment_status"] == "CAPTURED"

        # In-store promise: placed 10:00 + 15 minutes = 10:15; +45 minutes = 11:00.
        fixtures.set_clock(api, "2026-09-01T11:16:00Z")
        expired = fixtures.read_order(api, order["id"])
        assert expired["fulfillment_status"] == "EXPIRED", (
            f"expected EXPIRED after promise+45min, got {expired['fulfillment_status']}"
        )
        assert expired["payment_status"] == "REFUNDED", (
            f"expected REFUNDED after expiry, got {expired['payment_status']}"
        )

    def test_start_production_captures_payment_while_fulfillment_advances(self, api):
        """Starting production moves only the payment axis; fulfillment advances on its own.

        PRD §3.5: "Starting production captures payment, moving `payment_status` from `AUTHORIZED` to `CAPTURED`."
        Design: Difficulty/non_linear_state_machine/order_parallel_payment_fulfillment_axes
        """
        fixtures.set_clock(api, fixtures.MORNING)
        world = fixtures.store_with_locked_deployment(api, store_overrides={"store_code": "S5"})
        order = fixtures.place_order(api, world["store_id"], world["item_id"])
        assert order["fulfillment_status"] == "ACCEPTED"
        assert order["payment_status"] == "AUTHORIZED"

        started = fixtures.start_production(api, world["store_id"], order["id"])
        assert started["fulfillment_status"] == "IN_PRODUCTION"
        assert started["payment_status"] == "CAPTURED", (
            "starting production must capture payment while fulfillment advances independently"
        )


class TestAccuracyReworkLoop:
    """The accuracy axis cycles UNVERIFIED -> MISMATCHED -> VERIFIED."""

    def test_fail_verification_leaves_order_in_production_and_mismatched(self, api):
        """A FAIL pass flags the mismatched lines and the order stays IN_PRODUCTION.

        PRD §3.5: "When at least one line mismatches, the result is `FAIL`, the offending lines' `accuracy_check` becomes `MISMATCHED`, and the order's `accuracy_status` becomes `MISMATCHED`; the order remains `IN_PRODUCTION`, and after rework it may be verified again — the accuracy axis is cyclic, so `MISMATCHED` may legitimately return to `VERIFIED` on a later pass."
        Design: Difficulty/non_linear_state_machine/accuracy_status_cyclic_rework_loop
        """
        fixtures.set_clock(api, fixtures.MORNING)
        world = fixtures.store_with_locked_deployment(api, store_overrides={"store_code": "S6"})
        order = fixtures.order_in_production(api, world)

        failed = fixtures.verify_fail(api, world["store_id"], order["id"], world["item_id"])
        assert failed["result"] == "FAIL"
        assert failed["mismatched_lines"] == 1

        current = fixtures.read_order(api, order["id"])
        assert current["accuracy_status"] == "MISMATCHED"
        assert current["fulfillment_status"] == "IN_PRODUCTION", (
            "a FAIL verification must not advance or terminate fulfillment"
        )

    def test_reverify_after_rework_returns_accuracy_to_verified(self, api):
        """A PASS pass after a FAIL flips the order back to VERIFIED so mark-ready can run.

        PRD §3.5: "When no line mismatches, the pass `result` is `PASS`, every line's `accuracy_check` becomes `MATCHED`, and the order's `accuracy_status` becomes `VERIFIED`."
        PRD §3.5: "the order remains `IN_PRODUCTION`, and after rework it may be verified again — the accuracy axis is cyclic, so `MISMATCHED` may legitimately return to `VERIFIED` on a later pass."
        Design: Difficulty/non_linear_state_machine/accuracy_status_cyclic_rework_loop
        """
        fixtures.set_clock(api, fixtures.MORNING)
        world = fixtures.store_with_locked_deployment(api, store_overrides={"store_code": "S6"})
        order = fixtures.order_in_production(api, world)

        fixtures.verify_fail(api, world["store_id"], order["id"], world["item_id"])
        assert fixtures.read_order(api, order["id"])["accuracy_status"] == "MISMATCHED"

        passed = fixtures.verify_pass(api, world["store_id"], order["id"], world["item_id"])
        assert passed["result"] == "PASS"
        assert passed["mismatched_lines"] == 0

        current = fixtures.read_order(api, order["id"])
        assert current["accuracy_status"] == "VERIFIED", (
            "MISMATCHED must be able to return to VERIFIED on a later pass"
        )

        ready = fixtures.mark_ready(api, world["store_id"], order["id"])
        assert ready["fulfillment_status"] == "READY", (
            "mark-ready succeeds once accuracy_status is VERIFIED"
        )

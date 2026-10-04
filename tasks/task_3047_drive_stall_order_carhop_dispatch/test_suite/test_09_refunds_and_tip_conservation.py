"""Cancel-of-captured fiscal gate and refund-driven tip/wallet conservation."""
from test_helpers import (
    TEST_DEFAULTS,
    TEST_USERS,
    ApiErrorId,
    authorize_and_capture,
    place_and_ready,
    place_order,
    set_clock,
    setup_delivered_order,
    setup_stall_draft_order,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["shift_manager_headers"]


class TestCancelOfCapturedRequiresRefund:
    def test_state_vs_business_fiscal_on_cancel_of_captured_placed_order(self, api):
        """PRD: "From `PLACED`, `PREPARING`, or `READY`, cancellation is a
        `ShiftManager`-only act and requires the payment to be `UNPAID`,
        `AUTHORIZED`, or `VOIDED`; a captured order refuses cancellation with
        `ERR_PAYMENT_CAPTURED_REQUIRES_REFUND` and must go through refund
        instead."

        A PLACED order with CAPTURED payment is a valid from-state for
        cancellation, so the fiscal gate is the one that fires.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_cancel_of_captured_placed_order
        """
        set_clock(TEST_DEFAULTS["CLOCK_0800_LOCAL"])
        ctx = setup_stall_draft_order(code="DIFF-FISC1", item_price=500, stall_capacity=2)
        location_id = ctx["location"]["id"]
        order_id = ctx["order"]["id"]
        place_order(location_id, order_id)
        authorize_and_capture(location_id, order_id)

        resp = api.cancel_order(location_id, order_id, MANAGER)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_CAPTURED_REQUIRES_REFUND)

        order = validate_success(api.get_order(location_id, order_id, MANAGER), 200)
        assert order["status"] == "PLACED"
        assert order["payment_status"] == "CAPTURED"

    def test_cancel_of_captured_ready_order_also_rejected(self, api):
        """PRD: "From `PLACED`, `PREPARING`, or `READY`, cancellation is a
        `ShiftManager`-only act and requires the payment to be `UNPAID`,
        `AUTHORIZED`, or `VOIDED`; a captured order refuses cancellation with
        `ERR_PAYMENT_CAPTURED_REQUIRES_REFUND` and must go through refund
        instead."

        The same fiscal gate fires at READY: the order stays READY and
        CAPTURED.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_cancel_of_captured_placed_order
        """
        set_clock(TEST_DEFAULTS["CLOCK_0800_LOCAL"])
        ctx = setup_stall_draft_order(code="DIFF-FISC2", item_price=500, stall_capacity=2)
        location_id = ctx["location"]["id"]
        order_id = ctx["order"]["id"]
        place_and_ready(location_id, order_id)
        authorize_and_capture(location_id, order_id)

        resp = api.cancel_order(location_id, order_id, MANAGER)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_CAPTURED_REQUIRES_REFUND)

        order = validate_success(api.get_order(location_id, order_id, MANAGER), 200)
        assert order["status"] == "READY"
        assert order["payment_status"] == "CAPTURED"


class TestRefundVoidsTipAndRestoresConservation:
    def test_refund_voids_tip_and_restores_wallet_conservation(self, api):
        """PRD: "Refund moves `CAPTURED` → `REFUNDED`, voids the order's
        TipRecord, decrements the carhop's `tips_outstanding_cents` by the
        recorded tip, and — when the request's `refund_mode` is `STORE_CREDIT`
        — credits the customer's `wallet_credit_cents` by `total_cents`,
        notably excluding the tip."

        A captured order carrying a 100c tip leaves the carhop with 100c of
        outstanding tips; refunding voids the record and returns the counter
        to 0.

        Design: Difficulty/compensating_invariant/refund_voids_tip_and_restores_wallet_conservation
        """
        set_clock(TEST_DEFAULTS["CLOCK_0800_LOCAL"])
        ctx = setup_delivered_order(
            code="DIFF-REF1", item_price=1000, stall_capacity=2,
            carhop_name="Hop F", carhop_zone="NORTH", tip_cents=100,
        )
        location_id = ctx["location"]["id"]
        order_id = ctx["order"]["id"]
        carhop_id = ctx["carhop"]["id"]

        carhop_before = validate_success(
            api.get_carhop(location_id, carhop_id, MANAGER), 200
        )
        assert carhop_before["tips_outstanding_cents"] == 100

        refunded = validate_success(
            api.refund_order(location_id, order_id, {"refund_mode": "STORE_CREDIT"}, MANAGER),
            200,
        )
        assert refunded["payment_status"] == "REFUNDED"

        carhop_after = validate_success(
            api.get_carhop(location_id, carhop_id, MANAGER), 200
        )
        assert carhop_after["tips_outstanding_cents"] == 0
        assert carhop_after["tips_settled_cents"] == 0

        tips = validate_success(
            api.list_tip_records(location_id, MANAGER, params={"order_id": order_id}), 200
        )
        assert len(tips) == 1
        assert tips[0]["status"] == "VOIDED"
        assert tips[0]["tip_cents"] == 100

    def test_refund_of_delivered_order_keeps_fulfillment_delivered(self, api):
        """PRD: "A refund requires `payment_status` of `CAPTURED` and is
        freely allowed on a `DELIVERED` order"

        Refunding a delivered order moves only the payment axis to REFUNDED;
        the fulfillment state stays DELIVERED.

        Design: Difficulty/compensating_invariant/refund_voids_tip_and_restores_wallet_conservation
        """
        set_clock(TEST_DEFAULTS["CLOCK_0800_LOCAL"])
        ctx = setup_delivered_order(
            code="DIFF-REF2", item_price=1000, stall_capacity=2,
            carhop_name="Hop F2", carhop_zone="NORTH", tip_cents=100,
        )
        location_id = ctx["location"]["id"]
        order_id = ctx["order"]["id"]

        refunded = validate_success(
            api.refund_order(location_id, order_id, {"refund_mode": "STORE_CREDIT"}, MANAGER),
            200,
        )
        assert refunded["payment_status"] == "REFUNDED"

        order = validate_success(api.get_order(location_id, order_id, MANAGER), 200)
        assert order["status"] == "DELIVERED"
        assert order["payment_status"] == "REFUNDED"

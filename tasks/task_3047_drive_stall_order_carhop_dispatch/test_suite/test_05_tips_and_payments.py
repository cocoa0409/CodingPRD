"""Tip resolution variants and immediate wallet/tip reflection at capture."""
from test_helpers import (
    TEST_DEFAULTS,
    TEST_USERS,
    add_line,
    assert_order,
    authorize_and_capture,
    create_drive_thru_order_with_line,
    create_location,
    create_service_target,
    place_order,
    set_clock,
    setup_drive_thru_location,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["shift_manager_headers"]


def _create_customer(email, stored_tip_default_pct):
    resp = api_create_customer(email, stored_tip_default_pct)
    return validate_success(resp, 201)


def api_create_customer(email, stored_tip_default_pct):
    from test_helpers import api_client, create_customer_payload

    return api_client.create_customer(
        create_customer_payload(email=email, stored_tip_default_pct=stored_tip_default_pct),
        ADMIN,
    )


class TestTipResolutionVariants:
    def test_tip_resolution_default_pct_vs_explicit_tip_diverge(self, api):
        """PRD: "Capture requires `AUTHORIZED` and resolves the tip first: an
        explicit `tip_cents` in the request wins outright; otherwise, when the
        order has a customer whose `stored_tip_default_pct` — a number between
        0 and 0.50, defaulting to 0 — is greater than zero, the tip is
        `total_cents` multiplied by that percentage, rounded half-up to the
        cent; otherwise the tip is zero. The order's `total_tendered_cents` is
        then `total_cents` plus `tip_cents`"

        Two identical 1000c drive-thru orders: the one captured with an
        explicit 100c tip tenders 1100c; the one falling back to the 0.20
        stored default tenders 1200c.

        Design: Difficulty/dual_variant_calc/tip_resolution_default_pct_vs_explicit_tip_diverge
        """
        set_clock(TEST_DEFAULTS["CLOCK_0800_LOCAL"])
        ctx = setup_drive_thru_location(code="DIFF-TIP1", target_seconds=300, item_price=1000)
        location_id = ctx["location"]["id"]
        item_id = ctx["item"]["id"]
        customer = _create_customer("tip@x.com", 0.20)

        order_a = create_drive_thru_order_with_line(location_id, item_id, customer_id=customer["id"])
        order_b = create_drive_thru_order_with_line(location_id, item_id, customer_id=customer["id"])
        place_order(location_id, order_a["id"])
        place_order(location_id, order_b["id"])
        validate_success(api.authorize_payment(location_id, order_a["id"], MANAGER), 200)
        validate_success(api.authorize_payment(location_id, order_b["id"], MANAGER), 200)

        captured_a = validate_success(
            api.capture_payment(location_id, order_a["id"], {"tip_cents": 100}, MANAGER), 200
        )
        captured_b = validate_success(
            api.capture_payment(location_id, order_b["id"], {}, MANAGER), 200
        )
        assert captured_a["tip_cents"] == 100
        assert captured_a["total_tendered_cents"] == 1000 + 100
        assert captured_b["tip_cents"] == 200
        assert captured_b["total_tendered_cents"] == 1000 + 200
        assert captured_a["total_tendered_cents"] != captured_b["total_tendered_cents"]

    def test_tip_resolution_zero_when_no_explicit_and_no_default(self, api):
        """PRD: "an explicit `tip_cents` in the request wins outright;
        otherwise, when the order has a customer whose
        `stored_tip_default_pct` ... is greater than zero, the tip is
        `total_cents` multiplied by that percentage, rounded half-up to the
        cent; otherwise the tip is zero."

        A customer with stored_tip_default_pct 0 and no explicit tip captures
        with tip_cents 0 and tenders exactly total_cents.

        Design: Difficulty/dual_variant_calc/tip_resolution_default_pct_vs_explicit_tip_diverge
        """
        set_clock(TEST_DEFAULTS["CLOCK_0800_LOCAL"])
        ctx = setup_drive_thru_location(code="DIFF-TIP2", target_seconds=300, item_price=1000)
        location_id = ctx["location"]["id"]
        customer = _create_customer("zero@x.com", 0)

        order = create_drive_thru_order_with_line(
            location_id, ctx["item"]["id"], customer_id=customer["id"]
        )
        place_order(location_id, order["id"])
        captured = authorize_and_capture(location_id, order["id"])
        assert captured["tip_cents"] == 0
        assert captured["total_tendered_cents"] == captured["total_cents"] == 1000


class TestParallelPaymentAndFulfillmentAxes:
    def test_fulfillment_advances_while_payment_stays_unpaid(self, api):
        """PRD: "Payment is an axis independent of fulfillment: every order
        carries a `payment_status` of `UNPAID`, `AUTHORIZED`, `CAPTURED`,
        `VOIDED`, or `REFUNDED`, evolving alongside — never inside — the
        fulfillment states."

        An order reaches READY while payment_status is still UNPAID; the axes
        move independently.

        Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_axes
        """
        from test_helpers import setup_ready_order_on_stall

        ctx = setup_ready_order_on_stall(code="DIFF-AXES1", item_price=500)
        order = validate_success(
            api.get_order(ctx["location"]["id"], ctx["order"]["id"], MANAGER), 200
        )
        assert order["status"] == "READY"
        assert order["payment_status"] == "UNPAID"

    def test_capture_at_ready_does_not_move_fulfillment(self, api):
        """PRD: "Payment is an axis independent of fulfillment: every order
        carries a `payment_status` of `UNPAID`, `AUTHORIZED`, `CAPTURED`,
        `VOIDED`, or `REFUNDED`, evolving alongside — never inside — the
        fulfillment states."

        Capturing payment at READY moves only the payment axis: the order is
        still READY, payment_status CAPTURED, and the 500c order with no tip
        tenders exactly 500c.

        Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment_axes
        """
        from test_helpers import setup_ready_order_on_stall

        ctx = setup_ready_order_on_stall(code="DIFF-AXES2", item_price=500)
        captured = authorize_and_capture(ctx["location"]["id"], ctx["order"]["id"])
        assert captured["payment_status"] == "CAPTURED"
        assert captured["status"] == "READY"
        assert captured["tip_cents"] == 0
        assert captured["total_tendered_cents"] == 500


class TestCaptureImmediateConsistency:
    def test_capture_immediately_reflects_wallet_and_tip(self, api):
        """PRD: "the tender draws on the customer's `wallet_credit_cents`
        first, debiting up to the wallet balance against the tendered amount
        and charging any remainder to the card; the wallet debit is immediate
        at capture."

        A customer with a 300c wallet captures a 500c drive-thru order: the
        capture response itself reports CAPTURED with total_tendered_cents
        500, and the wallet is already 0 on the immediate read.

        Design: Corner/consistency_model/capture_immediately_reflects_wallet_and_tip
        """
        set_clock(TEST_DEFAULTS["CLOCK_0800_LOCAL"])
        ctx = setup_drive_thru_location(code="CRN-CONS", target_seconds=300, item_price=500)
        location_id = ctx["location"]["id"]
        customer = _create_customer("w@x.com", 0)
        validate_success(
            api.adjust_wallet(customer["id"], {"delta_cents": 300, "reason": "seed"}, MANAGER),
            200,
        )

        order = create_drive_thru_order_with_line(
            location_id, ctx["item"]["id"], customer_id=customer["id"]
        )
        place_order(location_id, order["id"])
        validate_success(api.authorize_payment(location_id, order["id"], MANAGER), 200)
        captured = validate_success(
            api.capture_payment(location_id, order["id"], {}, MANAGER), 200
        )
        assert captured["payment_status"] == "CAPTURED"
        assert captured["total_tendered_cents"] == 500

        customer_after = validate_success(api.get_customer(customer["id"], MANAGER), 200)
        assert customer_after["wallet_credit_cents"] == 0, (
            f"300c wallet debited against the 500c tender must leave 0, "
            f"got {customer_after['wallet_credit_cents']}"
        )

    def test_capture_wallet_debit_capped_at_tender(self, api):
        """PRD: "the tender draws on the customer's `wallet_credit_cents`
        first, debiting up to the wallet balance against the tendered amount
        and charging any remainder to the card; the wallet debit is immediate
        at capture."

        A 1000c wallet against a 500c tender leaves 500c immediately after
        capture.

        Design: Corner/consistency_model/capture_immediately_reflects_wallet_and_tip
        """
        set_clock(TEST_DEFAULTS["CLOCK_0800_LOCAL"])
        ctx = setup_drive_thru_location(code="CRN-CONS2", target_seconds=300, item_price=500)
        location_id = ctx["location"]["id"]
        customer = _create_customer("w2@x.com", 0)
        validate_success(
            api.adjust_wallet(customer["id"], {"delta_cents": 1000, "reason": "seed"}, MANAGER),
            200,
        )

        order = create_drive_thru_order_with_line(
            location_id, ctx["item"]["id"], customer_id=customer["id"]
        )
        place_order(location_id, order["id"])
        validate_success(api.authorize_payment(location_id, order["id"], MANAGER), 200)
        captured = validate_success(
            api.capture_payment(location_id, order["id"], {}, MANAGER), 200
        )
        assert captured["payment_status"] == "CAPTURED"
        assert captured["total_tendered_cents"] == 500

        customer_after = validate_success(api.get_customer(customer["id"], MANAGER), 200)
        assert customer_after["wallet_credit_cents"] == 500

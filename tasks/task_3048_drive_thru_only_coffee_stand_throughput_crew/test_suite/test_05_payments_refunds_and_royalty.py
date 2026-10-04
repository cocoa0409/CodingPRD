"""Payments: authorize/decline, capture sequencing, refund governance with
segregation of duties, refund caps, and the monthly royalty statement."""
from test_helpers import (
    ApiErrorId,
    PA,
    RM,
    add_recipe,
    authorize_order,
    create_loyalty_account,
    list_items_of_order,
    make_crew_member_headers,
    make_shift_lead_headers,
    make_stand_operator_headers,
    place_window_order,
    serve_window_order,
    setup_open_stand_with_menu,
    stand_version,
    validate_error,
    validate_paginated,
    validate_success,
)


def _captured_payment(api, ctx, price_cents, name="Keg", account=None):
    """Create + authorize + call + capture a single-item window order of the
    given price. Returns (order, payment)."""
    recipe, dist = add_recipe(
        ctx,
        name=name,
        base_price_cents=price_cents,
        base_build_seconds=120,
        temperature_class="HOT",
    )
    order = place_window_order(
        ctx, recipe["id"], lane_code="A", loyalty_account_id=account["id"] if account else None
    )
    payment = authorize_order(ctx, order["id"])
    lead = make_shift_lead_headers(ctx["lead"]["id"])
    validate_success(api.call_to_window(order["id"], lead), 200)
    payment = validate_success(api.capture_payment(payment["id"], lead), 200)
    return order, payment


class TestValidationPriority:
    def test_state_error_beats_fiscal_error_on_authorize_of_abandoned_order(self, api):
        """PRD §2.9: "When a single request could trip several rules, the system
        evaluates checks in a fixed priority order so that the surfaced error is
        deterministic: ... 6. **State preconditions** ... 12. **Fiscal rules** —
        declines, refund caps, and segregation of duties (`ERR_PAYMENT_DECLINED`,
        `ERR_REFUND_EXCEEDS_CAPTURED`, `ERR_SEGREGATION_OF_DUTIES`)."

        Design: Difficulty/priority_pair_validation_conflict/state_error_beats_fiscal_error_on_authorize_of_abandoned_order
        """
        ctx = setup_open_stand_with_menu()
        order = place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        lead = make_shift_lead_headers(ctx["lead"]["id"])
        validate_success(api.abandon_order(order["id"], lead), 200)
        resp = api.authorize_payment(
            order["id"], {"card_token": "DECLINE"},
            make_crew_member_headers(ctx["taker"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_INVALID_STATE, 409)

    def test_state_precondition_category_outranks_decline_on_abandoned_order(self, api):
        """PRD §2.9: "6. **State preconditions** — the target resource's own
        transition guards (`ERR_STAND_INVALID_TRANSITION`, `ERR_ORDER_INVALID_STATE`,
        `ERR_PAYMENT_INVALID_STATE`, ...)"

        Design: Difficulty/priority_pair_validation_conflict/state_error_beats_fiscal_error_on_authorize_of_abandoned_order
        """
        ctx = setup_open_stand_with_menu()
        order = place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        lead = make_shift_lead_headers(ctx["lead"]["id"])
        validate_success(api.abandon_order(order["id"], lead), 200)
        resp = api.authorize_payment(
            order["id"], {"card_token": "DECLINE"},
            make_crew_member_headers(ctx["taker"]["id"]),
        )
        assert resp.status_code == 409, (
            f"state error must surface as 409, not 402; got {resp.status_code}"
        )
        assert resp.json()["data"]["error_id"] == "ERR_ORDER_INVALID_STATE"


class TestPaymentDecline:
    def test_payment_decline_maps_to_402_fiscal(self, api):
        """PRD §3.7: "The request carries a `card_token`; a token of `DECLINE`
        simulates a card decline and fails with `ERR_PAYMENT_DECLINED`."

        Design: Corner/validations/payment_decline_maps_to_402_fiscal
        """
        ctx = setup_open_stand_with_menu()
        order = place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        resp = api.authorize_payment(
            order["id"], {"card_token": "DECLINE"},
            make_crew_member_headers(ctx["taker"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_DECLINED, 402)
        payments, _ = validate_paginated(
            api.list_payments(
                make_crew_member_headers(ctx["taker"]["id"]),
                params={"order_id": order["id"]},
            )
        )
        assert payments == [], "no Payment row may be created by a decline"
        order_after = validate_success(
            api.get_order(order["id"], make_crew_member_headers(ctx["taker"]["id"])), 200
        )
        assert order_after["payment_status"] == "UNPAID"

    def test_declined_authorize_leaves_order_unpaid_and_retryable(self, api):
        """PRD §3.7: "a token of `DECLINE` simulates a card decline and fails
        with `ERR_PAYMENT_DECLINED`."

        Design: Corner/validations/payment_decline_maps_to_402_fiscal
        """
        ctx = setup_open_stand_with_menu()
        order = place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        resp = api.authorize_payment(
            order["id"], {"card_token": "DECLINE"},
            make_crew_member_headers(ctx["taker"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_DECLINED, 402)
        payment = authorize_order(ctx, order["id"])
        assert payment["status"] == "AUTHORIZED"
        assert payment["captured_cents"] == 0
        assert payment["refunded_cents"] == 0


class TestCaptureSequencing:
    def test_capture_out_of_sequence_blocked_by_earlier_unpaid_car(self, api):
        """PRD §3.7: "Capture is **sequenced within each lane**: it is rejected
        with `ERR_CAPTURE_OUT_OF_SEQUENCE` if any other order in the same lane
        with a smaller `lane_seq` is neither `SERVED` nor `ABANDONED` while its
        `payment_status` is still `UNPAID` or `AUTHORIZED` — the car ahead pays
        first."

        Design: Corner/validations/capture_out_of_sequence_blocked_by_earlier_unpaid_car
        """
        ctx = setup_open_stand_with_menu()
        order1 = place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        order2 = place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        payment2 = authorize_order(ctx, order2["id"])
        lead = make_shift_lead_headers(ctx["lead"]["id"])
        resp = api.capture_payment(payment2["id"], lead)
        validate_error(resp, ApiErrorId.ERR_CAPTURE_OUT_OF_SEQUENCE, 409)
        payment2_after = validate_success(api.get_payment(payment2["id"], lead), 200)
        assert payment2_after["status"] == "AUTHORIZED"

    def test_capture_succeeds_in_lane_sequence(self, api):
        """PRD §3.7: "Capture sets `captured_cents` equal to `authorized_cents`,
        stamps `captured_at` with the current logical clock (this timestamp later
        drives royalty month attribution), moves the order's `payment_status` to
        `CAPTURED`, and posts loyalty accrual per §3.4."

        Design: Corner/validations/capture_out_of_sequence_blocked_by_earlier_unpaid_car
        """
        ctx = setup_open_stand_with_menu()
        order1 = place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        order2 = place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        payment1 = authorize_order(ctx, order1["id"])
        payment2 = authorize_order(ctx, order2["id"])
        lead = make_shift_lead_headers(ctx["lead"]["id"])
        captured1 = validate_success(api.capture_payment(payment1["id"], lead), 200)
        assert captured1["status"] == "CAPTURED"
        assert captured1["captured_cents"] == captured1["authorized_cents"]
        assert captured1["captured_at"] is not None
        captured2 = validate_success(api.capture_payment(payment2["id"], lead), 200)
        assert captured2["status"] == "CAPTURED"


class TestRefundCaps:
    def test_refund_beyond_captured_rejected(self, api):
        """PRD §3.7: "cumulative refunds may never exceed the captured amount, so
        a request where `refunded_cents` plus `amount_cents` would exceed
        `captured_cents` is rejected with `ERR_REFUND_EXCEEDS_CAPTURED`."
        PRD §3.7: "the payment becomes `REFUNDED` only when the cumulative
        refunded amount equals the captured amount — a partial small refund
        leaves the payment `CAPTURED` with no state change."

        Design: Corner/validations/refund_beyond_captured_rejected
        """
        ctx = setup_open_stand_with_menu()
        order, payment = _captured_payment(api, ctx, 450, name="Keg 450")
        lead = make_shift_lead_headers(ctx["lead"]["id"])

        small = validate_success(
            api.refund_payment(payment["id"], {"amount_cents": 200}, lead), 200
        )
        assert small["status"] == "CAPTURED", (
            "a partial auto-approved refund leaves the payment CAPTURED"
        )
        assert small["refunded_cents"] == 200

        too_much = api.refund_payment(payment["id"], {"amount_cents": 300}, lead)
        validate_error(too_much, ApiErrorId.ERR_REFUND_EXCEEDS_CAPTURED, 422)

        final = validate_success(
            api.refund_payment(payment["id"], {"amount_cents": 250}, lead), 200
        )
        assert final["refunded_cents"] == 450
        assert final["status"] == "REFUNDED", (
            "refunded == captured flips the payment to REFUNDED"
        )

    def test_exact_remainder_refund_completes_capture(self, api):
        """PRD §3.7: "An amount of 2000 cents or less is auto-approved: it is
        applied immediately, `refunded_cents` increases by the amount, loyalty
        points are reversed per §3.4, and the payment becomes `REFUNDED` only
        when the cumulative refunded amount equals the captured amount"

        Design: Corner/validations/refund_beyond_captured_rejected
        """
        ctx = setup_open_stand_with_menu()
        order, payment = _captured_payment(api, ctx, 450, name="Keg 450")
        lead = make_shift_lead_headers(ctx["lead"]["id"])
        validate_success(api.refund_payment(payment["id"], {"amount_cents": 200}, lead), 200)
        final = validate_success(
            api.refund_payment(payment["id"], {"amount_cents": 250}, lead), 200
        )
        assert final["status"] == "REFUNDED"
        assert final["refunded_cents"] == 450


class TestRefundSegregationOfDuties:
    def test_refund_decision_enforces_segregation_of_duties(self, api):
        """PRD §3.7: "The decision belongs to a `StandOperator`, who submits a
        `decision` of `APPROVE` or `REJECT` — and never to the initiator: a
        decider whose `X-User-ID` equals `refund_initiated_by` is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.7: "rejecting discards the pending amount, records
        `refund_decided_by`, and returns the payment to `CAPTURED`."

        Design: Corner/rbac/refund_decision_enforces_segregation_of_duties
        """
        ctx = setup_open_stand_with_menu()
        order, payment = _captured_payment(api, ctx, 5000, name="Keg 5000")
        lead = make_shift_lead_headers(ctx["lead"]["id"])
        pending = validate_success(
            api.refund_payment(payment["id"], {"amount_cents": 5000}, lead), 200
        )
        assert pending["status"] == "REFUND_PENDING"
        assert pending["refund_initiated_by"] == ctx["lead"]["id"]

        # Decider identity == initiator identity, even in the StandOperator role.
        self_decide = api.decide_refund(
            payment["id"], {"decision": "APPROVE"},
            make_stand_operator_headers(ctx["lead"]["id"]),
        )
        validate_error(self_decide, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

        rejected = validate_success(
            api.decide_refund(
                payment["id"], {"decision": "REJECT"},
                make_stand_operator_headers(ctx["op"]["id"]),
            ),
            200,
        )
        assert rejected["status"] == "CAPTURED"
        assert rejected["refunded_cents"] == 0
        assert rejected["refund_decided_by"] == ctx["op"]["id"]

    def test_refund_approve_by_distinct_operator_applies_refund(self, api):
        """PRD §3.7: "Approving applies the pending amount to `refunded_cents`,
        reverses loyalty points for it, records `refund_decided_by`, and moves
        the payment to `REFUNDED` when the refund completes the capture"

        Design: Corner/rbac/refund_decision_enforces_segregation_of_duties
        """
        ctx = setup_open_stand_with_menu()
        order, payment = _captured_payment(api, ctx, 5000, name="Keg 5000")
        lead = make_shift_lead_headers(ctx["lead"]["id"])
        pending = validate_success(
            api.refund_payment(payment["id"], {"amount_cents": 5000}, lead), 200
        )
        assert pending["status"] == "REFUND_PENDING"
        approved = validate_success(
            api.decide_refund(
                payment["id"], {"decision": "APPROVE"},
                make_stand_operator_headers(ctx["op"]["id"]),
            ),
            200,
        )
        assert approved["status"] == "REFUNDED"
        assert approved["refunded_cents"] == 5000
        assert approved["refund_decided_by"] == ctx["op"]["id"]


class TestCaptureRefundInvariant:
    def test_capture_then_full_refund_conserves_net_sales_and_points(self, api):
        """PRD §3.4: "When a refund is applied (whether auto-approved or
        operator-approved), points are reversed at the same rate for the refunded
        amount, with the balance floored at zero."
        PRD §3.7: "First, `gross_cents` is the sum, over all payments at the
        stand whose `captured_at` falls within that calendar month (from the
        first instant of the month, inclusive, to the first instant of the
        following month, exclusive), of each payment's `captured_cents` minus its
        `refunded_cents`."

        Design: Difficulty/compensating_invariant/capture_then_full_refund_conserves_net_sales_and_points
        """
        ctx = setup_open_stand_with_menu()
        account = create_loyalty_account(ctx["stand"]["id"], full_name="Refundable Rita")
        order, payment = _captured_payment(api, ctx, 5000, name="Keg 5000", account=account)
        lead = make_shift_lead_headers(ctx["lead"]["id"])

        mid_account = validate_success(
            api.get_loyalty_account(account["id"], ctx["operator_headers"]), 200
        )
        assert mid_account["points"] == 50, (
            f"capture of 5000 cents earns floor(5000/100)=50, got {mid_account['points']}"
        )

        pending = validate_success(
            api.refund_payment(payment["id"], {"amount_cents": 5000}, lead), 200
        )
        assert pending["status"] == "REFUND_PENDING", (
            "a refund above 2000 cents routes through REFUND_PENDING"
        )
        final = validate_success(
            api.decide_refund(
                payment["id"], {"decision": "APPROVE"},
                make_stand_operator_headers(ctx["op"]["id"]),
            ),
            200,
        )
        assert final["status"] == "REFUNDED"
        assert final["captured_cents"] == 5000
        assert final["refunded_cents"] == 5000

        account_after = validate_success(
            api.get_loyalty_account(account["id"], ctx["operator_headers"]), 200
        )
        assert account_after["points"] == 0, (
            f"50 earned then 50 reversed must return to 0, got {account_after['points']}"
        )

        statement = validate_success(
            api.get_royalty_statement(
                ctx["stand"]["id"], "2026-09", ctx["operator_headers"]
            ),
            200,
        )
        assert statement["gross_cents"] == 0, (
            f"5000 captured - 5000 refunded nets to 0, got {statement['gross_cents']}"
        )
        assert statement["royalty_cents"] == 0

    def test_capture_accrues_points_and_full_refund_reverses_them(self, api):
        """PRD §3.4: "When a payment is captured for an order carrying a
        `loyalty_account_id`, the account earns one point per whole dollar
        captured — the captured cents divided by one hundred, rounded down — and
        `lifetime_captured_cents` grows by the captured amount."

        Design: Difficulty/compensating_invariant/capture_then_full_refund_conserves_net_sales_and_points
        """
        ctx = setup_open_stand_with_menu()
        account = create_loyalty_account(ctx["stand"]["id"], full_name="Refundable Rita")
        order, payment = _captured_payment(api, ctx, 5000, name="Keg 5000", account=account)
        lead = make_shift_lead_headers(ctx["lead"]["id"])
        account_mid = validate_success(
            api.get_loyalty_account(account["id"], ctx["operator_headers"]), 200
        )
        assert account_mid["lifetime_captured_cents"] == 5000

        validate_success(api.refund_payment(payment["id"], {"amount_cents": 5000}, lead), 200)
        validate_success(
            api.decide_refund(
                payment["id"], {"decision": "APPROVE"},
                make_stand_operator_headers(ctx["op"]["id"]),
            ),
            200,
        )
        account_after = validate_success(
            api.get_loyalty_account(account["id"], ctx["operator_headers"]), 200
        )
        assert account_after["points"] == 0


class TestRoyaltyStatement:
    def test_royalty_statement_pins_gross_then_brand_fund_then_net_then_tiered_rate(
        self, api
    ):
        """PRD §3.7: "First, `gross_cents` is the sum, over all payments at the
        stand whose `captured_at` falls within that calendar month (from the
        first instant of the month, inclusive, to the first instant of the
        following month, exclusive), of each payment's `captured_cents` minus its
        `refunded_cents`. Second, `brand_fund_cents` is two percent of the gross,
        rounded half-up to a whole cent. Third, `net_cents` is the gross minus
        the brand-fund deduction. Fourth, the `royalty_rate` is keyed on the
        gross with inclusive lower bounds: six percent when the gross reaches
        5,000,000 cents, five percent when it reaches 1,000,000 cents, and four
        percent below that. Finally, `royalty_cents` is the net multiplied by
        that rate, rounded half-up to a whole cent."

        Design: Difficulty/combinatorial_formula/royalty_statement_pins_gross_then_brand_fund_then_net_then_tiered_rate
        """
        ctx = setup_open_stand_with_menu()
        order, payment = _captured_payment(api, ctx, 1_000_000, name="Catering Keg")
        statement = validate_success(
            api.get_royalty_statement(
                ctx["stand"]["id"], "2026-09", ctx["operator_headers"]
            ),
            200,
        )
        assert statement["gross_cents"] == 1_000_000
        assert statement["brand_fund_cents"] == 20_000, (
            f"round_half_up(1000000 * 0.02) = 20000, got {statement['brand_fund_cents']}"
        )
        assert statement["net_cents"] == 980_000
        assert statement["royalty_rate"] == 0.05, (
            f"gross >= 1,000,000 (inclusive) selects 0.05, got {statement['royalty_rate']}"
        )
        assert statement["royalty_cents"] == 49_000, (
            f"round_half_up(980000 * 0.05) = 49000, got {statement['royalty_cents']}"
        )
        assert statement["month"] == "2026-09"

    def test_royalty_statement_tier_boundary_uses_gross_not_net(self, api):
        """PRD §3.7: "Fourth, the `royalty_rate` is keyed on the gross with
        inclusive lower bounds: six percent when the gross reaches 5,000,000
        cents, five percent when it reaches 1,000,000 cents, and four percent
        below that."

        Design: Difficulty/combinatorial_formula/royalty_statement_pins_gross_then_brand_fund_then_net_then_tiered_rate
        """
        ctx = setup_open_stand_with_menu()
        _captured_payment(api, ctx, 1_000_000, name="Catering Keg")
        statement = validate_success(
            api.get_royalty_statement(
                ctx["stand"]["id"], "2026-09", ctx["operator_headers"]
            ),
            200,
        )
        # net 980000 is below the tier boundary; the tier is keyed on gross.
        assert statement["royalty_rate"] == 0.05
        assert statement["royalty_cents"] == 49_000

    def test_royalty_statement_low_tier_and_refund_netting(self, api):
        """PRD §3.7: "First, `gross_cents` is the sum, over all payments at the
        stand whose `captured_at` falls within that calendar month (from the
        first instant of the month, inclusive, to the first instant of the
        following month, exclusive), of each payment's `captured_cents` minus its
        `refunded_cents`."

        Design: Corner/calculations/royalty_statement_low_tier_and_refund_netting
        """
        ctx = setup_open_stand_with_menu()
        order, payment = _captured_payment(api, ctx, 50_000, name="Keg 500")
        lead = make_shift_lead_headers(ctx["lead"]["id"])
        pending = validate_success(
            api.refund_payment(payment["id"], {"amount_cents": 10_000}, lead), 200
        )
        assert pending["status"] == "REFUND_PENDING"
        validate_success(
            api.decide_refund(
                payment["id"], {"decision": "APPROVE"},
                make_stand_operator_headers(ctx["op"]["id"]),
            ),
            200,
        )
        statement = validate_success(
            api.get_royalty_statement(
                ctx["stand"]["id"], "2026-09", ctx["operator_headers"]
            ),
            200,
        )
        assert statement["gross_cents"] == 40_000, (
            f"50000 - 10000 refunded = 40000, got {statement['gross_cents']}"
        )
        assert statement["brand_fund_cents"] == 800
        assert statement["net_cents"] == 39_200
        assert statement["royalty_rate"] == 0.04, (
            f"gross 40000 is below the 1,000,000 tier, got {statement['royalty_rate']}"
        )
        assert statement["royalty_cents"] == 1568, (
            f"round_half_up(39200 * 0.04) = 1568, got {statement['royalty_cents']}"
        )

    def test_royalty_statement_is_computed_read_with_no_writes(self, api):
        """PRD §3.7: "The statement reports `month`, `gross_cents`,
        `brand_fund_cents`, `net_cents`, `royalty_rate`, and `royalty_cents`."

        Design: Corner/endpoints/royalty_statement_is_computed_read_with_no_writes
        """
        ctx = setup_open_stand_with_menu()
        v_before = stand_version(ctx)
        statement1 = validate_success(
            api.get_royalty_statement(ctx["stand"]["id"], "2026-09", RM), 200
        )
        statement2 = validate_success(
            api.get_royalty_statement(ctx["stand"]["id"], "2026-09", RM), 200
        )
        assert statement1 == statement2, "two identical GETs return identical bodies"
        assert statement1["gross_cents"] == 0
        assert statement1["brand_fund_cents"] == 0
        assert statement1["net_cents"] == 0
        assert statement1["royalty_rate"] == 0.04
        assert statement1["royalty_cents"] == 0
        v_after = stand_version(ctx)
        assert v_before == v_after, "a computed read must not bump Stand.version"

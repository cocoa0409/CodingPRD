"""Returns, restocking math, and member savings recognition at delivery."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_member_headers,
    setup_gallery,
    setup_member,
    setup_product,
    setup_delivered_stock_order,
    setup_delivered_custom_order,
    setup_requested_return,
    create_retail_quote,
    create_member_quote,
    add_line,
    confirm_order,
    read_order,
    set_clock,
    create_return_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ASSOCIATE = TEST_USERS["gallery_associate_headers"]
HUB = TEST_USERS["hub_operator_headers"]


class TestMemberSavings:

    def test_gross_vs_net_savings_after_delivery(self, api):
        """PRD §3.7: "For member orders this is also the moment savings are recognized — and only this moment, never at confirm: the member's `lifetime_gross_savings_cents` increases by the difference between the order's undiscounted content (the sum over its lines of `unit_list_price_cents` multiplied by `qty`) and the amount actually charged (the sum of `line_charged_cents`), and `lifetime_net_savings_cents` is recomputed as gross savings minus `fee_paid_total_cents`."

        Design: Difficulty/dual_variant_calc/member_gross_vs_net_savings
        """
        gallery = setup_gallery(name="Gallery B")
        member = setup_member(email="m1@x.com", full_name="M One", auto_renew=False)
        product = setup_product(list_price_cents=100000, line_kind="STOCK")
        headers = make_member_headers(member["id"])
        order = create_member_quote(gallery["id"], member["id"])
        add_line(order["id"], product["id"], qty=2, headers=headers)

        # Savings are not recognized at confirm.
        confirm_order(order["id"], headers=headers)
        at_confirm = get_success_data(api.get_member(member["id"], ADMIN))
        assert at_confirm["lifetime_gross_savings_cents"] == 0

        from test_helpers import deliver_order
        deliver_order(order["id"], gallery["id"], delivery_date="2026-09-05")

        member_after = get_success_data(api.get_member(member["id"], ADMIN))
        assert member_after["lifetime_gross_savings_cents"] == 50000
        assert member_after["lifetime_net_savings_cents"] == 32500
        assert member_after["fee_paid_total_cents"] == 17500

    def test_savings_not_recognized_before_delivery(self, api):
        """PRD §3.1: "Gross savings themselves accumulate only when member orders are delivered, as described in §3.7, never earlier."

        Design: Difficulty/dual_variant_calc/member_gross_vs_net_savings
        """
        gallery = setup_gallery(name="Gallery B2")
        member = setup_member(email="m1b@x.com", full_name="M One B", auto_renew=False)
        product = setup_product(list_price_cents=100000, line_kind="STOCK")
        headers = make_member_headers(member["id"])
        order = create_member_quote(gallery["id"], member["id"])
        add_line(order["id"], product["id"], qty=2, headers=headers)
        confirm_order(order["id"], headers=headers)

        member_after = get_success_data(api.get_member(member["id"], ADMIN))
        assert member_after["lifetime_gross_savings_cents"] == 0
        assert member_after["lifetime_net_savings_cents"] == -17500


class TestRestockingMath:

    def test_per_line_round_then_sum(self, api):
        """PRD §2.6: "The same per-unit-then-aggregate discipline applies to restocking fees: the fee is computed and rounded per returned line, then summed. (For contrast: two lines each charged 1003 cents carry a restocking fee of 150 + 150 = 300 cents under the pinned rule; computing fifteen percent of the 2006-cent sum and rounding once would incorrectly yield 301 cents.)"
        PRD §3.8: "On `APPROVE`, the restocking fee is computed per returned line as fifteen percent of that line's `line_charged_cents`, rounded half up to integer cents per line, and `restocking_fee_cents` is the sum of those per-line fees; `refund_cents` is the sum of the returned lines' `line_charged_cents` minus `restocking_fee_cents`."

        Design: Difficulty/combinatorial_formula/restocking_per_line_round_then_sum
        """
        setup = setup_requested_return(list_price_cents=1003, num_lines=2, qty=1)
        settled = validate_success(
            api.settle_return(setup["return"]["id"], {"decision": "APPROVE"}, ASSOCIATE)
        )
        assert settled["restocking_fee_cents"] == 300
        assert settled["refund_cents"] == 1706

    def test_single_line_restocking_fee_and_refund(self, api):
        """PRD §3.8: "On `APPROVE`, the restocking fee is computed per returned line as fifteen percent of that line's `line_charged_cents`, rounded half up to integer cents per line, and `restocking_fee_cents` is the sum of those per-line fees; `refund_cents` is the sum of the returned lines' `line_charged_cents` minus `restocking_fee_cents`."

        Design: Difficulty/combinatorial_formula/restocking_per_line_round_then_sum
        """
        setup = setup_requested_return(list_price_cents=50000, num_lines=1, qty=1)
        settled = validate_success(
            api.settle_return(setup["return"]["id"], {"decision": "APPROVE"}, ASSOCIATE)
        )
        assert settled["restocking_fee_cents"] == 7500
        assert settled["refund_cents"] == 42500
        assert settled["status"] == "SETTLED"


class TestReturnGates:

    def test_return_gated_by_completed_delivery(self, api):
        """PRD §3.8: "The request is valid only when the order is `DELIVERED` (otherwise `ERR_INVALID_STATE`)"
        PRD §3.7: "The first appointment of an order to reach `COMPLETED` delivers the order: the order moves from `READY_FOR_DELIVERY` to its terminal `DELIVERED` state"

        Design: Difficulty/cross_entity_state_dependency/return_gated_by_completed_delivery
        """
        gallery = setup_gallery(name="Gallery M")
        member = setup_member(email="m9@x.com", full_name="M Nine")
        product = setup_product(list_price_cents=50000, line_kind="STOCK")
        headers = make_member_headers(member["id"])
        order = create_member_quote(gallery["id"], member["id"])
        line = add_line(order["id"], product["id"], qty=1, headers=headers)
        confirm_order(order["id"], headers=headers)
        assert read_order(order["id"])["status"] == "READY_FOR_DELIVERY"

        resp = api.create_return(
            create_return_payload(order["id"], [line["id"]]), headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_return_of_custom_line_rejected(self, api):
        """PRD §3.8: "when every named line is a `STOCK` line of that order (any custom line in the list is rejected with `ERR_CUSTOM_NON_RETURNABLE`, HTTP 422)."

        Design: Corner/validations/return_of_custom_line_rejected
        """
        setup = setup_delivered_custom_order(list_price_cents=120000)
        order = setup["order"]
        line = setup["lines"][0]
        assert order["status"] == "DELIVERED"

        resp = api.create_return(
            create_return_payload(order["id"], [line["id"]]), ASSOCIATE
        )
        validate_error(resp, ApiErrorId.ERR_CUSTOM_NON_RETURNABLE.value)

    def test_return_after_window_rejected(self, api):
        """PRD §3.8: "when the clock is at or before 30 days after the order's `delivered_at` — later requests are rejected with `ERR_RETURN_WINDOW_CLOSED` (HTTP 422)"

        Design: Corner/validations/return_after_window_rejected
        """
        setup = setup_delivered_stock_order(list_price_cents=10000,
                                            delivery_date="2026-09-05")
        order = setup["order"]
        line = setup["line"]
        assert order["status"] == "DELIVERED"

        set_clock("2026-10-06T00:00:00Z")
        resp = api.create_return(
            create_return_payload(order["id"], [line["id"]]), ASSOCIATE
        )
        validate_error(resp, ApiErrorId.ERR_RETURN_WINDOW_CLOSED.value)


class TestReturnSettlement:

    def test_settled_return_rejects_second_settle(self, api):
        """PRD §3.8: "Both `SETTLED` and `REJECTED` are terminal"
        PRD §3.8: "On `APPROVE`, the restocking fee is computed per returned line as fifteen percent of that line's `line_charged_cents`, rounded half up to integer cents per line, and `restocking_fee_cents` is the sum of those per-line fees; `refund_cents` is the sum of the returned lines' `line_charged_cents` minus `restocking_fee_cents`."

        Design: Corner/state_machines/settled_return_rejects_second_settle
        """
        setup = setup_requested_return(list_price_cents=50000, num_lines=1, qty=1)
        first = validate_success(
            api.settle_return(setup["return"]["id"], {"decision": "APPROVE"}, ASSOCIATE)
        )
        assert first["restocking_fee_cents"] == 7500
        assert first["refund_cents"] == 42500

        resp = api.settle_return(
            setup["return"]["id"], {"decision": "REJECT", "reason": "changed mind"},
            ASSOCIATE,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

        after = get_success_data(api.get_return(setup["return"]["id"], ADMIN))
        assert after["restocking_fee_cents"] == 7500
        assert after["refund_cents"] == 42500
        assert after["status"] == "SETTLED"

"""Digital orders: pinned totals, parallel payment/fulfillment tracks, recalls."""
from test_helpers import (
    ApiErrorId,
    add_product,
    assert_digital_order,
    create_active_recall,
    create_digital_order,
    create_troop_with_account,
    get_account,
    get_digital_order,
    make_council_admin_headers,
    setup_selling_season,
    validate_error,
    validate_success,
)


class TestDigitalOrderTotal:
    def test_digital_order_total_mode_a_nonlinear_donation_blend(self, api):
        """PRD §3.6: "The donation portion prices each donated package at the
        season's average unit price: the sum of `unit_price_cents` over all of
        the season's products, divided by the product count, rounded half-up to
        a whole cent, and only then multiplied by `donation_units`."

        Design: Difficulty/combinatorial_formula/digital_order_total_mode_a_nonlinear_donation_blend
        """
        admin = make_council_admin_headers()
        ctx = setup_selling_season(
            purchase_qty=1000, confirm_qty=800, admin=admin, unit_price_cents=600,
        )
        season, product_tm = ctx["season"], ctx["product"]
        add_product(
            season["id"], admin=admin, variety_code="SD", name="Samoas",
            unit_price_cents=700, troop_proceeds_cents=110, packages_per_case=1,
        )
        order = create_digital_order(
            season["id"], ctx["troop"],
            [{"product_id": product_tm["id"], "package_qty": 12}],
            leader=ctx["leader"], donation_units=3,
        )
        assert_digital_order(order)
        # items: 12*600 = 7200; donation avg round_half_up((600+700)/2) = 650;
        # 3*650 = 1950; total = 9150.
        assert order["total_amount_cents"] == 9150


class TestParallelTracks:
    def test_digital_order_parallel_payment_and_fulfillment_dims(self, api):
        """PRD §3.6: "Refunding is a `CouncilAdmin` act requiring payment
        `PAID` and fulfillment anything other than `DELIVERED`; refunding after
        delivery is refused with `ERR_ALREADY_DELIVERED`."

        Design: Difficulty/non_linear_state_machine/digital_order_parallel_payment_and_fulfillment_dims
        """
        admin = make_council_admin_headers()
        ctx = setup_selling_season(
            purchase_qty=1000, confirm_qty=800, admin=admin,
        )
        season, product = ctx["season"], ctx["product"]
        order = create_digital_order(
            season["id"], ctx["troop"],
            [{"product_id": product["id"], "package_qty": 12}],
            leader=ctx["leader"],
        )
        validate_success(api.record_payment(order["id"], ctx["leader"]))
        validate_success(api.mark_delivered(order["id"], ctx["leader"]))
        resp = api.refund_digital_order(order["id"], admin)
        validate_error(resp, ApiErrorId.ERR_ALREADY_DELIVERED, 422)
        after = get_digital_order(order["id"], admin=admin)
        assert after["payment_status"] == "PAID"
        assert after["fulfillment_status"] == "DELIVERED"


class TestPaymentRefundConservation:
    def test_troop_account_money_conservation_payment_refund(self, api):
        """PRD §3.6: "it moves payment to `PAID`, charges the full
        `total_amount_cents` to the troop account's `balance_cents` as customer
        remittance, and accrues the items' per-package proceeds into
        `proceeds_accrued_cents`." PRD §3.6: "The refund credits
        `total_amount_cents` back off the troop account's `balance_cents` and
        claws the accrued proceeds back out of `proceeds_accrued_cents`."

        Design: Difficulty/compensating_invariant/troop_account_money_conservation_payment_refund
        """
        admin = make_council_admin_headers()
        ctx = setup_selling_season(
            purchase_qty=100, confirm_qty=80, admin=admin,
        )
        season, product, account = ctx["season"], ctx["product"], ctx["account"]
        before = get_account(account["id"], admin=admin)
        assert before["balance_cents"] == 48000
        assert before["proceeds_accrued_cents"] == 8000
        order = create_digital_order(
            season["id"], ctx["troop"],
            [{"product_id": product["id"], "package_qty": 12}],
            leader=ctx["leader"],
        )
        validate_success(api.record_payment(order["id"], ctx["leader"]))
        refunded = validate_success(api.refund_digital_order(order["id"], admin))
        assert refunded["payment_status"] == "REFUNDED"
        assert refunded["fulfillment_status"] == "OPEN"
        after = get_account(account["id"], admin=admin)
        assert after["balance_cents"] == 48000
        assert after["proceeds_accrued_cents"] == 8000


class TestDigitalOrderGates:
    def test_mark_uncollected_shipped_rejected(self, api):
        """PRD §3.6: "attempting that on a `SHIPPED` order fails with
        `ERR_FULFILLMENT_TYPE_MISMATCH`, since shipped orders cannot be
        uncollected."

        Design: Corner/validations/mark_uncollected_shipped_rejected
        """
        admin = make_council_admin_headers()
        ctx = setup_selling_season(admin=admin)
        season, product = ctx["season"], ctx["product"]
        order = create_digital_order(
            season["id"], ctx["troop"],
            [{"product_id": product["id"], "package_qty": 2}],
            leader=ctx["leader"], fulfillment_type="SHIPPED",
        )
        resp = api.mark_uncollected(order["id"], {}, ctx["leader"])
        validate_error(resp, ApiErrorId.ERR_FULFILLMENT_TYPE_MISMATCH, 422)

    def test_deliver_unpaid_rejected(self, api):
        """PRD §3.6: "Delivery requires the payment to be `PAID` — delivering
        an unpaid order fails with `ERR_UNPAID_DELIVERY`"."

        Design: Corner/validations/deliver_unpaid_rejected
        """
        admin = make_council_admin_headers()
        ctx = setup_selling_season(admin=admin)
        season, product = ctx["season"], ctx["product"]
        order = create_digital_order(
            season["id"], ctx["troop"],
            [{"product_id": product["id"], "package_qty": 2}],
            leader=ctx["leader"],
        )
        resp = api.mark_delivered(order["id"], ctx["leader"])
        validate_error(resp, ApiErrorId.ERR_UNPAID_DELIVERY, 422)

    def test_recall_blocks_digital_deliver(self, api):
        """PRD §3.8: "from its `effective_at` forward the recall blocks three
        operations for that product: order confirmation, transfer completion,
        and digital-order delivery, each failing with `ERR_RECALLED_PRODUCT`."

        Design: Corner/validations/recall_blocks_digital_deliver
        """
        admin = make_council_admin_headers()
        ctx = setup_selling_season(admin=admin)
        season, product = ctx["season"], ctx["product"]
        order = create_digital_order(
            season["id"], ctx["troop"],
            [{"product_id": product["id"], "package_qty": 2}],
            leader=ctx["leader"],
        )
        validate_success(api.record_payment(order["id"], ctx["leader"]))
        create_active_recall(
            season["id"], product["id"], admin=admin,
            effective_at="2027-01-09T00:00:00Z",
        )
        resp = api.mark_delivered(order["id"], ctx["leader"])
        validate_error(resp, ApiErrorId.ERR_RECALLED_PRODUCT, 422)
        after = get_digital_order(order["id"], admin=admin)
        assert after["fulfillment_status"] == "OPEN"

    def test_recall_lift_releases_blocks(self, api):
        """PRD §3.8: "Lifting an `ACTIVE` recall releases all three gates."

        Design: Corner/validations/recall_lift_releases_blocks
        """
        admin = make_council_admin_headers()
        ctx = setup_selling_season(admin=admin)
        season, product = ctx["season"], ctx["product"]
        order = create_digital_order(
            season["id"], ctx["troop"],
            [{"product_id": product["id"], "package_qty": 2}],
            leader=ctx["leader"],
        )
        validate_success(api.record_payment(order["id"], ctx["leader"]))
        recall = create_active_recall(
            season["id"], product["id"], admin=admin,
            effective_at="2027-01-09T00:00:00Z",
        )
        validate_success(api.lift_recall(season["id"], recall["id"], admin))
        delivered = validate_success(api.mark_delivered(order["id"], ctx["leader"]))
        assert delivered["fulfillment_status"] == "DELIVERED"

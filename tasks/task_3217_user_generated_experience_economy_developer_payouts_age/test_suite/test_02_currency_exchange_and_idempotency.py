"""Tiered currency exchange, refund compensating invariants, and order
idempotency (PRD §2.9, §3.3)."""
from test_helpers import (
    ApiErrorId,
    create_currency_purchase_order_payload,
    create_purchase_order_payload,
    create_on_sale_item,
    create_user,
    expected_credited_robux,
    fund_user,
    get_user,
    make_creator_headers,
    set_clock,
    validate_error,
    validate_success,
)


class TestTieredExchange:
    def test_currency_exchange_base_vs_promotional_bonus(self, api):
        """PRD §3.3: "The first 999 cents (from zero) convert at 0.80 Robux per cent;
        cents from 1,000 through 4,999 convert at 0.90 per cent; cents from 5,000
        through 19,999 convert at 1.00 per cent; and every cent from 20,000 upward
        converts at 1.10 per cent."
        PRD §3.3: "The Robux contributed by each tier are summed, and only the final
        aggregate is rounded — half-up to a whole number of Robux; per-tier rounding is
        forbidden because it drifts the total."

        Design: Difficulty/dual_variant_calc/currency_exchange_base_vs_promotional_bonus
        """
        set_clock()
        buyer = create_user(username="buyer_a", email="buyer_a@x.com", date_of_birth="1990-01-01")
        headers = make_creator_headers(buyer["id"])

        # 5500 cents: 999*0.80 + 4000*0.90 + 501*1.00 = 799.20 + 3600.00 + 501.00
        # = 4900.20 -> round half up once -> 4900 Robux.
        expected = expected_credited_robux(5500)
        assert expected == 4900, f"helper drifted: {expected}"

        o1 = validate_success(
            api.create_currency_purchase_order(
                create_currency_purchase_order_payload(
                    fiat_amount_cents=5500, idempotency_key="cur-1"
                ),
                headers,
            ),
            201,
        )
        o2 = validate_success(
            api.create_currency_purchase_order(
                create_currency_purchase_order_payload(
                    fiat_amount_cents=5500, idempotency_key="cur-2"
                ),
                headers,
            ),
            201,
        )
        c1 = validate_success(api.confirm_currency_payment(o1["id"], headers), 200)
        c2 = validate_success(api.confirm_currency_payment(o2["id"], headers), 200)
        assert c1["credited_robux"] == 4900, (
            f"expected 4900 (999*0.8+4000*0.9+501*1.0=4900.2 rounded once), got {c1['credited_robux']}"
        )
        assert c2["credited_robux"] == 4900
        fresh = get_user(buyer["id"])
        assert fresh["robux_balance"] == 9800, (
            f"two completed 4900-Robux orders must credit 9800 total, got {fresh['robux_balance']}"
        )

    def test_currency_exchange_rounds_final_aggregate_not_per_tier(self, api):
        """PRD §3.3: "The Robux contributed by each tier are summed, and only the final
        aggregate is rounded — half-up to a whole number of Robux; per-tier rounding is
        forbidden because it drifts the total."

        Design: Difficulty/dual_variant_calc/currency_exchange_base_vs_promotional_bonus
        """
        set_clock()
        buyer = create_user(username="buyer_r", email="buyer_r@x.com", date_of_birth="1990-01-01")
        headers = make_creator_headers(buyer["id"])

        # 1500 cents: tier1 999*0.80 = 799.20, tier2 501*0.90 = 450.90; raw sum
        # 1250.10 -> 1250 when rounded once. Per-tier rounding would give 800+451=1251.
        order, credited = fund_user(buyer["id"], 1500)
        assert credited == 1250, (
            f"sum-then-round must give 1250 (per-tier rounding would give 1251), got {credited}"
        )
        fresh = get_user(buyer["id"])
        assert fresh["robux_balance"] == 1250


class TestCurrencyRefundInvariant:
    def test_currency_purchase_and_refund_leave_balance_unchanged(self, api, platform_admin_headers):
        """PRD §3.3: "A successful refund transitions the order to `REFUNDED` and
        subtracts `credited_robux` from the buyer's `robux_balance`, restoring the
        compensating invariant that the balance is unchanged net of the original
        purchase."

        Design: Difficulty/compensating_invariant/currency_purchase_and_refund_leave_balance_unchanged
        """
        set_clock()
        buyer = create_user(username="b_m", email="b_m@x.com", date_of_birth="1990-01-01")
        headers = make_creator_headers(buyer["id"])
        pre = get_user(buyer["id"])["robux_balance"]

        # 1000 cents: 999*0.80 + 1*0.90 = 800.10 -> 800 Robux.
        order = validate_success(
            api.create_currency_purchase_order(
                create_currency_purchase_order_payload(
                    fiat_amount_cents=1000, idempotency_key="cur-m"
                ),
                headers,
            ),
            201,
        )
        completed = validate_success(api.confirm_currency_payment(order["id"], headers), 200)
        assert completed["credited_robux"] == 800, (
            f"expected 800, got {completed['credited_robux']}"
        )
        assert get_user(buyer["id"])["robux_balance"] == pre + 800

        refunded = validate_success(
            api.refund_currency_purchase_order(order["id"], platform_admin_headers), 200
        )
        assert refunded["status"] == "REFUNDED"
        post = get_user(buyer["id"])["robux_balance"]
        assert post == pre, (
            f"compensating invariant violated: balance {post} != pre-purchase {pre}"
        )

    def test_currency_refund_after_spend_rejected_exceeds_balance(self, api, platform_admin_headers):
        """PRD §3.3: "A `PlatformAdmin` may refund a `COMPLETED` currency order only
        while the buyer's `robux_balance` still covers the order's `credited_robux`; if
        the buyer has already spent part of the credited Robux such that the refund
        would drive the balance negative, the refund is rejected with
        `ERR_REFUND_EXCEEDS_BALANCE`."

        Design: Difficulty/compensating_invariant/currency_purchase_and_refund_leave_balance_unchanged
        """
        set_clock()
        seller = create_user(username="s_rf", email="s_rf@x.com", date_of_birth="1990-01-01")
        buyer = create_user(username="b_rf", email="b_rf@x.com", date_of_birth="1990-01-01")
        buyer_headers = make_creator_headers(buyer["id"])
        item, _sub = create_on_sale_item(seller["id"], title="Refund Hat", price_robux=100)

        order, credited = fund_user(buyer["id"], 1000)
        assert credited == 800

        # Spend part of the credited Robux so the balance no longer covers the refund.
        po = validate_success(
            api.create_purchase_order(
                create_purchase_order_payload("MARKETPLACE_ITEM", item["id"], 100),
                buyer_headers,
            ),
            201,
        )
        validate_success(api.confirm_purchase_order(po["id"], buyer_headers), 200)
        assert get_user(buyer["id"])["robux_balance"] == 700

        resp = api.refund_currency_purchase_order(order["id"], platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_REFUND_EXCEEDS_BALANCE)
        assert get_user(buyer["id"])["robux_balance"] == 700


class TestIdempotency:
    def test_currency_purchase_order_idempotency_key_returns_same_order(self, api):
        """PRD §2.9: "Both order types — `CurrencyPurchaseOrder` and `PurchaseOrder` —
        accept a client-supplied `idempotency_key`. A repeated submission under a key
        already seen returns the original order rather than creating a new charge; a
        key reused with a different payload is rejected with
        `ERR_DUPLICATE_IDEMPOTENCY_KEY`."

        Design: Corner/endpoints/currency_purchase_order_idempotency_key_returns_same_order
        """
        set_clock()
        buyer = create_user(username="b_idem", email="b_idem@x.com", date_of_birth="1990-01-01")
        headers = make_creator_headers(buyer["id"])

        first = validate_success(
            api.create_currency_purchase_order(
                create_currency_purchase_order_payload(
                    fiat_amount_cents=500, idempotency_key="same-key"
                ),
                headers,
            ),
            201,
        )
        second = validate_success(
            api.create_currency_purchase_order(
                create_currency_purchase_order_payload(
                    fiat_amount_cents=500, idempotency_key="same-key"
                ),
                headers,
            ),
            201,
        )
        assert first["id"] == second["id"], (
            "same key + same payload must return the original order, not a new one"
        )

        resp = api.create_currency_purchase_order(
            create_currency_purchase_order_payload(
                fiat_amount_cents=999, idempotency_key="same-key"
            ),
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_IDEMPOTENCY_KEY)

    def test_purchase_order_idempotency_duplicate_key_different_payload(self, api):
        """PRD §2.9: "Both order types — `CurrencyPurchaseOrder` and `PurchaseOrder` —
        accept a client-supplied `idempotency_key`. A repeated submission under a key
        already seen returns the original order rather than creating a new charge; a
        key reused with a different payload is rejected with
        `ERR_DUPLICATE_IDEMPOTENCY_KEY`."

        Design: Corner/cross_cutting_complexity_layers/purchase_order_idempotency_duplicate_key_different_payload
        """
        set_clock()
        seller = create_user(username="s_idem", email="s_idem@x.com", date_of_birth="1990-01-01")
        buyer = create_user(username="b_idem2", email="b_idem2@x.com", date_of_birth="1990-01-01")
        buyer_headers = make_creator_headers(buyer["id"])
        item, _sub = create_on_sale_item(seller["id"], title="Idem Cap", price_robux=100)
        fund_user(buyer["id"], 750)

        first = validate_success(
            api.create_purchase_order(
                create_purchase_order_payload(
                    "MARKETPLACE_ITEM", item["id"], 100, idempotency_key="po-idem"
                ),
                buyer_headers,
            ),
            201,
        )
        second = validate_success(
            api.create_purchase_order(
                create_purchase_order_payload(
                    "MARKETPLACE_ITEM", item["id"], 100, idempotency_key="po-idem"
                ),
                buyer_headers,
            ),
            201,
        )
        assert first["id"] == second["id"], (
            "same key + same payload must return the original order"
        )

        resp = api.create_purchase_order(
            create_purchase_order_payload(
                "MARKETPLACE_ITEM", item["id"], 200, idempotency_key="po-idem"
            ),
            buyer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_IDEMPOTENCY_KEY)

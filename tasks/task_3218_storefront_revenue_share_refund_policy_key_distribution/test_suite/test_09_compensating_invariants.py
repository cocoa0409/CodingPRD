"""Depth tests for conserved quantities (revenue ledger, per-purchase split)."""
from test_helpers import (
    api_client,
    buy_title,
    create_buyer,
    create_released_title,
    make_user_headers,
    read_title,
    request_refund,
    set_clock,
    validate_success,
)


class TestRecognizedRevenueConservation:
    def test_purchase_then_full_refund_leaves_ledger_unchanged(self):
        """PRD §3.4: "Recognized revenue — the figure that drives tier
        evaluation — rises by a purchase's `usd_recognized_cents` at completion,
        falls by the USD value of each approved refund (partial refunds subtract
        only the refunded part, so the retained part keeps counting), and moves
        by the signed `delta_usd_cents` of manual adjustments, subject to the
        floor that recognized revenue may never go below zero
        (`ERR_NEGATIVE_REVENUE`)."

        Design: Difficulty/compensating_invariant/recognized_revenue_conservation_under_refund
        """
        set_clock("2026-09-04T00:00:00Z")
        developer, title = create_released_title(base_price_usd_cents=1000)
        buyer1 = create_buyer()
        buyer2 = create_buyer()

        buy_title(buyer1, title)
        baseline = read_title(title["id"], developer)
        assert baseline["lifetime_recognized_revenue_usd_cents"] == 1000

        purchase2 = buy_title(buyer2, title)
        rr = request_refund(purchase2, buyer2, reason="changed mind")
        assert rr["status"] == "APPROVED"

        final = read_title(title["id"], developer)
        assert final["lifetime_recognized_revenue_usd_cents"] == 1000

        purchase2_read = validate_success(
            api_client.get_purchase(purchase2["id"], make_user_headers(buyer2["id"]))
        )
        assert purchase2_read["status"] == "REFUNDED"
        assert purchase2_read["refunded_cents"] == 1000

    def test_non_usd_purchase_then_full_refund_leaves_ledger_unchanged(self):
        """PRD §3.3: "The purchase's `usd_recognized_cents` snapshot is the gross
        itself when the currency is USD, and otherwise the gross divided by the
        purchase-time FX rate, rounded half-up; that USD value is immediately
        added to the title's `lifetime_recognized_revenue_usd_cents`, the title's
        `current_tier` is re-evaluated, and the title's `version` increments."

        Design: Difficulty/compensating_invariant/recognized_revenue_conservation_under_refund
        """
        set_clock("2026-09-04T00:00:00Z")
        developer, title = create_released_title(base_price_usd_cents=1000)
        buyer = create_buyer()

        purchase = buy_title(buyer, title, currency="EUR")
        mid = read_title(title["id"], developer)
        credited = mid["lifetime_recognized_revenue_usd_cents"]
        assert credited == purchase["usd_recognized_cents"] > 0

        rr = request_refund(purchase, buyer, reason="not for me")
        assert rr["status"] == "APPROVED"

        final = read_title(title["id"], developer)
        assert final["lifetime_recognized_revenue_usd_cents"] == 0


class TestPurchaseSplitConservation:
    def test_fee_plus_share_equals_gross_999_tier1(self):
        """PRD §3.4: "So `platform_fee_cents` plus `developer_share_cents`
        always reconstructs `gross_price_cents` exactly."

        Design: Difficulty/compensating_invariant/purchase_gross_equals_fee_plus_share_conservation
        """
        developer, title = create_released_title(base_price_usd_cents=999)
        buyer = create_buyer()

        purchase = buy_title(buyer, title)

        assert purchase["gross_price_cents"] == 999
        # round_half_up(999 * 0.30) = round_half_up(299.7) = 300
        assert purchase["platform_fee_cents"] == 300
        assert purchase["developer_share_cents"] == 699
        assert purchase["platform_fee_cents"] + purchase["developer_share_cents"] == 999

    def test_fee_plus_share_equals_gross_across_prices(self):
        """PRD §3.4: "Each purchase is split between platform and developer using
        the tier rate in force at purchase time."

        Design: Difficulty/compensating_invariant/purchase_gross_equals_fee_plus_share_conservation
        """
        for price in (1, 7, 333):
            developer, title = create_released_title(base_price_usd_cents=price)
            buyer = create_buyer()
            purchase = buy_title(buyer, title)
            assert purchase["gross_price_cents"] == price
            assert (
                purchase["platform_fee_cents"] + purchase["developer_share_cents"]
                == purchase["gross_price_cents"]
            ), f"split must conserve gross at price {price}"

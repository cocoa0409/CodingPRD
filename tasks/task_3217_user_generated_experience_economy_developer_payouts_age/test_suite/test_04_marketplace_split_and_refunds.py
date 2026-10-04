"""Marketplace split, limited-resale waterfall, and purchase/refund
compensating invariants (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    assert_purchase_order,
    buy_item,
    create_limited_item,
    create_marketplace_item,
    create_on_sale_item,
    create_on_sale_limited_item,
    create_purchase_order_payload,
    create_user,
    expected_marketplace_split_nonlimited,
    expected_resale_waterfall,
    find_asset_submission,
    fund_user,
    get_user,
    list_for_resale,
    make_creator_headers,
    set_clock,
    validate_success,
)


class TestMarketplaceSplitNonLimited:
    def test_marketplace_split_nonlimited_fee_30pct(self, api):
        """PRD §3.7: "The platform fee is always 30% of `price_robux`, rounded half-up
        to a whole Robux, and recorded as `platform_fee_robux`. For a non-limited item
        or a gamepass, the remainder — `price_robux` minus the fee — is the
        `creator_credit_robux` paid to the seller."
        PRD §3.7: "On completion the buyer's `robux_balance` drops by `price_robux`,
        the seller's `earned_robux_lifetime` rises by their credit"

        Design: Corner/calculations/marketplace_split_nonlimited_fee_30pct
        """
        set_clock()
        seller = create_user(username="s_ms", email="s_ms@x.com", date_of_birth="1990-01-01")
        buyer = create_user(username="b_ms", email="b_ms@x.com", date_of_birth="1990-01-01")
        item, _sub = create_on_sale_item(seller["id"], title="Cap", price_robux=100)
        fund_user(buyer["id"], 750)  # 750c -> 600 Robux

        po = buy_item(buyer["id"], item["id"], 100)
        assert_purchase_order(po)
        assert po["status"] == "COMPLETED"
        assert po["platform_fee_robux"] == 30, (
            f"fee must be round_half_up(100*0.30)=30, got {po['platform_fee_robux']}"
        )
        assert po["creator_credit_robux"] == 70, (
            f"creator credit must be 100-30=70, got {po['creator_credit_robux']}"
        )
        seller_fresh = get_user(seller["id"])
        assert seller_fresh["earned_robux_lifetime"] == 70, (
            f"seller lifetime earned must rise by 70, got {seller_fresh['earned_robux_lifetime']}"
        )
        buyer_fresh = get_user(buyer["id"])
        assert buyer_fresh["robux_balance"] == 500, (
            f"buyer balance must drop by 100 from 600 to 500, got {buyer_fresh['robux_balance']}"
        )


class TestLimitedResaleWaterfall:
    def test_marketplace_split_limited_resale_royalty_waterfall(self, api, platform_admin_headers):
        """PRD §3.7: "For a limited resale the split is a waterfall, and the order of
        operations is pinned: the platform fee comes off first, the gross seller share
        is what remains, the royalty is computed as the gross seller share multiplied
        by the item's `royalty_pct` percent and rounded half-up, the reseller's credit
        is the gross seller share minus the royalty, and the original creator's credit
        is exactly the royalty."
        PRD §3.6: "On sale, `sold_at` and `buyer_user_id` are stamped, item ownership
        transfers to the buyer, and the proceeds split by the waterfall in §3.7: the
        seller's `robux_balance` grows by their post-fee, post-royalty share, and the
        original creator's `earned_robux_lifetime` grows by the royalty share."

        Design: Corner/calculations/marketplace_split_limited_resale_royalty_waterfall
        """
        set_clock("2026-08-20T00:00:00Z")
        oc = create_user(username="oc_x", email="oc@x.com", date_of_birth="1990-01-01")
        rs = create_user(username="rs_x", email="rs@x.com", date_of_birth="1990-01-01")
        bb = create_user(username="bb_x", email="bb@x.com", date_of_birth="1990-01-01")

        item, _sub = create_on_sale_limited_item(
            oc["id"], title="Ltd Hat", price_robux=500, total_supply=5, royalty_pct=10
        )

        # Reseller buys the limited in the primary sale (500 Robux at 700c -> 560).
        fund_user(rs["id"], 700)
        buy_item(rs["id"], item["id"], 500)
        assert get_user(oc["id"])["earned_robux_lifetime"] == 350, (
            "primary sale of 500 with 30% fee must credit the original creator 350"
        )

        fund_user(bb["id"], 3000)  # -> 2600 Robux

        # Age the reseller's account past the seven-day resale gate.
        set_clock("2026-09-01T00:00:00Z")
        listing = list_for_resale(rs["id"], item["id"], 1000)

        rs_balance_before = get_user(rs["id"])["robux_balance"]
        bb_headers = make_creator_headers(bb["id"])
        po = validate_success(
            api.create_purchase_order(
                create_purchase_order_payload(
                    "LIMITED_ITEM_RESALE", listing["id"], 1000
                ),
                bb_headers,
            ),
            201,
        )
        completed = validate_success(api.confirm_purchase_order(po["id"], bb_headers), 200)
        assert completed["status"] == "COMPLETED"
        assert completed["platform_fee_robux"] == 300, (
            f"fee must be round_half_up(1000*0.30)=300, got {completed['platform_fee_robux']}"
        )

        # Waterfall: fee 300; gross seller share 700; royalty round(700*0.10)=70;
        # reseller credit 630; original creator +70 royalty on top of 350 primary.
        oc_fresh = get_user(oc["id"])
        assert oc_fresh["earned_robux_lifetime"] == 420, (
            f"original creator must have 350 (primary) + 70 (royalty) = 420, got "
            f"{oc_fresh['earned_robux_lifetime']}"
        )
        rs_fresh = get_user(rs["id"])
        assert rs_fresh["robux_balance"] == rs_balance_before + 630, (
            f"reseller must net 630 (700 gross share minus 70 royalty), got delta "
            f"{rs_fresh['robux_balance'] - rs_balance_before}"
        )

        sold = validate_success(
            api.get_resale_listing(listing["id"], platform_admin_headers), 200
        )
        assert sold["status"] == "SOLD"


class TestPurchaseRefundInvariant:
    def test_purchase_and_refund_leave_seller_lifetime_earned_unchanged(self, api, platform_admin_headers):
        """PRD §3.7: "Refunding returns `price_robux` to the buyer's `robux_balance`
        and subtracts `creator_credit_robux` from the seller's `earned_robux_lifetime`
        — the compensating invariant is that the seller's lifetime-earned figure
        returns to its pre-purchase value."

        Design: Difficulty/compensating_invariant/purchase_and_refund_leave_seller_lifetime_earned_unchanged
        """
        set_clock()
        seller = create_user(username="s_n", email="s_n@x.com", date_of_birth="1990-01-01")
        buyer = create_user(username="b_n", email="b_n@x.com", date_of_birth="1990-01-01")
        item, _sub = create_on_sale_item(seller["id"], title="Cap N", price_robux=100)
        fund_user(buyer["id"], 750)

        earned_pre = get_user(seller["id"])["earned_robux_lifetime"]
        po = buy_item(buyer["id"], item["id"], 100)
        assert get_user(seller["id"])["earned_robux_lifetime"] == earned_pre + 70

        refunded = validate_success(api.refund_purchase_order(po["id"], platform_admin_headers), 200)
        assert refunded["status"] == "REFUNDED"
        assert get_user(seller["id"])["earned_robux_lifetime"] == earned_pre, (
            "refund must return the seller's lifetime-earned figure to its pre-purchase value"
        )
        assert get_user(buyer["id"])["robux_balance"] == 600, (
            "refund must return the full price_robux to the buyer"
        )

    def test_purchase_refund_of_one_of_two_restores_partial_lifetime(self, api, platform_admin_headers):
        """PRD §3.7: "Refunding returns `price_robux` to the buyer's `robux_balance`
        and subtracts `creator_credit_robux` from the seller's `earned_robux_lifetime`
        — the compensating invariant is that the seller's lifetime-earned figure
        returns to its pre-purchase value."

        Design: Difficulty/compensating_invariant/purchase_and_refund_leave_seller_lifetime_earned_unchanged
        """
        set_clock()
        seller = create_user(username="s_n2", email="s_n2@x.com", date_of_birth="1990-01-01")
        buyer = create_user(username="b_n2", email="b_n2@x.com", date_of_birth="1990-01-01")
        item, _sub = create_on_sale_item(seller["id"], title="Cap N2", price_robux=100)
        fund_user(buyer["id"], 750)

        po1 = buy_item(buyer["id"], item["id"], 100)
        po2 = buy_item(buyer["id"], item["id"], 100)
        assert get_user(seller["id"])["earned_robux_lifetime"] == 140

        validate_success(api.refund_purchase_order(po1["id"], platform_admin_headers), 200)
        assert get_user(seller["id"])["earned_robux_lifetime"] == 70, (
            "refunding one of two purchases must subtract exactly that order's credit"
        )
        # The surviving order is untouched.
        surviving = validate_success(
            api.get_purchase_order(po2["id"], platform_admin_headers), 200
        )
        assert surviving["status"] == "COMPLETED"

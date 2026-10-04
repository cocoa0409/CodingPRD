"""On-approval sales, sale unwinding, and seller-side decisions."""
from test_helpers import (
    ApiErrorId,
    assert_settlement_invariants,
    create_member,
    create_seller,
    create_yard,
    create_auction,
    get_settlement,
    get_success_data,
    issue_gate_pass,
    list_into_auction,
    make_buyer_headers,
    make_seller_agent_headers,
    pay_sale,
    place_bid,
    prepare_vehicle,
    set_clock,
    setup_closed_sale,
    setup_live_item,
    setup_paid_sale,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

AU = TEST_USERS["auctioneer_headers"]
YO = TEST_USERS["yard_operator_headers"]
TC = TEST_USERS["title_clerk_headers"]


def _on_approval_pending(api, ctx, bid_cents=300000):
    """Close the live ON_APPROVAL lot; returns (bid, PENDING_APPROVAL Sale)."""
    bid = place_bid(ctx["item"]["id"], ctx["member"], bid_cents)
    sale = validate_success(api.close_lot(ctx["auction"]["id"], ctx["item"]["id"], AU), 200)
    assert sale["status"] == "PENDING_APPROVAL"
    return bid, sale


ON_APPROVAL_KWARGS = dict(reserve_price_cents=500000, sale_type="ON_APPROVAL")


class TestCloseLotSettlement:
    def test_close_lot_creates_sale_and_draft_settlement(self, api):
        """PRD §3.5: "Whichever path produced it, a completed sale triggers a fixed
        bundle of side effects at the moment it becomes `AWAITING_PAYMENT`. A
        `Settlement` is created in `DRAFT` status and computed per the waterfall of
        §3.6."
        PRD §3.6: "under `STANDARD` it is the greater of 2500 cents and 10 percent of
        the gross rounded half-up, plus a fixed 5000-cent title fee" and "`storage_recovery_cents`
        ... the whole calendar days between the vehicle's `received_at` date and the
        sale-day UTC date, minus a seller free allowance of seven days ... floored at
        zero".

        Derivation (same-day close: received_at 2026-09-01, sale day 2026-09-01, hammer
        1000000, STANDARD seller):
          gross = 1000000
          seller_fee = max(2500, round_half_up(0.10*1000000)) + 5000 = 105000
          storage_recovery = (0 days - 7) floored at 0 = 0
          title_late_penalty = 0 (title received 2026-09-01, same day as assigned)
          net = 1000000 - 105000 - 0 - 0 = 895000
          buyer_fee = 0.12*500000 + 0.09*500000 = 60000 + 45000 = 105000
          payment amount = 1000000 + 105000 + 0 = 1105000

        Design: Difficulty/transitive_cascade/close_lot_five_hop_cascade
        """
        ctx = setup_closed_sale()
        sale = ctx["sale"]
        assert sale["status"] == "AWAITING_PAYMENT"
        assert sale["buyer_fee_cents"] == 105000
        settlement = get_settlement(sale["id"])
        assert settlement["status"] == "DRAFT"
        assert settlement["gross_proceeds_cents"] == 1000000
        assert settlement["seller_fee_cents"] == 105000
        assert settlement["storage_recovery_cents"] == 0
        assert settlement["title_late_penalty_cents"] == 0
        assert settlement["net_proceeds_cents"] == 895000
        assert_settlement_invariants(settlement)


class TestOnApprovalCycle:
    def test_on_approval_reject_returns_vehicle_to_sale_ready(self, api):
        """PRD §3.5: "Rejection requires only that the sale be `PENDING_APPROVAL` and
        seller-owned; it cancels the sale, releases the winning bid (`is_winning` back
        to false), and returns the vehicle to `SALE_READY` so it can be listed again."

        Design: Difficulty/non_linear_state_machine/vehicle_on_approval_reject_relists_cycle
        """
        ctx = setup_live_item(**ON_APPROVAL_KWARGS)
        bid, sale = _on_approval_pending(api, ctx)
        seller_headers = make_seller_agent_headers(ctx["seller"]["id"])
        validate_success(api.reject_offer(sale["id"], seller_headers), 200)
        sale = get_success_data(api.get_sale(sale["id"], seller_headers))
        assert sale["status"] == "CANCELLED"
        vehicle = get_success_data(api.get_vehicle(ctx["vehicle"]["id"], seller_headers))
        assert vehicle["status"] == "SALE_READY"
        released = get_success_data(api.get_bid(bid["id"], AU))
        assert released["is_winning"] is False
        item = get_success_data(api.get_auction_item(ctx["item"]["id"], AU))
        assert item["status"] == "CLOSED"

    def test_on_approval_reject_permits_relisting_into_new_auction(self, api):
        """PRD §3.5: "Rejection requires only that the sale be `PENDING_APPROVAL` and
        seller-owned; it cancels the sale, releases the winning bid (`is_winning` back
        to false), and returns the vehicle to `SALE_READY` so it can be listed again."
        PRD §3.3: "Listing requires the vehicle to be `SALE_READY`
        (`ERR_VEHICLE_NOT_SALE_READY`), the auction to be `SCHEDULED`
        (`ERR_AUCTION_NOT_SCHEDULED`), and no other item for the same vehicle to be
        `QUEUED` or `LIVE` (`ERR_VEHICLE_ALREADY_LISTED`)."

        Design: Difficulty/non_linear_state_machine/vehicle_on_approval_reject_relists_cycle
        """
        ctx = setup_live_item(**ON_APPROVAL_KWARGS)
        _, sale = _on_approval_pending(api, ctx)
        seller_headers = make_seller_agent_headers(ctx["seller"]["id"])
        validate_success(api.reject_offer(sale["id"], seller_headers), 200)
        auction2 = create_auction()
        item2 = validate_success(
            api.create_auction_item(auction2["id"], {"vehicle_id": ctx["vehicle"]["id"]}, AU), 201
        )
        assert item2["status"] == "QUEUED"

    def test_on_approval_reject_restores_full_pre_listing_state(self, api):
        """PRD §3.5: "Rejection requires only that the sale be `PENDING_APPROVAL` and
        seller-owned; it cancels the sale, releases the winning bid (`is_winning` back
        to false), and returns the vehicle to `SALE_READY` so it can be listed again."

        Design: Difficulty/compensating_invariant/on_approval_reject_restores_full_pre_listing_state
        """
        ctx = setup_live_item(**ON_APPROVAL_KWARGS)
        bid, sale = _on_approval_pending(api, ctx)
        seller_headers = make_seller_agent_headers(ctx["seller"]["id"])
        validate_success(api.reject_offer(sale["id"], seller_headers), 200)
        vehicle = get_success_data(api.get_vehicle(ctx["vehicle"]["id"], seller_headers))
        assert vehicle["status"] == "SALE_READY"
        sale = get_success_data(api.get_sale(sale["id"], seller_headers))
        assert sale["status"] == "CANCELLED"
        assert get_success_data(api.get_bid(bid["id"], AU))["is_winning"] is False

    def test_no_queued_or_live_items_remain_after_reject(self, api):
        """PRD §3.5: "Rejection requires only that the sale be `PENDING_APPROVAL` and
        seller-owned; it cancels the sale, releases the winning bid (`is_winning` back
        to false), and returns the vehicle to `SALE_READY` so it can be listed again."

        Design: Difficulty/compensating_invariant/on_approval_reject_restores_full_pre_listing_state
        """
        ctx = setup_live_item(**ON_APPROVAL_KWARGS)
        _, sale = _on_approval_pending(api, ctx)
        seller_headers = make_seller_agent_headers(ctx["seller"]["id"])
        validate_success(api.reject_offer(sale["id"], seller_headers), 200)
        items = get_success_data(
            api.list_vehicle_auction_items(ctx["vehicle"]["id"], AU)
        )
        assert all(i["status"] in ("CLOSED", "CANCELLED") for i in items)
        sales = get_success_data(
            api.list_sales(seller_headers, params={"vehicle_id": ctx["vehicle"]["id"]})
        )
        assert all(s["status"] == "CANCELLED" for s in sales)


class TestSaleCancelRollback:
    def test_sale_cancel_restores_title_and_brand(self, api):
        """PRD §3.5: "Cancelling a sale requires its status to be `PENDING_APPROVAL` or
        `AWAITING_PAYMENT` (`ERR_SALE_NOT_CANCELLABLE`) and rolls everything back: the
        sale becomes `CANCELLED`; the settlement remains `DRAFT` with all money fields
        zeroed; the title record returns to `RECEIVED`; the vehicle's `title_brand` is
        restored to its prior value; the winning bid is released; and the vehicle
        returns to `SALE_READY`."

        Design: Difficulty/compensating_invariant/title_record_count_conserved_across_sale_cancel
        """
        ctx = setup_closed_sale()  # PURE, sold, AWAITING_PAYMENT
        seller_headers = make_seller_agent_headers(ctx["seller"]["id"])
        validate_success(api.cancel_sale(ctx["sale"]["id"], seller_headers), 200)
        titles = get_success_data(api.get_vehicle_title(ctx["vehicle"]["id"], TC))
        assert len(titles) == 1, f"title cardinality must be conserved, got {len(titles)}"
        assert titles[0]["status"] == "RECEIVED"
        vehicle = get_success_data(api.get_vehicle(ctx["vehicle"]["id"], seller_headers))
        assert vehicle["title_brand"] == "NONE"
        assert vehicle["status"] == "SALE_READY"
        sale = get_success_data(api.get_sale(ctx["sale"]["id"], seller_headers))
        assert sale["status"] == "CANCELLED"

    def test_sale_cancel_zeroes_draft_settlement(self, api):
        """PRD §3.5: "the settlement remains `DRAFT` with all money fields zeroed"

        Design: Difficulty/compensating_invariant/title_record_count_conserved_across_sale_cancel
        """
        ctx = setup_closed_sale()
        settlement_before = get_settlement(ctx["sale"]["id"])
        assert settlement_before["status"] == "DRAFT"
        seller_headers = make_seller_agent_headers(ctx["seller"]["id"])
        validate_success(api.cancel_sale(ctx["sale"]["id"], seller_headers), 200)
        settlement_after = get_settlement(ctx["sale"]["id"])
        assert settlement_after["status"] == "DRAFT"
        for field in (
            "gross_proceeds_cents",
            "seller_fee_cents",
            "storage_recovery_cents",
            "title_late_penalty_cents",
            "net_proceeds_cents",
        ):
            assert settlement_after[field] == 0, f"{field} must be zeroed, got {settlement_after[field]}"


class TestPaymentCascade:
    def test_payment_finalizes_settlement_and_releases_vehicle(self, api):
        """PRD §3.5: "A clearing payment moves the sale to `PAID`, the settlement to
        `FINALIZED` (locking the seller's proceeds), and the vehicle to `RELEASED`."

        Design: Difficulty/transitive_cascade/close_lot_five_hop_cascade
        """
        ctx = setup_paid_sale()
        assert ctx["sale"]["status"] == "PAID"
        settlement = get_settlement(ctx["sale"]["id"])
        assert settlement["status"] == "FINALIZED"
        vehicle = get_success_data(api.get_vehicle(ctx["vehicle"]["id"], YO))
        assert vehicle["status"] == "RELEASED"

    def test_load_out_complete_marks_settlement_paid_and_vehicle_loaded_out(self, api):
        """PRD §3.8: "Completion — the vehicle physically leaving — requires the pass
        to be `CHECKED_IN` (`ERR_GATE_PASS_INVALID_STATE`) and finishes the cycle in
        one bundle: the pass becomes `COMPLETED`, the vehicle becomes `LOADED_OUT`,
        and the settlement becomes `PAID`."

        Design: Difficulty/transitive_cascade/close_lot_five_hop_cascade
        """
        ctx = setup_paid_sale()
        set_clock("2026-09-02T15:00:00Z")
        gp = issue_gate_pass(ctx)
        validate_success(api.check_in_gate_pass(gp["id"], YO), 200)
        done = validate_success(api.complete_gate_pass(gp["id"], YO), 200)
        assert done["status"] == "COMPLETED"
        settlement = get_settlement(ctx["sale"]["id"])
        assert settlement["status"] == "PAID"
        vehicle = get_success_data(api.get_vehicle(ctx["vehicle"]["id"], YO))
        assert vehicle["status"] == "LOADED_OUT"


class TestSellerLiveCancel:
    def test_seller_live_cancel_releases_bid_and_completes_auction(self, api):
        """PRD §3.5: "cancelling a `LIVE` vehicle cancels the live item and releases
        every winning bid on it, and if that leaves the auction with no queued or live
        items, the auction completes automatically."

        Design: Difficulty/transitive_cascade/seller_live_cancel_releases_bid_and_completes_auction
        """
        ctx = setup_live_item()
        bid = place_bid(ctx["item"]["id"], ctx["member"], 1000000)
        seller_headers = make_seller_agent_headers(ctx["seller"]["id"])
        validate_success(api.cancel_vehicle(ctx["vehicle"]["id"], seller_headers), 200)
        vehicle = get_success_data(api.get_vehicle(ctx["vehicle"]["id"], seller_headers))
        assert vehicle["status"] == "CANCELLED"
        item = get_success_data(api.get_auction_item(ctx["item"]["id"], AU))
        assert item["status"] == "CANCELLED"

    def test_seller_live_cancel_auto_completes_auction(self, api):
        """PRD §3.5: "cancelling a `LIVE` vehicle cancels the live item and releases
        every winning bid on it, and if that leaves the auction with no queued or live
        items, the auction completes automatically."

        Design: Difficulty/transitive_cascade/seller_live_cancel_releases_bid_and_completes_auction
        """
        ctx = setup_live_item()
        bid = place_bid(ctx["item"]["id"], ctx["member"], 1000000)
        seller_headers = make_seller_agent_headers(ctx["seller"]["id"])
        validate_success(api.cancel_vehicle(ctx["vehicle"]["id"], seller_headers), 200)
        auction = get_success_data(api.get_auction(ctx["auction"]["id"], AU))
        assert auction["status"] == "COMPLETED"
        released = get_success_data(api.get_bid(bid["id"], AU))
        assert released["is_winning"] is False

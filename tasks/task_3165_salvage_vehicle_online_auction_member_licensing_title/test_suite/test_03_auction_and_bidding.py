"""Auction sequencing, lot opening/closing, prelim snapshot, bid rules."""
from test_helpers import (
    ApiErrorId,
    add_images,
    assert_auction_item,
    create_auction,
    create_member,
    create_seller,
    create_vehicle,
    create_yard,
    get_success_data,
    list_into_auction,
    make_buyer_headers,
    mark_ready,
    place_bid,
    prepare_vehicle,
    receive_title,
    setup_closed_sale,
    setup_live_item,
    submit_condition,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

AU = TEST_USERS["auctioneer_headers"]
YO = TEST_USERS["yard_operator_headers"]


def _second_ready_vehicle(seller, yard, **overrides):
    return prepare_vehicle(seller, yard, **overrides)


class TestOpenLotSequencing:
    def test_open_lot_rejected_before_auction_live(self, api):
        """PRD §3.4: "Opening a lot requires the auction to be `LIVE`
        (`ERR_AUCTION_NOT_LIVE`)"

        Design: Difficulty/cross_entity_state_dependency/open_lot_requires_auction_live_and_sequence_next
        """
        yard = create_yard()
        seller = create_seller()
        v1 = prepare_vehicle(seller, yard)
        v2 = _second_ready_vehicle(seller, yard)
        auction = create_auction()
        item1 = list_into_auction(auction["id"], v1["id"])
        list_into_auction(auction["id"], v2["id"])
        resp = api.open_lot(auction["id"], item1["id"], AU)
        validate_error(resp, ApiErrorId.ERR_AUCTION_NOT_LIVE)

    def test_open_lot_out_of_order_rejected(self, api):
        """PRD §3.4: "the item's `sequence_number` to be exactly one greater than the
        auction's `current_sequence_number` (skipping ahead is rejected with
        `ERR_AUCTION_ITEM_OUT_OF_ORDER`)"
        PRD §3.3: "Going live assigns the deterministic running order: the candidate
        set is the auction's `QUEUED` items, ranked by their `created_at` ascending"

        Design: Difficulty/cross_entity_state_dependency/open_lot_requires_auction_live_and_sequence_next
        """
        yard = create_yard()
        seller = create_seller()
        v1 = prepare_vehicle(seller, yard)
        v2 = _second_ready_vehicle(seller, yard)
        auction = create_auction()
        item1 = list_into_auction(auction["id"], v1["id"])
        item2 = list_into_auction(auction["id"], v2["id"])
        auction = get_success_data(api.start_auction(auction["id"], AU))
        assert auction["current_sequence_number"] == 0
        item1 = get_success_data(api.get_auction_item(item1["id"], AU))
        item2 = get_success_data(api.get_auction_item(item2["id"], AU))
        assert item1["sequence_number"] == 1
        assert item2["sequence_number"] == 2
        resp = api.open_lot(auction["id"], item2["id"], AU)
        validate_error(resp, ApiErrorId.ERR_AUCTION_ITEM_OUT_OF_ORDER)
        assert get_success_data(api.get_auction_item(item1["id"], AU))["status"] == "QUEUED"
        assert get_success_data(api.get_auction_item(item2["id"], AU))["status"] == "QUEUED"


class TestPrelimSnapshot:
    def test_prelim_high_bid_snapshot_sets_opening_high_bid(self, api):
        """PRD §3.4: "Opening snapshots the preliminary market:
        `prelim_high_bid_cents` becomes the maximum of the bids placed while the item
        was queued (0 when there were none), `prelim_high_bidder_id` the member who
        placed it (null when none), and the live bookkeeping — `high_bid_cents`,
        `high_bidder_id` — initializes from that same snapshot."
        PRD §3.4: "The `reserve_met` flag is set true exactly when the preliminary high
        bid is at least the vehicle's `reserve_price_cents`"

        Design: Corner/calculations/prelim_high_bid_snapshot_sets_opening_high_bid
        """
        yard = create_yard()
        seller = create_seller()
        ma = create_member(email="a@x.com", full_name="Member A")
        mb = create_member(email="b@x.com", full_name="Member B")
        vehicle = prepare_vehicle(seller, yard, reserve_price_cents=440000, sale_type="MINIMUM_BID")
        auction = create_auction()
        item = list_into_auction(auction["id"], vehicle["id"])
        bid_a = place_bid(item["id"], ma, 400000)
        bid_b = place_bid(item["id"], mb, 450000)
        assert bid_a["bid_type"] == "PRELIM"
        assert bid_b["bid_type"] == "PRELIM"
        get_success_data(api.start_auction(auction["id"], AU))
        opened = validate_success(api.open_lot(auction["id"], item["id"], AU), 200)
        assert_auction_item(opened)
        assert opened["prelim_high_bid_cents"] == 450000
        assert opened["prelim_high_bidder_id"] == mb["id"]
        assert opened["high_bid_cents"] == 450000
        assert opened["high_bidder_id"] == mb["id"]
        assert opened["reserve_met"] is True
        assert get_success_data(api.get_bid(bid_a["id"], AU))["is_winning"] is False
        assert get_success_data(api.get_bid(bid_b["id"], AU))["is_winning"] is True


class TestBidAmountRules:
    def test_error_bid_increment_and_self_outbid(self, api):
        """PRD §3.4: "a live bid must be at least the current `high_bid_cents` plus
        2500 cents, the fixed minimum increment, else `ERR_BID_INCREMENT_TOO_SMALL`"
        PRD §3.4: "A member who is already the high bidder on the item may not outbid
        themself — such a bid is rejected with `ERR_BID_SELF_OUTBID`."

        Design: Corner/errors/error_bid_increment_and_self_outbid
        """
        ctx = setup_live_item()
        item_id = ctx["item"]["id"]
        ma = ctx["member"]
        mb = create_member(email="b@x.com", full_name="Member B")
        place_bid(item_id, ma, 1000000)
        resp = api.place_bid(
            {"auction_item_id": item_id, "amount_cents": 1002499}, make_buyer_headers(mb["id"])
        )
        validate_error(resp, ApiErrorId.ERR_BID_INCREMENT_TOO_SMALL)
        resp = api.place_bid(
            {"auction_item_id": item_id, "amount_cents": 1010000}, make_buyer_headers(ma["id"])
        )
        validate_error(resp, ApiErrorId.ERR_BID_SELF_OUTBID)

    def test_exact_minimum_increment_accepted(self, api):
        """PRD §3.4: "a live bid must be at least the current `high_bid_cents` plus
        2500 cents, the fixed minimum increment, else `ERR_BID_INCREMENT_TOO_SMALL`"
        PRD §3.4: "Each accepted bid flips the previous winning bid's `is_winning` to
        false, sets its own `is_winning` to true, ... recomputes the item's
        `high_bid_cents`, `high_bidder_id`, and `reserve_met`"

        Design: Corner/errors/error_bid_increment_and_self_outbid
        """
        ctx = setup_live_item()
        item_id = ctx["item"]["id"]
        ma = ctx["member"]
        mb = create_member(email="b@x.com", full_name="Member B")
        place_bid(item_id, ma, 1000000)
        bid_b = place_bid(item_id, mb, 1002500)
        assert bid_b["is_winning"] is True
        item = get_success_data(api.get_auction_item(item_id, AU))
        assert item["high_bid_cents"] == 1002500
        assert item["high_bidder_id"] == mb["id"]


class TestCloseLotGuards:
    def test_error_no_bids_on_close(self, api):
        """PRD §3.4: "Closing requires the item to be `LIVE`
        (`ERR_AUCTION_ITEM_NOT_LIVE`) and at least one bid to have been accepted, so
        `high_bid_cents` above zero (`ERR_NO_BIDS`)."

        Design: Corner/errors/error_no_bids_on_close
        """
        ctx = setup_live_item()
        resp = api.close_lot(ctx["auction"]["id"], ctx["item"]["id"], AU)
        validate_error(resp, ApiErrorId.ERR_NO_BIDS)
        item = get_success_data(api.get_auction_item(ctx["item"]["id"], AU))
        assert item["status"] == "LIVE"
        vehicle = get_success_data(api.get_vehicle(ctx["vehicle"]["id"], YO))
        assert vehicle["status"] == "LIVE"


class TestReserveBoundary:
    def test_reserve_met_equality_sells(self, api):
        """PRD §3.4: "For `PURE` and `MINIMUM_BID` vehicles, `reserve_met` must also be
        true (`ERR_RESERVE_NOT_MET`)"
        PRD §3.4: "The `reserve_met` flag is set true exactly when the preliminary high
        bid is at least the vehicle's `reserve_price_cents`"

        Design: Difficulty/boundary_precision_check/reserve_met_equality_vs_one_cent_below
        """
        ctx = setup_closed_sale(
            hammer_cents=500000, reserve_price_cents=500000, sale_type="MINIMUM_BID"
        )
        assert ctx["sale"]["winning_bid_cents"] == 500000
        vehicle = get_success_data(api.get_vehicle(ctx["vehicle"]["id"], AU))
        assert vehicle["status"] == "SOLD"
        item = get_success_data(api.get_auction_item(ctx["item"]["id"], AU))
        assert item["reserve_met"] is True

    def test_one_cent_below_reserve_rejected(self, api):
        """PRD §3.4: "For `PURE` and `MINIMUM_BID` vehicles, `reserve_met` must also be
        true (`ERR_RESERVE_NOT_MET`)"
        PRD §3.4: "The `reserve_met` flag is set true exactly when the preliminary high
        bid is at least the vehicle's `reserve_price_cents`"

        Design: Difficulty/boundary_precision_check/reserve_met_equality_vs_one_cent_below
        """
        ctx = setup_live_item(reserve_price_cents=500000, sale_type="MINIMUM_BID")
        place_bid(ctx["item"]["id"], ctx["member"], 499999)
        item = get_success_data(api.get_auction_item(ctx["item"]["id"], AU))
        assert item["reserve_met"] is False
        resp = api.close_lot(ctx["auction"]["id"], ctx["item"]["id"], AU)
        validate_error(resp, ApiErrorId.ERR_RESERVE_NOT_MET)
        vehicle = get_success_data(api.get_vehicle(ctx["vehicle"]["id"], AU))
        assert vehicle["status"] == "LIVE"


class TestAuctionAutoComplete:
    def test_auction_auto_completes_when_last_item_closes(self, api):
        """PRD §3.3: "An auction with no remaining `QUEUED` or `LIVE` items — every
        item `CLOSED` or `CANCELLED` — automatically transitions to `COMPLETED`."
        PRD §3.4: "A successful close of those sale types moves the vehicle
        `LIVE → SOLD`"

        Design: Corner/state_machines/auction_auto_completes_when_last_item_closes
        """
        ctx = setup_closed_sale()
        auction = get_success_data(api.get_auction(ctx["auction"]["id"], AU))
        assert auction["status"] == "COMPLETED"
        item = get_success_data(api.get_auction_item(ctx["item"]["id"], AU))
        assert item["status"] == "CLOSED"
        vehicle = get_success_data(api.get_vehicle(ctx["vehicle"]["id"], AU))
        assert vehicle["status"] == "SOLD"


class TestImmediateConsistency:
    def test_close_lot_response_carries_computed_sale_fields(self, api):
        """PRD §3.4: "A successful close of those sale types moves the vehicle
        `LIVE → SOLD` and produces a `Sale` in `AWAITING_PAYMENT` status: the
        `winning_bid_cents` and `winner_member_id` are copied from the item's high bid,
        the `buyer_fee_cents` is computed per the tiered premium of §3.6, and the
        `gate_pass_expires_at` is set to the logical clock plus 72 hours."
        PRD §3.6: "The first 500000 cents of the hammer price are charged at 12%;
        the portion from 500000 up to (but not including) 2000000 cents is charged at
        9%."

        Derivation (hammer 1000000, logical clock 2026-09-01T00:00:00Z at close):
          buyer_fee = round_half_up(0.12*500000) + round_half_up(0.09*500000)
                    = 60000 + 45000 = 105000
          gate_pass_expires_at = 2026-09-01T00:00:00Z + 72h = 2026-09-04T00:00:00Z

        Design: Corner/consistency_model/immediate_consistency_same_response_reflects_all_mutations
        """
        ctx = setup_live_item()
        place_bid(ctx["item"]["id"], ctx["member"], 1000000)
        sale = validate_success(
            api.close_lot(ctx["auction"]["id"], ctx["item"]["id"], AU), 200
        )
        assert sale["winning_bid_cents"] == 1000000
        assert sale["winner_member_id"] == ctx["member"]["id"]
        assert sale["buyer_fee_cents"] == 105000
        assert sale["gate_pass_expires_at"] == "2026-09-04T00:00:00Z"
        assert sale["status"] == "AWAITING_PAYMENT"

    def test_followup_read_reflects_sold_immediately(self, api):
        """PRD §3.4: "A successful close of those sale types moves the vehicle
        `LIVE → SOLD`"

        Design: Corner/consistency_model/immediate_consistency_same_response_reflects_all_mutations
        """
        ctx = setup_closed_sale()
        vehicle = get_success_data(api.get_vehicle(ctx["vehicle"]["id"], AU))
        assert vehicle["status"] == "SOLD"

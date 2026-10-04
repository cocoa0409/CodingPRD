"""Licensing jurisdiction gates, title transferability, error priority, ownership."""
from test_helpers import (
    ApiErrorId,
    create_license,
    create_member,
    create_seller,
    create_yard,
    create_auction,
    get_success_data,
    list_into_auction,
    make_buyer_headers,
    make_seller_agent_headers,
    pay_sale,
    place_bid,
    prepare_vehicle,
    set_clock,
    setup_closed_sale,
    setup_live_item,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

AU = TEST_USERS["auctioneer_headers"]
YO = TEST_USERS["yard_operator_headers"]
TC = TEST_USERS["title_clerk_headers"]


def _dealer_only_live(api):
    """DEALER_ONLY PURE vehicle open in a live auction with two licensed dealers."""
    yard = create_yard(state_code="CA")
    seller = create_seller()
    d1 = create_member(email="d1@x.com", full_name="Dealer One")
    d2 = create_member(email="d2@x.com", full_name="Dealer Two")
    create_license(d1["id"], state_code="CA", license_type="DEALER", expires_on="2026-09-01")
    create_license(d2["id"], state_code="CA", license_type="DEALER", expires_on="2026-09-01")
    vehicle = prepare_vehicle(seller, yard, lot_type="DEALER_ONLY")
    auction = create_auction()
    item = list_into_auction(auction["id"], vehicle["id"])
    get_success_data(api.start_auction(auction["id"], AU))
    item = get_success_data(api.open_lot(auction["id"], item["id"], AU))
    return {"yard": yard, "seller": seller, "d1": d1, "d2": d2, "vehicle": vehicle,
            "auction": auction, "item": item}


class TestLicenseExpiryBoundary:
    def test_license_expiry_boundary_equal_date_is_valid(self, api):
        """PRD §3.7: "expiry is date-granular, and a license whose `expires_on` equals
        the current UTC date of the logical clock is still valid on that date."

        Design: Corner/calculations/license_expiry_boundary_equal_date_is_valid
        """
        ctx = _dealer_only_live(api)
        bid = place_bid(ctx["item"]["id"], ctx["d1"], 1000000)
        assert bid["is_winning"] is True

    def test_license_expired_next_date_rejected(self, api):
        """PRD §3.7: "A bid on a lot whose type is outside the bidder's effective tier
        is rejected with `ERR_LICENSE_REQUIRED` — whether the license is missing,
        issued by the wrong state, revoked, or expired."

        Design: Corner/calculations/license_expiry_boundary_equal_date_is_valid
        """
        ctx = _dealer_only_live(api)
        place_bid(ctx["item"]["id"], ctx["d1"], 1000000)
        set_clock("2026-09-02T00:00:00Z")
        resp = api.place_bid(
            {"auction_item_id": ctx["item"]["id"], "amount_cents": 1025000},
            make_buyer_headers(ctx["d2"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LICENSE_REQUIRED)


class TestExportOnlyTitleGating:
    def test_non_repairable_ca_title_is_export_only_and_blocks_us_buyer(self, api):
        """PRD §3.2: "A `NON_REPAIRABLE` title in Florida or Michigan is
        `NON_TRANSFERABLE`, and `EXPORT_ONLY` elsewhere."
        PRD §3.7: "The title record adds one further bid-time gate: when the vehicle's
        title transferability is `EXPORT_ONLY`, a bid from a US member is rejected with
        `ERR_TITLE_EXPORT_ONLY` — such a vehicle can only be won by an exporter."
        PRD §3.5: "when the title type is `NON_REPAIRABLE` or `PARTS_ONLY` and the
        jurisdiction is Florida or Michigan, the vehicle's `title_brand` is force-set
        to `REBUILT`"

        Design: Corner/endpoints/non_repairable_ca_title_is_export_only_and_blocks_us_buyer
        """
        yard = create_yard(state_code="CA")
        seller = create_seller()
        us_member = create_member(email="us@x.com", full_name="Domestic D", tier="PREMIER")
        de_member = create_member(email="exp@x.com", full_name="Exporter E", country_code="DE")
        vehicle = prepare_vehicle(seller, yard, title_type="NON_REPAIRABLE",
                                  condition_overrides={"primary_damage": "FLOOD",
                                                       "run_and_drive_status": "STATIONARY"})
        title = get_success_data(api.get_vehicle_title(vehicle["id"], TC))[0]
        assert title["transferability"] == "EXPORT_ONLY"
        auction = create_auction()
        item = list_into_auction(auction["id"], vehicle["id"])
        get_success_data(api.start_auction(auction["id"], AU))
        get_success_data(api.open_lot(auction["id"], item["id"], AU))
        resp = api.place_bid(
            {"auction_item_id": item["id"], "amount_cents": 900000},
            make_buyer_headers(us_member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TITLE_EXPORT_ONLY)
        place_bid(item["id"], de_member, 1000000)
        sale = validate_success(api.close_lot(auction["id"], item["id"], AU), 200)
        assert sale["status"] == "AWAITING_PAYMENT"
        vehicle = get_success_data(api.get_vehicle(vehicle["id"], AU))
        assert vehicle["status"] == "SOLD"
        assert vehicle["title_brand"] == "NONE"
        title = get_success_data(api.get_vehicle_title(vehicle["id"], TC))[0]
        assert title["status"] == "TRANSFERRED"

    def test_parts_only_fl_sale_stamps_rebuilt_brand(self, api):
        """PRD §3.2: "A `PARTS_ONLY` title in California or Texas is `NON_TRANSFERABLE`,
        and `EXPORT_ONLY` in every other jurisdiction."
        PRD §3.5: "when the title type is `NON_REPAIRABLE` or `PARTS_ONLY` and the
        jurisdiction is Florida or Michigan, the vehicle's `title_brand` is force-set
        to `REBUILT`"

        Design: Corner/endpoints/parts_only_fl_sale_stamps_rebuilt_brand
        """
        yard = create_yard(state_code="FL", daily_storage_rate_cents=1200, free_storage_days=2)
        seller = create_seller()
        de_member = create_member(email="exp@x.com", full_name="Exporter E",
                                  home_state="FL", country_code="DE")
        vehicle = prepare_vehicle(
            seller, yard, title_type="PARTS_ONLY", lot_type="EXPORT_ONLY",
            condition_overrides={"primary_damage": "FLOOD", "run_and_drive_status": "STATIONARY"},
        )
        title = get_success_data(api.get_vehicle_title(vehicle["id"], TC))[0]
        assert title["transferability"] == "EXPORT_ONLY"
        auction = create_auction()
        item = list_into_auction(auction["id"], vehicle["id"])
        get_success_data(api.start_auction(auction["id"], AU))
        get_success_data(api.open_lot(auction["id"], item["id"], AU))
        place_bid(item["id"], de_member, 1000000)
        sale = validate_success(api.close_lot(auction["id"], item["id"], AU), 200)
        assert sale["status"] == "AWAITING_PAYMENT"
        vehicle = get_success_data(api.get_vehicle(vehicle["id"], AU))
        assert vehicle["title_brand"] == "REBUILT"
        assert vehicle["status"] == "SOLD"
        title = get_success_data(api.get_vehicle_title(vehicle["id"], TC))[0]
        assert title["status"] == "TRANSFERRED"


class TestValidationPriority:
    def test_bid_state_failure_masks_license_failure(self, api):
        """PRD §2.7: "**(7)** state preconditions for the requested transition ...
        **(8)** license and title gating on bids and lot closure
        (`ERR_LICENSE_REQUIRED`, `ERR_MEMBER_SUSPENDED`, `ERR_TITLE_EXPORT_ONLY`,
        `ERR_TITLE_NON_TRANSFERABLE`)"

        Design: Difficulty/priority_pair_validation_conflict/bid_state_failure_masks_license_failure
        """
        yard = create_yard(state_code="CA")
        seller = create_seller()
        dealer = create_member(email="dealer@x.com", full_name="Dealer Dan")
        create_license(dealer["id"], state_code="CA", license_type="DEALER", expires_on="2027-12-31")
        bare = create_member(email="bare@x.com", full_name="Bare Bob")
        vehicle = prepare_vehicle(seller, yard, lot_type="DEALER_ONLY")
        auction = create_auction()
        item = list_into_auction(auction["id"], vehicle["id"])
        get_success_data(api.start_auction(auction["id"], AU))
        get_success_data(api.open_lot(auction["id"], item["id"], AU))
        place_bid(item["id"], dealer, 1000000)
        validate_success(api.close_lot(auction["id"], item["id"], AU), 200)
        # Item now CLOSED; bare member would fail licensing too — state wins.
        resp = api.place_bid(
            {"auction_item_id": item["id"], "amount_cents": 2000000},
            make_buyer_headers(bare["id"]),
        )
        body = resp.json()
        assert body["data"]["error_id"] != "ERR_LICENSE_REQUIRED"
        assert resp.status_code == 409
        assert body["data"]["error_id"] in (
            "ERR_AUCTION_ITEM_NOT_LIVE",
            "ERR_INVALID_REQUEST",
        ), f"expected the item-state error, got {body['data']['error_id']}"

    def test_bid_on_closed_item_rejected_with_state_error(self, api):
        """PRD §3.4: "The bid's `bid_type` is derived from the item's status at
        acceptance: `PRELIM` while the item is `QUEUED`, `LIVE` while it is `LIVE`."
        PRD §2.7: "**(7)** state preconditions for the requested transition
        (`ERR_VEHICLE_INVALID_STATE`, `ERR_VEHICLE_NOT_SALE_READY`,
        `ERR_AUCTION_NOT_SCHEDULED`, `ERR_AUCTION_NOT_LIVE`,
        `ERR_AUCTION_ITEM_NOT_QUEUED`, `ERR_AUCTION_ITEM_NOT_LIVE`"

        Design: Difficulty/priority_pair_validation_conflict/bid_state_failure_masks_license_failure
        """
        yard = create_yard(state_code="CA")
        seller = create_seller()
        dealer = create_member(email="dealer@x.com", full_name="Dealer Dan")
        create_license(dealer["id"], state_code="CA", license_type="DEALER", expires_on="2027-12-31")
        bare = create_member(email="bare@x.com", full_name="Bare Bob")
        vehicle = prepare_vehicle(seller, yard, lot_type="DEALER_ONLY")
        auction = create_auction()
        item = list_into_auction(auction["id"], vehicle["id"])
        get_success_data(api.start_auction(auction["id"], AU))
        get_success_data(api.open_lot(auction["id"], item["id"], AU))
        place_bid(item["id"], dealer, 1000000)
        validate_success(api.close_lot(auction["id"], item["id"], AU), 200)
        # Even a fully-licensed member cannot bid on a CLOSED item: the state gate
        # fires for every caller, licensing or not.
        resp = api.place_bid(
            {"auction_item_id": item["id"], "amount_cents": 2000000},
            make_buyer_headers(dealer["id"]),
        )
        assert resp.status_code == 409
        assert resp.json()["data"]["error_id"] != "ERR_LICENSE_REQUIRED"
        # And the license-only failure is observable on its own while the lot is open.
        ctx2 = setup_live_item(lot_type="DEALER_ONLY", yard_overrides={"state_code": "CA"})
        resp2 = api.place_bid(
            {"auction_item_id": ctx2["item"]["id"], "amount_cents": 500000},
            make_buyer_headers(bare["id"]),
        )
        validate_error(resp2, ApiErrorId.ERR_LICENSE_REQUIRED)

    def test_wrong_amount_on_awaiting_payment_rejected(self, api):
        """PRD §3.5: "The submitted `amount_cents` must equal exactly the sum of
        `winning_bid_cents`, `buyer_fee_cents`, and any winner-side storage fee accrued
        so far on the sale's gate pass — which is zero when no gate pass exists yet or
        none has checked in. Any other amount is rejected with
        `ERR_PAYMENT_AMOUNT_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/payment_state_failure_masks_amount_mismatch
        """
        ctx = setup_closed_sale()
        # Sale is AWAITING_PAYMENT and the amount is wrong: the fiscal gate fires
        # in isolation (state precondition satisfied).
        resp = api.pay_sale(
            ctx["sale"]["id"], {"amount_cents": 1}, make_buyer_headers(ctx["member"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)
        sale = get_success_data(api.get_sale(ctx["sale"]["id"], AU))
        assert sale["status"] == "AWAITING_PAYMENT"

    def test_payment_state_failure_masks_amount_mismatch(self, api):
        """PRD §2.7: "**(7)** state preconditions for the requested transition
        (`ERR_VEHICLE_INVALID_STATE`, `ERR_VEHICLE_NOT_SALE_READY`,
        `ERR_AUCTION_NOT_SCHEDULED`, `ERR_AUCTION_NOT_LIVE`,
        `ERR_AUCTION_ITEM_NOT_QUEUED`, `ERR_AUCTION_ITEM_NOT_LIVE`,
        `ERR_AUCTION_ITEM_ALREADY_LIVE`, `ERR_AUCTION_ITEM_OUT_OF_ORDER`,
        `ERR_SALE_NOT_PENDING_APPROVAL`, `ERR_SALE_NOT_AWAITING_PAYMENT`,
        `ERR_SALE_NOT_CANCELLABLE`, `ERR_GATE_PASS_INVALID_STATE`,
        `ERR_VEHICLE_NOT_CANCELLABLE`)"
        PRD §3.5: "Payment is the buyer's act, on their own sale only, with the sale in
        `AWAITING_PAYMENT` (`ERR_SALE_NOT_AWAITING_PAYMENT`)."

        Design: Difficulty/priority_pair_validation_conflict/payment_state_failure_masks_amount_mismatch
        """
        ctx = setup_closed_sale()
        pay_sale(ctx)  # sale PAID
        resp = api.pay_sale(
            ctx["sale"]["id"], {"amount_cents": 1}, make_buyer_headers(ctx["member"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_SALE_NOT_AWAITING_PAYMENT)
        sale = get_success_data(api.get_sale(ctx["sale"]["id"], AU))
        assert sale["status"] == "PAID"


class TestOwnership:
    def test_buyer_cannot_pay_another_members_sale(self, api):
        """PRD §2.1: "When `X-User-Role` is `Buyer`, `X-User-ID` is the `id` of the
        acting `Member`; ownership checks on any resource that references a `Member` —
        a bid's `member_id`, a sale's `winner_member_id`, a gate pass or export
        document reached through a sale — compare the resource's foreign-key field to
        `X-User-ID`."
        PRD §3.5: "Payment is the buyer's act, on their own sale only"

        Design: Corner/rbac/buyer_cannot_pay_another_members_sale
        """
        ctx = setup_closed_sale()
        other = create_member(email="other@x.com", full_name="Other Buyer")
        resp = api.pay_sale(
            ctx["sale"]["id"], {"amount_cents": 1120000}, make_buyer_headers(other["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        sale = get_success_data(api.get_sale(ctx["sale"]["id"], AU))
        assert sale["status"] == "AWAITING_PAYMENT"

    def test_seller_agent_cannot_approve_another_sellers_sale(self, api):
        """PRD §2.1: "When `X-User-Role` is `SellerAgent`, `X-User-ID` is the `id` of
        the acting `Seller`; operations on vehicles and sales are permitted only when
        the vehicle's `seller_id` equals `X-User-ID` (a mismatch on an on-approval
        decision surfaces as `ERR_SELLER_MISMATCH`)."
        PRD §3.5: "Approval by the `SellerAgent` requires the sale to be
        `PENDING_APPROVAL` and to belong to the acting seller (violations surface as
        `ERR_SALE_NOT_PENDING_APPROVAL` or `ERR_SELLER_MISMATCH`)"

        Design: Corner/rbac/seller_agent_cannot_approve_another_sellers_sale
        """
        ctx = setup_live_item(reserve_price_cents=500000, sale_type="ON_APPROVAL")
        other_seller = create_seller(name="Insurer B")
        place_bid(ctx["item"]["id"], ctx["member"], 300000)
        sale = validate_success(
            api.close_lot(ctx["auction"]["id"], ctx["item"]["id"], AU), 200
        )
        assert sale["status"] == "PENDING_APPROVAL"
        resp = api.approve_sale(sale["id"], make_seller_agent_headers(other_seller["id"]))
        validate_error(resp, ApiErrorId.ERR_SELLER_MISMATCH)
        sale = get_success_data(api.get_sale(sale["id"], AU))
        assert sale["status"] == "PENDING_APPROVAL"

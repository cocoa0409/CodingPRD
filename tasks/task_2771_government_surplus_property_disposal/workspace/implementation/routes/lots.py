"""Auction lot and bidding endpoints (PRD sections 3.6, 3.7)."""
import db as store
from db import db, by_created, iso, parse_date, parse_instant
from errors import ApiError
from middleware import (Fields, bidder_scope, endpoint, list_params,
                        plain_filters, read_body)
from response import collection, created, ok
from services import calc, rollups
from services.enums import BID_STATUS, LOT_STATUS
from services.serialize import view, views


def register(app):

    @app.route("/auction-lots", methods=["POST"])
    @endpoint(["DisposalOfficer"])
    def create_lot(ctx):
        body = read_body()
        f = Fields(body)
        f.string("asset_id", required=True, minlen=1)
        f.string("venue_id", required=True, minlen=1)
        f.instant("opens_at", required=True)
        f.instant("closes_at", required=True)
        f.integer("reserve_price_cents", minv=calc.MIN_RESERVE_CENTS)
        f.done()
        asset = rollups.fetch(db.assets, f["asset_id"], "ERR_ASSET_NOT_FOUND")
        venue = rollups.fetch(db.venues, f["venue_id"], "ERR_VENUE_NOT_FOUND")
        turn_in = db.turn_ins.get(asset["turn_in_id"])
        listable = False
        if asset["disposition_status"] == "AUCTION_ELIGIBLE":
            listable = True
        elif (asset["disposition_status"] == "ASSESSED"
                and turn_in is not None and turn_in["status"] == "ACCEPTED"
                and calc.screening_exempt(asset)):
            listable = True
        if not listable:
            raise ApiError("ERR_ASSET_NOT_DISPOSABLE",
                           "the asset is not eligible for auction listing")
        if venue["status"] != "ACTIVE":
            raise ApiError("ERR_VENUE_CLOSED", "the venue is closed")
        if calc.federal_use_period_active(asset):
            raise ApiError("ERR_FEDERAL_USE_PERIOD_ACTIVE",
                           "the federal use period has not expired")
        opens_at = f["opens_at"]
        closes_at = f["closes_at"]
        overlapping = 0
        for other in rollups.lots_of_venue(venue["id"]):
            if other["status"] not in ("DRAFT", "OPEN"):
                continue
            other_opens = parse_instant(other["opens_at"])
            other_closes = parse_instant(other["closes_at"])
            if opens_at < other_closes and other_opens < closes_at:
                overlapping += 1
        if overlapping >= venue["concurrent_lot_capacity"]:
            raise ApiError("ERR_VENUE_CAPACITY_CONFLICT",
                           "the venue has no concurrent capacity left in this window")
        latest_close = None
        for other in rollups.lots_of_asset(asset["id"]):
            if other["status"] not in ("DRAFT", "OPEN", "CLOSED_MET",
                                       "CLOSED_NO_SALE", "SETTLED"):
                continue
            other_closes = parse_instant(other["closes_at"])
            if latest_close is None or other_closes > latest_close:
                latest_close = other_closes
        if latest_close is not None:
            if opens_at < store.add_days(latest_close, 1):
                raise ApiError("ERR_ASSET_WINDOW_CONFLICT",
                               "the asset's relist cooldown has not elapsed")
        if opens_at < store.db.now or closes_at <= opens_at:
            raise ApiError("ERR_INVALID_WINDOW",
                           "opens_at must be at or after the logical clock and "
                           "closes_at must be strictly after opens_at")
        if f["reserve_price_cents"] is not None:
            reserve = f["reserve_price_cents"]
            source = "OFFICER_OVERRIDE"
        else:
            reserve = calc.auction_reserve(asset["fair_market_value_cents"] or 0)
            source = "COMPUTED"
        position = len(rollups.lots_of_venue(venue["id"])) + 1
        lot = store.base_row()
        lot.update({
            "asset_id": asset["id"],
            "venue_id": venue["id"],
            "lot_number": "%s-%04d" % (venue["venue_code"], position),
            "opens_at": iso(opens_at),
            "closes_at": iso(closes_at),
            "reserve_price_cents": reserve,
            "reserve_source": source,
            "required_deposit_cents": calc.deposit_requirement(reserve),
            "status": "DRAFT",
            "high_bid_cents": 0,
            "bid_count": 0,
            "closed_by_user_id": None,
            "closed_at": None,
        })
        db.lots[lot["id"]] = lot
        asset["disposition_status"] = "LISTED"
        ctx.touch(asset)
        rollups.recompute_venue(venue, ctx)
        return created(view("AuctionLot", lot))

    @app.route("/auction-lots/<lot_id>", methods=["GET"])
    @endpoint(["ProgramAdmin", "DisposalOfficer", "FinanceController", "Bidder"])
    def get_lot(ctx, lot_id):
        lot = rollups.fetch(db.lots, lot_id, "ERR_AUCTION_LOT_NOT_FOUND")
        return ok(view("AuctionLot", lot))

    @app.route("/auction-lots", methods=["GET"])
    @endpoint(["ProgramAdmin", "DisposalOfficer", "FinanceController", "Bidder"])
    def list_lots(ctx):
        filters, limit, offset = list_params({"status": LOT_STATUS})
        plain = plain_filters(["asset_id", "venue_id"])
        rows = by_created(db.lots.values())
        for key, value in filters.items():
            rows = [r for r in rows if r[key] == value]
        for key, value in plain.items():
            rows = [r for r in rows if r[key] == value]
        return collection(views("AuctionLot", rows), limit, offset)

    @app.route("/auction-lots/<lot_id>/open", methods=["POST"])
    @endpoint(["DisposalOfficer"])
    def open_lot(ctx, lot_id):
        read_body()
        lot = rollups.fetch(db.lots, lot_id, "ERR_AUCTION_LOT_NOT_FOUND")
        if lot["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", "only a DRAFT lot may be opened")
        venue = db.venues.get(lot["venue_id"])
        if venue is None or venue["status"] != "ACTIVE":
            raise ApiError("ERR_VENUE_CLOSED", "the venue is closed")
        now = store.db.now
        if now < parse_instant(lot["opens_at"]) or now >= parse_instant(lot["closes_at"]):
            raise ApiError("ERR_INVALID_STATE",
                           "the logical clock lies outside the sale window")
        lot["status"] = "OPEN"
        ctx.touch(lot)
        return ok(view("AuctionLot", lot))

    @app.route("/auction-lots/<lot_id>/bids", methods=["POST"])
    @endpoint(["Bidder"])
    def place_bid(ctx, lot_id):
        body = read_body()
        bidder_scope(ctx, body.get("bidder_id")
                     if isinstance(body.get("bidder_id"), str) else None)
        f = Fields(body)
        f.string("bidder_id", required=True, minlen=1)
        f.integer("amount_cents", required=True, minv=1)
        f.done()
        lot = rollups.fetch(db.lots, lot_id, "ERR_AUCTION_LOT_NOT_FOUND")
        bidder = rollups.fetch(db.bidders, f["bidder_id"], "ERR_BIDDER_NOT_FOUND")
        now = store.db.now
        if (lot["status"] != "OPEN"
                or now < parse_instant(lot["opens_at"])
                or now >= parse_instant(lot["closes_at"])):
            raise ApiError("ERR_LOT_NOT_OPEN",
                           "the lot is not open for bidding")
        if bidder["status"] != "REGISTERED":
            raise ApiError("ERR_BIDDER_NOT_REGISTERED",
                           "only a REGISTERED bidder may bid")
        asset = db.assets.get(lot["asset_id"])
        if asset is not None and asset["is_restricted"]:
            expires = bidder["end_use_certificate_expires_on"]
            if expires is None or parse_date(expires) < store.today():
                raise ApiError("ERR_END_USE_CERTIFICATE_REQUIRED",
                               "a current end-use certificate is required for a "
                               "restricted article")
        amount = f["amount_cents"]
        if amount < lot["reserve_price_cents"]:
            raise ApiError("ERR_BID_BELOW_RESERVE",
                           "the bid is below the lot's reserve price")
        has_active = any(b["status"] == "ACTIVE"
                         for b in rollups.bids_of_lot(lot["id"]))
        if has_active and amount < lot["high_bid_cents"] + calc.MIN_BID_INCREMENT_CENTS:
            raise ApiError("ERR_BID_INCREMENT_NOT_MET",
                           "the bid does not clear the minimum increment")
        if bidder["deposit_held_cents"] < lot["required_deposit_cents"]:
            raise ApiError("ERR_BID_DEPOSIT_INSUFFICIENT",
                           "the bidder's held deposit does not cover the lot's "
                           "deposit requirement")
        bid = store.base_row()
        bid.update({
            "auction_lot_id": lot["id"],
            "bidder_id": bidder["id"],
            "amount_cents": amount,
            "placed_at": iso(store.db.now),
            "status": "ACTIVE",
        })
        db.bids[bid["id"]] = bid
        rollups.recompute_lot(lot, ctx)
        return created(view("Bid", bid))

    @app.route("/auction-lots/<lot_id>/bids", methods=["GET"])
    @endpoint(["ProgramAdmin", "DisposalOfficer", "FinanceController"])
    def list_lot_bids(ctx, lot_id):
        filters, limit, offset = list_params({"status": BID_STATUS})
        lot = rollups.fetch(db.lots, lot_id, "ERR_AUCTION_LOT_NOT_FOUND")
        rows = rollups.bids_of_lot(lot["id"])
        for key, value in filters.items():
            rows = [r for r in rows if r[key] == value]
        rows = sorted(rows, key=lambda r: (-r["amount_cents"], r["created_at"], r["_seq"]))
        return collection(views("Bid", rows), limit, offset)

    @app.route("/auction-lots/<lot_id>/close", methods=["POST"])
    @endpoint(["DisposalOfficer"])
    def close_lot(ctx, lot_id):
        read_body()
        lot = rollups.fetch(db.lots, lot_id, "ERR_AUCTION_LOT_NOT_FOUND")
        if lot["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", "only an OPEN lot may be closed")
        if store.db.now < parse_instant(lot["closes_at"]):
            raise ApiError("ERR_INVALID_STATE",
                           "the sale window has not elapsed")
        bids = rollups.bids_of_lot(lot["id"])
        qualifying = [b for b in bids
                      if b["status"] == "ACTIVE"
                      and b["amount_cents"] >= lot["reserve_price_cents"]]
        lot["closed_by_user_id"] = ctx.user_id
        lot["closed_at"] = iso(store.db.now)
        asset = db.assets.get(lot["asset_id"])
        venue = db.venues.get(lot["venue_id"])
        if qualifying:
            winner = sorted(qualifying,
                            key=lambda b: (-b["amount_cents"], b["placed_at"],
                                           b["created_at"], b["_seq"]))[0]
            lot["status"] = "CLOSED_MET"
            winner["status"] = "WINNING"
            ctx.touch(winner)
            for other in bids:
                if other is winner:
                    continue
                if other["status"] == "ACTIVE":
                    other["status"] = "OUTBID"
                    ctx.touch(other)
            bidder = db.bidders.get(winner["bidder_id"])
            hammer = winner["amount_cents"]
            premium, tax, total = calc.invoice_lines(
                hammer, venue["buyer_premium_pct"], venue["sales_tax_pct"])
            invoice = store.base_row()
            invoice.update({
                "auction_lot_id": lot["id"],
                "bidder_id": winner["bidder_id"],
                "hammer_price_cents": hammer,
                "buyer_premium_cents": premium,
                "sales_tax_cents": tax,
                "total_due_cents": total,
                "amount_paid_cents": 0,
                "deposit_applied_cents": 0,
                "balance_due_cents": total,
                "due_at": iso(store.add_days(parse_instant(lot["closed_at"]),
                                             calc.PAYMENT_TERM_DAYS)),
                "status": "ISSUED",
                "default_reason": None,
                "void_reason": None,
            })
            db.invoices[invoice["id"]] = invoice
            if asset is not None and asset["disposition_status"] == "LISTED":
                asset["disposition_status"] = "SOLD"
                ctx.touch(asset)
            rollups.recompute_lot(lot, ctx)
            if bidder is not None:
                rollups.recompute_bidder_wins(bidder, ctx)
        else:
            lot["status"] = "CLOSED_NO_SALE"
            if asset is not None and asset["disposition_status"] == "LISTED":
                asset["disposition_status"] = "AUCTION_ELIGIBLE"
                ctx.touch(asset)
            rollups.recompute_lot(lot, ctx)
        if venue is not None:
            rollups.recompute_venue(venue, ctx)
        ctx.touch(lot)
        return ok(view("AuctionLot", lot))

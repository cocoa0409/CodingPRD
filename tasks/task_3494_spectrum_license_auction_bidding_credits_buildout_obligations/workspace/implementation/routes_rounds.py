"""Clock rounds and clock bids (PRD §3.5): tiered price increments, live
aggregate demand, the activity requirement, and the auto-advance to the
assignment phase."""
from flask import Blueprint, request

import store
import calcs
import serializers
from errors import ApiError, success
from helpers import (auth, require_role, body, req_present, as_str, as_int,
                     get_or_404, paginate, touch)

bp = Blueprint("rounds", __name__)

ANY_ROLE = ("AuctionAdmin", "Bidder", "IncumbentOperator", "TransferReviewer")


@bp.route("/spectrum-auctions/auctions/<aid>/rounds", methods=["POST"])
def open_next_round(aid):
    _, role = auth()
    require_role(role, ("AuctionAdmin",))
    auction = get_or_404("auctions", aid)
    if auction["status"] != "CLOCK_ACTIVE":
        raise ApiError("ERR_AUCTION_INVALID_STATE", 409,
                       "Opening a round requires CLOCK_ACTIVE")
    last = None
    for r in store.DB["rounds"].values():
        if (r["auction_id"] == aid
                and r["round_number"] == auction["current_round_number"]):
            last = r
            break
    if last is None or last["status"] != "CLOSED":
        raise ApiError("ERR_AUCTION_INVALID_STATE", 409,
                       "The previous round must be CLOSED before the next "
                       "opens")
    last_demand = {(d["area_code"], d["category"]): d["demand_quantity"]
                   for d in last["aggregate_demand"]}
    prices, demand = [], []
    for p in last["prices"]:
        key = (p["area_code"], p["category"])
        block = calcs.find_block_by_category(auction["band_plan_id"],
                                             p["category"])
        d = last_demand.get(key, 0)
        pct = calcs.increment_pct(d, block["supply_per_area"])
        if pct is None:
            continue  # product closes; excluded from the new round forever
        prices.append({
            "area_code": p["area_code"],
            "category": p["category"],
            "price_cents": calcs.round_half_up_ratio(
                p["price_cents"] * (100 + pct), 100),
        })
        demand.append({"area_code": p["area_code"], "category": p["category"],
                       "demand_quantity": 0})
    number = last["round_number"] + 1
    rnd = store.stamp_new({
        "id": store.new_id(),
        "auction_id": aid,
        "round_number": number,
        "stage": calcs.stage_of(number),
        "prices": prices,
        "aggregate_demand": demand,
        "status": "OPEN",
    })
    store.DB["rounds"][rnd["id"]] = rnd
    auction["current_round_number"] = number
    touch(auction)
    return success(serializers.clock_round(rnd), 201)


@bp.route("/spectrum-auctions/auctions/<aid>/rounds", methods=["GET"])
def list_rounds(aid):
    auth()
    get_or_404("auctions", aid)
    items = [r for r in store.DB["rounds"].values() if r["auction_id"] == aid]
    page, meta = paginate(items)
    return success([serializers.clock_round(r) for r in page], 200, meta)


@bp.route("/spectrum-auctions/rounds/<rid>", methods=["GET"])
def get_round(rid):
    auth()
    return success(serializers.clock_round(get_or_404("rounds", rid)), 200)


@bp.route("/spectrum-auctions/rounds/<rid>/close", methods=["POST"])
def close_round(rid):
    _, role = auth()
    require_role(role, ("AuctionAdmin",))
    rnd = get_or_404("rounds", rid)
    if rnd["status"] != "OPEN":
        raise ApiError("ERR_ROUND_NOT_OPEN", 409, "Round is not OPEN")
    auction = store.DB["auctions"][rnd["auction_id"]]
    if auction["status"] != "CLOCK_ACTIVE":
        raise ApiError("ERR_AUCTION_INVALID_STATE", 409,
                       "Closing a round requires CLOCK_ACTIVE")
    # Finalize demand: SUBMITTED bids become PROCESSED (the live-maintained
    # aggregate_demand already reflects exactly those bids).
    for bid in store.DB["bids"].values():
        if bid["round_id"] == rid and bid["status"] == "SUBMITTED":
            bid["status"] = "PROCESSED"
            touch(bid)
    rnd["status"] = "CLOSED"
    touch(rnd)
    # Activity requirement (pinned evaluation order: bids were validated
    # against the eligibility in force during the round; reductions apply to
    # subsequent rounds only). Only QUALIFIED applicants are evaluated.
    required_milli = (calcs.STAGE1_ACTIVITY_MILLI if rnd["stage"] == 1
                      else calcs.STAGE2_ACTIVITY_MILLI)
    for appl in store.DB["applicants"].values():
        if appl["auction_id"] != auction["id"] or appl["status"] != "QUALIFIED":
            continue
        activity = sum(
            b["units_snapshot"] for b in store.DB["bids"].values()
            if b["round_id"] == rid and b["bidder_applicant_id"] == appl["id"]
            and b["status"] == "PROCESSED")
        if activity * 1000 >= required_milli * appl["eligibility_units"]:
            continue  # inclusive boundary: eligibility unchanged
        appl["eligibility_units"] = (activity * 1000) // required_milli
        touch(appl)
    # Auto-advance: demand at or below supply for every product still open.
    supply_by_category = {
        b["category"]: b["supply_per_area"]
        for b in calcs.blocks_of_plan(auction["band_plan_id"])}
    demand = {(d["area_code"], d["category"]): d["demand_quantity"]
              for d in rnd["aggregate_demand"]}
    advance = all(
        demand.get((p["area_code"], p["category"]), 0)
        <= supply_by_category[p["category"]]
        for p in rnd["prices"])
    if advance:
        winners = [{
            "applicant_id": b["bidder_applicant_id"],
            "area_code": b["area_code"],
            "category": b["category"],
            "quantity": b["quantity"],
        } for b in sorted(store.DB["bids"].values(), key=store.created_key)
            if b["round_id"] == rid and b["status"] == "PROCESSED"
            and b["quantity"] > 0]
        auction["winners"] = winners
        auction["final_round_id"] = rid
        auction["status"] = "ASSIGNMENT_PHASE"
        touch(auction)
    return success(serializers.clock_round(rnd), 200)


@bp.route("/spectrum-auctions/rounds/<rid>/bids", methods=["POST"])
def place_bid(rid):
    uid, role = auth()
    require_role(role, ("Bidder",))
    b = body()
    area_code = as_str(req_present(b, "area_code"), "area_code")
    category = as_str(req_present(b, "category"), "category")
    quantity = as_int(req_present(b, "quantity"), "quantity", minimum=1)
    rnd = get_or_404("rounds", rid)
    auction = store.DB["auctions"][rnd["auction_id"]]
    area = calcs.find_area_by_code(auction["band_plan_id"], area_code)
    block = calcs.find_block_by_category(auction["band_plan_id"], category)
    if area is None or block is None:
        raise ApiError("ERR_PRODUCT_NOT_FOUND", 404,
                       "The (area_code, category) product is not part of the "
                       "auction's band plan")
    # The bid's bidder is always the caller: the caller must be a QUALIFIED
    # applicant of this auction.
    bidder = store.DB["applicants"].get(uid)
    if bidder is None or bidder["auction_id"] != auction["id"]:
        raise ApiError("ERR_APPLICANT_INVALID_STATE", 409,
                       "The caller is not an applicant of this auction")
    if rnd["status"] != "OPEN":
        raise ApiError("ERR_ROUND_NOT_OPEN", 409, "Round is not OPEN")
    if auction["status"] != "CLOCK_ACTIVE":
        raise ApiError("ERR_AUCTION_INVALID_STATE", 409,
                       "Bids require CLOCK_ACTIVE")
    if bidder["status"] != "QUALIFIED":
        raise ApiError("ERR_APPLICANT_INVALID_STATE", 409,
                       "Only QUALIFIED applicants may bid")
    in_prices = any(p["area_code"] == area_code and p["category"] == category
                    for p in rnd["prices"])
    if not in_prices:
        raise ApiError("ERR_PRODUCT_CLOSED", 409,
                       "The product is closed in this round")
    if quantity > block["supply_per_area"]:
        raise ApiError("ERR_SUPPLY_EXCEEDED", 422,
                       "Bid quantity exceeds supply_per_area")
    for existing in store.DB["bids"].values():
        if (existing["round_id"] == rid
                and existing["bidder_applicant_id"] == bidder["id"]
                and existing["area_code"] == area_code
                and existing["category"] == category
                and existing["status"] == "SUBMITTED"):
            raise ApiError("ERR_DUPLICATE_BID", 409,
                           "A SUBMITTED bid already exists for this round, "
                           "bidder, and product")
    units = quantity * calcs.bidding_units(block, area)
    cumulative = units + sum(
        x["units_snapshot"] for x in store.DB["bids"].values()
        if x["round_id"] == rid and x["bidder_applicant_id"] == bidder["id"]
        and x["status"] == "SUBMITTED")
    if cumulative > bidder["eligibility_units"]:
        raise ApiError("ERR_BID_EXCEEDS_ELIGIBILITY", 422,
                       "Cumulative round activity exceeds eligibility_units")
    bid = store.stamp_new({
        "id": store.new_id(),
        "round_id": rid,
        "bidder_applicant_id": bidder["id"],
        "area_code": area_code,
        "category": category,
        "quantity": quantity,
        "units_snapshot": units,
        "status": "SUBMITTED",
    })
    store.DB["bids"][bid["id"]] = bid
    for entry in rnd["aggregate_demand"]:
        if entry["area_code"] == area_code and entry["category"] == category:
            entry["demand_quantity"] += quantity
            break
    touch(rnd)
    return success(serializers.bid(bid), 201)


@bp.route("/spectrum-auctions/rounds/<rid>/bids", methods=["GET"])
def list_round_bids(rid):
    auth()
    get_or_404("rounds", rid)
    items = [b for b in store.DB["bids"].values() if b["round_id"] == rid]
    bidder_id = request.args.get("bidder_applicant_id")
    if bidder_id is not None:
        items = [b for b in items if b["bidder_applicant_id"] == bidder_id]
    page, meta = paginate(items)
    return success([serializers.bid(b) for b in page], 200, meta)


@bp.route("/spectrum-auctions/applicants/<aid>/bids", methods=["GET"])
def list_applicant_bids(aid):
    auth()
    get_or_404("applicants", aid)
    items = [b for b in store.DB["bids"].values()
             if b["bidder_applicant_id"] == aid]
    round_id = request.args.get("round_id")
    if round_id is not None:
        items = [b for b in items if b["round_id"] == round_id]
    page, meta = paginate(items)
    return success([serializers.bid(b) for b in page], 200, meta)

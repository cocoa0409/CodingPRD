"""Auctions and the auction phase machine (PRD §3.2, §3.4, §3.6)."""
from flask import Blueprint

import store
import calcs
import serializers
from errors import ApiError, success
from helpers import (auth, require_role, body, req_present, as_str, as_enum,
                     as_datetime, get_or_404, paginate, touch)

bp = Blueprint("auctions", __name__)

ANY_ROLE = ("AuctionAdmin", "Bidder", "IncumbentOperator", "TransferReviewer")
PHASE_ACTIONS = ("OPEN_APPLICATIONS", "BEGIN_QUIET_PERIOD", "POSTPONE",
                 "START_CLOCK", "PAUSE_CLOCK", "RESUME_CLOCK",
                 "COMPLETE_ASSIGNMENT")


@bp.route("/spectrum-auctions/auctions", methods=["POST"])
def create_auction():
    _, role = auth()
    require_role(role, ("AuctionAdmin",))
    b = body()
    plan_id = as_str(req_present(b, "band_plan_id"), "band_plan_id")
    name = as_str(req_present(b, "name"), "name")
    deadline = as_datetime(req_present(b, "application_deadline"),
                           "application_deadline")
    plan = get_or_404("band_plans", plan_id)
    if plan["status"] != "PUBLISHED":
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Auctions require a PUBLISHED band plan")
    auction = store.stamp_new({
        "id": store.new_id(),
        "band_plan_id": plan_id,
        "name": name,
        "application_deadline": deadline,
        "status": "DRAFT",
        "current_round_number": 0,
        "total_proceeds_cents": 0,
        "forfeited_deposits_cents": 0,
        "available_supply": [],
        "winners": [],
        "final_round_id": None,
    })
    store.DB["auctions"][auction["id"]] = auction
    return success(serializers.auction(auction), 201)


@bp.route("/spectrum-auctions/auctions/<aid>", methods=["GET"])
def get_auction(aid):
    auth()
    return success(serializers.auction(get_or_404("auctions", aid)), 200)


@bp.route("/spectrum-auctions/band-plans/<pid>/auctions", methods=["GET"])
def list_auctions_of_plan(pid):
    auth()
    get_or_404("band_plans", pid)
    items = [a for a in store.DB["auctions"].values()
             if a["band_plan_id"] == pid]
    page, meta = paginate(items)
    return success([serializers.auction(a) for a in page], 200, meta)


# --- phase machine side effects -------------------------------------------------
def _start_clock(auction):
    plan_id = auction["band_plan_id"]
    prices, demand, supply = [], [], []
    for area, block in calcs.products_of_plan(plan_id):
        entry = {"area_code": area["area_code"], "category": block["category"]}
        prices.append(dict(entry, price_cents=calcs.opening_price(block, area)))
        demand.append(dict(entry, demand_quantity=0))
        supply.append(dict(entry, available=block["supply_per_area"]))
    round1 = store.stamp_new({
        "id": store.new_id(),
        "auction_id": auction["id"],
        "round_number": 1,
        "stage": 1,
        "prices": prices,
        "aggregate_demand": demand,
        "status": "OPEN",
    })
    store.DB["rounds"][round1["id"]] = round1
    auction["available_supply"] = supply
    auction["current_round_number"] = 1
    for appl in store.DB["applicants"].values():
        if appl["auction_id"] == auction["id"] and appl["status"] == "QUALIFIED":
            appl["initial_eligibility_units"] = appl["eligibility_units"]
            touch(appl)
    auction["status"] = "CLOCK_ACTIVE"
    touch(auction)


def _complete_assignment(auction):
    winners = auction["winners"]
    bids_by_key = {}
    for ab in store.DB["assignment_bids"].values():
        if ab["auction_id"] == auction["id"] and ab["status"] == "SUBMITTED":
            bids_by_key[(ab["bidder_applicant_id"], ab["area_code"],
                         ab["category"])] = ab
    # Precondition: every winner tuple has a SUBMITTED assignment bid; no
    # zero-amount default fallback. Check everything before mutating anything.
    for w in winners:
        if (w["applicant_id"], w["area_code"], w["category"]) not in bids_by_key:
            raise ApiError("ERR_ASSIGNMENT_BIDS_INCOMPLETE", 409,
                           "Every winner requires a SUBMITTED assignment bid")
    final_round = store.DB["rounds"][auction["final_round_id"]]
    posted = {(p["area_code"], p["category"]): p["price_cents"]
              for p in final_round["prices"]}

    # Group winner tuples per product, rank by amount_cents DESC, tie-break
    # assignment-bid created_at ASC (creation sequence breaks exact ties,
    # never id).
    per_product = {}
    for w in winners:
        key = (w["area_code"], w["category"])
        ab = bids_by_key[(w["applicant_id"], w["area_code"], w["category"])]
        per_product.setdefault(key, []).append((w, ab))

    for (area_code, category), entries in per_product.items():
        entries.sort(key=lambda pair: (-pair[1]["amount_cents"],
                                       pair[1]["created_at"],
                                       pair[1]["_seq"]))
        area = calcs.find_area_by_code(auction["band_plan_id"], area_code)
        next_index = 0
        created_here = 0
        for w, ab in entries:
            holder = store.DB["applicants"][w["applicant_id"]]
            money = calcs.settlement_fields(posted[(area_code, category)],
                                            ab["amount_cents"],
                                            holder["credit_pct"])
            for _ in range(w["quantity"]):
                license_ = store.stamp_new({
                    "id": store.new_id(),
                    "auction_id": auction["id"],
                    "area_id": area["id"],
                    "area_code": area_code,
                    "category": category,
                    "frequency_block_index": next_index,
                    "holder_applicant_id": w["applicant_id"],
                    "credit_pct": holder["credit_pct"],
                    "gross_clock_price_cents": posted[(area_code, category)],
                    "assignment_bid_cents": ab["amount_cents"],
                    "gross_final_price_cents": money["gross_final_price_cents"],
                    "provisional_net_price_cents":
                        money["provisional_net_price_cents"],
                    "net_price_cents": money["net_price_cents"],
                    "credit_amount_cents": money["credit_amount_cents"],
                    "paid_cents": 0,
                    "grant_date": None,
                    "term_end": None,
                    "payment_deadline": store.add_days(
                        store.now(), calcs.PAYMENT_DEADLINE_DAYS),
                    "active_lease_start": None,
                    "active_lease_end": None,
                    "leased_to_applicant_id": None,
                    "relocation_share_owed_cents": 0,
                    "status": "PENDING_PAYMENT",
                })
                store.DB["licenses"][license_["id"]] = license_
                # Pinned rounding order: round each license to cents FIRST,
                # then sum.
                auction["total_proceeds_cents"] += license_["net_price_cents"]
                next_index += 1
                created_here += 1
            ab["status"] = "APPLIED"
            touch(ab)
        for entry in auction["available_supply"]:
            if (entry["area_code"] == area_code
                    and entry["category"] == category):
                entry["available"] -= created_here
                break
    auction["status"] = "CLOSED"
    touch(auction)


@bp.route("/spectrum-auctions/auctions/<aid>/phase", methods=["POST"])
def drive_phase(aid):
    _, role = auth()
    require_role(role, ("AuctionAdmin",))
    b = body()
    action = as_enum(req_present(b, "action"), "action", PHASE_ACTIONS)
    auction = get_or_404("auctions", aid)
    status = auction["status"]

    def bad_state():
        raise ApiError("ERR_AUCTION_INVALID_STATE", 409,
                       "Auction phase transition %s is not available from %s"
                       % (action, status))

    if action == "OPEN_APPLICATIONS":
        if status != "DRAFT":
            bad_state()
        auction["status"] = "APPLICATION_OPEN"
        touch(auction)
    elif action == "BEGIN_QUIET_PERIOD":
        if status != "APPLICATION_OPEN":
            bad_state()
        if store.now() < auction["application_deadline"]:
            raise ApiError("ERR_APPLICATION_DEADLINE_NOT_PASSED", 409,
                           "The application deadline has not passed")
        auction["status"] = "QUIET_PERIOD"
        touch(auction)
    elif action == "POSTPONE":
        if status != "QUIET_PERIOD":
            bad_state()
        auction["status"] = "APPLICATION_OPEN"
        touch(auction)
    elif action == "START_CLOCK":
        if status != "QUIET_PERIOD":
            bad_state()
        qualified = [a for a in store.DB["applicants"].values()
                     if a["auction_id"] == aid and a["status"] == "QUALIFIED"]
        if not qualified:
            raise ApiError("ERR_NO_QUALIFIED_BIDDERS", 422,
                           "START_CLOCK requires at least one QUALIFIED "
                           "applicant")
        _start_clock(auction)
    elif action == "PAUSE_CLOCK":
        if status != "CLOCK_ACTIVE":
            bad_state()
        auction["status"] = "CLOCK_PAUSED"
        touch(auction)
    elif action == "RESUME_CLOCK":
        if status != "CLOCK_PAUSED":
            bad_state()
        auction["status"] = "CLOCK_ACTIVE"
        touch(auction)
    else:  # COMPLETE_ASSIGNMENT
        if status != "ASSIGNMENT_PHASE":
            bad_state()
        _complete_assignment(auction)
    return success(serializers.auction(auction), 200)

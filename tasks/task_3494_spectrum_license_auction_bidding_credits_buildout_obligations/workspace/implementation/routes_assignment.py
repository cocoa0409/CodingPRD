"""Assignment-phase sealed bids (PRD §3.6)."""
from flask import Blueprint

import store
import calcs
import serializers
from errors import ApiError, success
from helpers import (auth, require_role, body, req_present, as_str, as_int,
                     get_or_404, paginate)

bp = Blueprint("assignment", __name__)


@bp.route("/spectrum-auctions/auctions/<aid>/assignment-bids", methods=["POST"])
def file_assignment_bid(aid):
    uid, role = auth()
    require_role(role, ("Bidder",))
    b = body()
    area_code = as_str(req_present(b, "area_code"), "area_code")
    category = as_str(req_present(b, "category"), "category")
    amount = as_int(req_present(b, "amount_cents"), "amount_cents", minimum=0)
    auction = get_or_404("auctions", aid)
    if (calcs.find_area_by_code(auction["band_plan_id"], area_code) is None
            or calcs.find_block_by_category(auction["band_plan_id"], category)
            is None):
        raise ApiError("ERR_PRODUCT_NOT_FOUND", 404,
                       "The (area_code, category) product is not part of the "
                       "auction's band plan")
    if auction["status"] != "ASSIGNMENT_PHASE":
        raise ApiError("ERR_AUCTION_INVALID_STATE", 409,
                       "Assignment bids require ASSIGNMENT_PHASE")
    for existing in store.DB["assignment_bids"].values():
        if (existing["auction_id"] == aid
                and existing["bidder_applicant_id"] == uid
                and existing["area_code"] == area_code
                and existing["category"] == category):
            raise ApiError("ERR_DUPLICATE_ASSIGNMENT_BID", 409,
                           "An assignment bid already exists for this bidder "
                           "and product")
    won = any(w["applicant_id"] == uid and w["area_code"] == area_code
              and w["category"] == category for w in auction["winners"])
    if not won:
        raise ApiError("ERR_NOT_A_WINNER", 403,
                       "The caller is not a recorded winner of this product")
    ab = store.stamp_new({
        "id": store.new_id(),
        "auction_id": aid,
        "bidder_applicant_id": uid,
        "area_code": area_code,
        "category": category,
        "amount_cents": amount,
        "status": "SUBMITTED",
    })
    store.DB["assignment_bids"][ab["id"]] = ab
    return success(serializers.assignment_bid(ab), 201)


@bp.route("/spectrum-auctions/auctions/<aid>/assignment-bids", methods=["GET"])
def list_assignment_bids(aid):
    auth()
    get_or_404("auctions", aid)
    items = [b for b in store.DB["assignment_bids"].values()
             if b["auction_id"] == aid]
    page, meta = paginate(items)
    return success([serializers.assignment_bid(b) for b in page], 200, meta)


@bp.route("/spectrum-auctions/applicants/<aid>/assignment-bids",
          methods=["GET"])
def list_applicant_assignment_bids(aid):
    auth()
    get_or_404("applicants", aid)
    items = [b for b in store.DB["assignment_bids"].values()
             if b["bidder_applicant_id"] == aid]
    page, meta = paginate(items)
    return success([serializers.assignment_bid(b) for b in page], 200, meta)

"""The operations run and the getaway market."""

from flask import Blueprint

import shapes
from authz import authenticate, require_acting_identity, require_owner
from errors import ApiError
from response import object_response
from routes.common import ENUM, FK, listing, one, read
from services import ledger
from services import matching
from store import db, serialize, touch, OFFER_STATUSES, RUN_STATUSES

bp = Blueprint("runs", __name__)

ALL_ROLES = ["Member", "ResortManager", "NetworkOperator", "DisputeAnalyst"]
RUN_READERS = ["NetworkOperator", "ResortManager", "DisputeAnalyst"]


@bp.route("/matching-runs", methods=["POST"])
def create_matching_run():
    caller = authenticate(["NetworkOperator"])
    payload = shapes.body()
    note = shapes.take_string(payload, "note", required=False)
    require_acting_identity(caller)
    run = matching.execute(note)
    return object_response(serialize(run), 201)


@bp.route("/matching-runs/<run_id>", methods=["GET"])
def get_matching_run(run_id):
    read(RUN_READERS)
    return one(shapes.find_run(run_id))


@bp.route("/matching-runs", methods=["GET"])
def list_matching_runs():
    return listing(RUN_READERS, db.matching_runs,
                   [("status", "status", ENUM, RUN_STATUSES)], order="run_sequence")


# ---------------------------------------------------------------------------
# getaway offers
# ---------------------------------------------------------------------------
@bp.route("/getaway-offers/<offer_id>", methods=["GET"])
def get_getaway_offer(offer_id):
    read(ALL_ROLES)
    return one(shapes.find_offer(offer_id))


@bp.route("/getaway-offers", methods=["GET"])
def list_getaway_offers():
    return listing(ALL_ROLES, db.getaway_offers, [
        ("deposit_id", "deposit_id", FK, shapes.find_deposit),
        ("booked_by_member_id", "booked_by_member_id", FK, shapes.find_member),
        ("created_by_run_id", "created_by_run_id", "text", None),
        ("status", "status", ENUM, OFFER_STATUSES),
    ])


@bp.route("/getaway-offers/<offer_id>/bookings", methods=["POST"])
def book_getaway_offer(offer_id):
    caller = authenticate(["Member"])
    payload = shapes.body()
    member_id = shapes.take_id(payload, "member_id")
    require_acting_identity(caller)
    offer = shapes.find_offer(offer_id)
    member = shapes.find_member(member_id)
    require_owner(caller, member["id"])
    if offer["status"] != "LISTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if member["enrollment_status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE")
    deposit = db.deposits[offer["deposit_id"]]
    if deposit["member_id"] == member["id"]:
        raise ApiError("ERR_GETAWAY_SELF_BOOKING")
    if member["wallet_credit_cents"] < offer["list_price_cents"]:
        raise ApiError("ERR_INSUFFICIENT_WALLET_CREDIT")
    offer["status"] = "BOOKED"
    offer["booked_by_member_id"] = member["id"]
    offer["booked_at"] = db.now_iso()
    touch(offer)
    deposit["rental_status"] = "RENTED"
    touch(deposit)
    ledger.move_cash(member, "GETAWAY_BOOKING_PAYMENT", "GETAWAY_OFFER", offer["id"],
                     "Cash rental of an unmatched week from the getaway market.",
                     -offer["list_price_cents"])
    return one(offer)


@bp.route("/getaway-offers/<offer_id>/withdrawal", methods=["POST"])
def withdraw_getaway_offer(offer_id):
    caller = authenticate(["NetworkOperator"])
    shapes.body()
    require_acting_identity(caller)
    offer = shapes.find_offer(offer_id)
    if offer["status"] != "LISTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    offer["status"] = "WITHDRAWN"
    touch(offer)
    deposit = db.deposits[offer["deposit_id"]]
    deposit["rental_status"] = "NOT_LISTED"
    touch(deposit)
    owner = db.members[deposit["member_id"]]
    ledger.credit_power(owner, "DEPOSIT_CREDIT", "DEPOSIT", deposit["id"],
                        "Listing pulled from the getaway market; remaining power re-credited.",
                        deposit["remaining_power"])
    return one(offer)

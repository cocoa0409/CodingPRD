"""Network-wide bid listing, bid read and withdrawal."""

from flask import Blueprint, request

import auth
import envelope
import serializers
import store
from errors import ERR_BID_NOT_FOUND, ERR_BID_NOT_SUBMITTED, fail
from services import loads as load_svc

bp = Blueprint("bids", __name__)


@bp.route("/network/bids", methods=["GET"])
def list_bids():
    auth.require_roles("NetworkAdmin", "MemberFoodBank")
    rows = store.ordered(store.bids.values())
    load_id = request.args.get("load_id")
    if load_id:
        rows = [b for b in rows if b["load_id"] == load_id]
    member_id = request.args.get("member_id")
    if member_id:
        rows = [b for b in rows if b["member_id"] == member_id]
    status_filter = request.args.get("bid_status")
    if status_filter:
        rows = [b for b in rows if b["bid_status"] == status_filter]
    page, limit, offset, total = auth.paginate(rows)
    return envelope.ok_array([serializers.bid(b) for b in page], limit, offset, total)


@bp.route("/network/bids/<bid_id>", methods=["GET"])
def read_bid(bid_id):
    auth.require_roles("NetworkAdmin", "MemberFoodBank")
    bid = store.bids.get(bid_id)
    if bid is None:
        fail(ERR_BID_NOT_FOUND, "no load bid matches id %s" % bid_id)
    return envelope.ok_object(serializers.bid(bid))


@bp.route("/network/bids/<bid_id>/withdraw", methods=["POST"])
def withdraw_bid(bid_id):
    user_id, role = auth.require_roles("MemberFoodBank", "NetworkAdmin")
    bid = store.bids.get(bid_id)
    if bid is None:
        fail(ERR_BID_NOT_FOUND, "no load bid matches id %s" % bid_id)
    auth.require_owning_member(user_id, role, bid["member_id"])
    if bid["bid_status"] != "SUBMITTED":
        fail(ERR_BID_NOT_SUBMITTED, "only a SUBMITTED bid may be withdrawn")

    member = store.members.get(bid["member_id"])
    if member is not None:
        load_svc.withdraw_bid(bid, member)
    return envelope.ok_object(serializers.bid(bid))

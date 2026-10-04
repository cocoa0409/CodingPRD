"""TipRecord endpoints (PRD 3.10)."""
from db import db
from errors import invalid_request, invalid_state, raise_error
from middleware import (
    require_auth,
    body_json,
    get_int,
    pagination_params,
    sort_by_created,
)
from response import success_object, success_array
from serializers import tip_record as ser_tip
from services import touch, get_location, get_tip_nested
from . import tips_bp

TIP_STATUSES = ["RECORDED", "SETTLED", "VOIDED"]
TIP_READ_ROLES = ["ShiftManager", "Carhop", "PlatformAdmin"]


@tips_bp.route("/locations/<locationId>/tip-records", methods=["GET"])
def list_tips(locationId):
    require_auth(TIP_READ_ROLES)
    from flask import request

    loc = get_location(locationId)
    carhop_id = request.args.get("carhop_id")
    status = request.args.get("status")
    order_id = request.args.get("order_id")
    if status is not None and status not in TIP_STATUSES:
        invalid_request("status must be RECORDED, SETTLED, or VOIDED")
    tips = []
    for t in db.tip_records.values():
        o = db.orders.get(t["order_id"])
        if o is None or o["location_id"] != loc["id"]:
            continue
        tips.append(t)
    if carhop_id is not None:
        tips = [t for t in tips if t["carhop_id"] == carhop_id]
    if status is not None:
        tips = [t for t in tips if t["status"] == status]
    if order_id is not None:
        tips = [t for t in tips if t["order_id"] == order_id]
    tips = sort_by_created(tips)
    limit, offset = pagination_params()
    total = len(tips)
    page = tips[offset : offset + limit]
    return success_array([ser_tip(t) for t in page], limit, offset, total)


@tips_bp.route("/locations/<locationId>/tip-records/<tipId>/settle", methods=["POST"])
def settle_tip(locationId, tipId):
    require_auth(["ShiftManager"])
    loc, tip = get_tip_nested(locationId, tipId)
    body = body_json()
    adjusted = get_int(body, "adjusted_tip_cents")
    if tip["status"] != "RECORDED":
        invalid_state("Tip record is not RECORDED")
    if adjusted is not None:
        if adjusted < 0:
            invalid_request("adjusted_tip_cents must be >= 0")
        tip["adjusted_tip_cents"] = adjusted
        tip["tip_cents"] = adjusted
    tip["status"] = "SETTLED"
    touch(tip)
    if tip["carhop_id"] is not None:
        carhop = db.carhops.get(tip["carhop_id"])
        if carhop is not None:
            carhop["tips_outstanding_cents"] -= tip["tip_cents"]
            carhop["tips_settled_cents"] += tip["tip_cents"]
            touch(carhop)
    return success_object(ser_tip(tip))

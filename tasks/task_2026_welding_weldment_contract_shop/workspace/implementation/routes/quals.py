"""Welder qualification routes (nested)."""

from flask import Blueprint, request

from db import db
from errors import (
    ApiError, ERR_QUAL_NOT_LAPSED, ERR_WELDER_TERMINATED, ERR_WPS_NOT_APPROVED,
    invalid_request, invalid_state,
)
from helpers import json_body, require_fields, parse_datetime, paginate, PROCESSES
from middleware import require_roles, require_any
from response import success_object, success_list
from serializers import qualification_out
from services import (
    stamp_new, make_versioned, mutate, get_shop, get_welder, get_wps, get_qual,
    compute_continuity_expiry, recompute_welder_status,
)

bp = Blueprint("quals", __name__)


@bp.route("/weld-shop/shops/<shop_id>/welder-qualifications", methods=["POST"])
@require_roles("QCManager")
def create_qualification(user_id, role, shop_id):
    shop = get_shop(shop_id)
    body = json_body()
    require_fields(body, ["welder_id", "wps_id", "process", "qualified_at_utc"])
    welder = get_welder(shop_id, body["welder_id"])
    wps = get_wps(shop_id, body["wps_id"])
    if body["process"] not in PROCESSES:
        raise invalid_request("process must be one of SMAW, GMAW, FCAW, GTAW, SAW")
    if body["process"] != wps["process"]:
        raise invalid_request("Qualification process must match the WPS process")
    qualified_at = parse_datetime(body["qualified_at_utc"], "qualified_at_utc")
    qual = stamp_new({
        "shop_id": shop["id"],
        "welder_id": welder["id"],
        "wps_id": wps["id"],
        "process": body["process"],
        "qualified_at_utc": qualified_at,
        "last_weld_at_utc": qualified_at,
        "continuity_expires_at_utc": compute_continuity_expiry(qualified_at, qualified_at),
        "status": "QUALIFIED",
    })
    make_versioned(qual)
    db.qualifications[qual["id"]] = qual
    return success_object(qualification_out(qual), status=201)


@bp.route("/weld-shop/shops/<shop_id>/welder-qualifications", methods=["GET"])
@require_any
def list_qualifications(user_id, role, shop_id):
    shop = get_shop(shop_id)
    records = [q for q in db.qualifications.values() if q["shop_id"] == shop["id"]]
    for param in ("welder_id", "wps_id"):
        value = request.args.get(param)
        if value is not None:
            records = [q for q in records if q.get(param) == value]
    page, limit, offset, total = paginate(records)
    return success_list([qualification_out(q) for q in page], limit, offset, total)


@bp.route("/weld-shop/shops/<shop_id>/welder-qualifications/<qual_id>", methods=["GET"])
@require_any
def get_qualification(user_id, role, shop_id, qual_id):
    get_shop(shop_id)
    return success_object(qualification_out(get_qual(shop_id, qual_id)))


@bp.route("/weld-shop/shops/<shop_id>/welder-qualifications/<qual_id>/requalify", methods=["POST"])
@require_roles("QCManager")
def requalify(user_id, role, shop_id, qual_id):
    shop = get_shop(shop_id)
    qual = get_qual(shop_id, qual_id)
    if qual["status"] != "LAPSED":
        raise ApiError(ERR_QUAL_NOT_LAPSED, 409, "Requalify requires LAPSED status")
    welder = db.welders.get(qual["welder_id"])
    if welder is not None and welder["status"] == "TERMINATED":
        raise ApiError(ERR_WELDER_TERMINATED, 422, "Welder is TERMINATED")
    wps = db.wps.get(qual["wps_id"])
    if wps is None or wps["status"] != "APPROVED":
        raise ApiError(ERR_WPS_NOT_APPROVED, 422,
                       "Referenced WPS must be APPROVED and not SUPERSEDED")
    now = shop["current_utc"]
    qual["qualified_at_utc"] = now
    qual["last_weld_at_utc"] = now
    qual["continuity_expires_at_utc"] = compute_continuity_expiry(now, now)
    qual["status"] = "QUALIFIED"
    mutate(qual)
    if welder is not None:
        recompute_welder_status(welder)
    return success_object(qualification_out(qual))


@bp.route("/weld-shop/shops/<shop_id>/welder-qualifications/<qual_id>/revoke", methods=["POST"])
@require_roles("QCManager")
def revoke(user_id, role, shop_id, qual_id):
    get_shop(shop_id)
    qual = get_qual(shop_id, qual_id)
    if qual["status"] not in ("QUALIFIED", "LAPSED"):
        raise invalid_state("Qualification cannot be revoked from its current state")
    qual["status"] = "REVOKED"
    mutate(qual)
    welder = db.welders.get(qual["welder_id"])
    if welder is not None:
        recompute_welder_status(welder)
    return success_object(qualification_out(qual))

"""Ovens, consumable lots, consumable issues (nested routes)."""

from decimal import Decimal
from flask import Blueprint, request

from db import db
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_OVEN_NOT_ONLINE,
    ERR_OVEN_CAPACITY_EXCEEDED, ERR_LOT_NOT_IN_OVEN, ERR_LOT_NOT_QUARANTINED,
    ERR_LOT_REBAKE_LIMIT, ERR_INSUFFICIENT_LOT_QUANTITY, invalid_request,
    invalid_state,
)
from helpers import json_body, require_fields, parse_int, parse_number, kg, paginate, PROCESSES
from middleware import require_roles, require_any
from response import success_object, success_list
from serializers import oven_out, lot_out, issue_out
from services import (
    stamp_new, make_versioned, mutate, get_shop, get_oven, get_lot, get_issue,
    get_welder, oven_offline_cascade, SMAW_EXPOSURE_LIMIT_MINUTES,
)

bp = Blueprint("materials", __name__)


# ---------------------------------------------------------------------------
# Ovens
# ---------------------------------------------------------------------------

@bp.route("/weld-shop/shops/<shop_id>/ovens", methods=["POST"])
@require_roles("MaterialController")
def create_oven(user_id, role, shop_id):
    shop = get_shop(shop_id)
    body = json_body()
    require_fields(body, ["oven_code", "holding_temp_c", "capacity_electrodes_kg"])
    if not isinstance(body["oven_code"], str):
        raise invalid_request("oven_code must be a string")
    temp = parse_int(body["holding_temp_c"], "holding_temp_c")
    if temp < 120 or temp > 300:
        raise invalid_request("holding_temp_c must be in [120, 300]")
    capacity = parse_int(body["capacity_electrodes_kg"], "capacity_electrodes_kg")
    oven = stamp_new({
        "shop_id": shop["id"],
        "oven_code": body["oven_code"],
        "holding_temp_c": temp,
        "capacity_electrodes_kg": capacity,
        "status": "ONLINE",
    })
    make_versioned(oven)
    db.ovens[oven["id"]] = oven
    return success_object(oven_out(oven), status=201)


@bp.route("/weld-shop/shops/<shop_id>/ovens", methods=["GET"])
@require_any
def list_ovens(user_id, role, shop_id):
    shop = get_shop(shop_id)
    records = [o for o in db.ovens.values() if o["shop_id"] == shop["id"]]
    page, limit, offset, total = paginate(records)
    return success_list([oven_out(o) for o in page], limit, offset, total)


@bp.route("/weld-shop/shops/<shop_id>/ovens/<oven_id>/take-offline", methods=["POST"])
@require_roles("MaterialController")
def take_oven_offline(user_id, role, shop_id, oven_id):
    get_shop(shop_id)
    oven = get_oven(shop_id, oven_id)
    if oven["status"] != "ONLINE":
        raise invalid_state("Oven is not ONLINE")
    oven["status"] = "OFFLINE"
    mutate(oven)
    oven_offline_cascade(oven)
    return success_object(oven_out(oven))


@bp.route("/weld-shop/shops/<shop_id>/ovens/<oven_id>/bring-online", methods=["POST"])
@require_roles("MaterialController")
def bring_oven_online(user_id, role, shop_id, oven_id):
    get_shop(shop_id)
    oven = get_oven(shop_id, oven_id)
    if oven["status"] != "OFFLINE":
        raise invalid_state("Oven is not OFFLINE")
    oven["status"] = "ONLINE"
    mutate(oven)
    return success_object(oven_out(oven))


# ---------------------------------------------------------------------------
# Consumable lots
# ---------------------------------------------------------------------------

@bp.route("/weld-shop/shops/<shop_id>/consumable-lots", methods=["POST"])
@require_roles("MaterialController")
def create_lot(user_id, role, shop_id):
    shop = get_shop(shop_id)
    body = json_body()
    require_fields(body, ["lot_number", "filler_spec", "process", "received_kg", "oven_id"])
    if not isinstance(body["lot_number"], str) or not isinstance(body["filler_spec"], str):
        raise invalid_request("lot_number and filler_spec must be strings")
    if body["process"] not in PROCESSES:
        raise invalid_request("process must be one of SMAW, GMAW, FCAW, GTAW, SAW")
    received = kg(parse_number(body["received_kg"], "received_kg"))
    oven = get_oven(shop_id, body["oven_id"])
    # capacity: load = sum(remaining_kg over IN_OVEN/QUARANTINED lots); inclusive <=
    load = sum(
        (lot["remaining_kg"] for lot in db.lots.values()
         if lot["oven_id"] == oven["id"] and lot["status"] in ("IN_OVEN", "QUARANTINED")),
        Decimal("0"),
    )
    if load + received > Decimal(oven["capacity_electrodes_kg"]):
        raise ApiError(ERR_OVEN_CAPACITY_EXCEEDED, 422,
                       "Projected oven load exceeds capacity_electrodes_kg")
    lot = stamp_new({
        "shop_id": shop["id"],
        "oven_id": oven["id"],
        "lot_number": body["lot_number"],
        "filler_spec": body["filler_spec"],
        "process": body["process"],
        "received_kg": received,
        "remaining_kg": received,
        "exposed_minutes_total": 0,
        "rebake_count": 0,
        "status": "IN_OVEN",
    })
    make_versioned(lot)
    db.lots[lot["id"]] = lot
    return success_object(lot_out(lot), status=201)


@bp.route("/weld-shop/shops/<shop_id>/consumable-lots", methods=["GET"])
@require_any
def list_lots(user_id, role, shop_id):
    shop = get_shop(shop_id)
    records = [lot for lot in db.lots.values() if lot["shop_id"] == shop["id"]]
    oven_filter = request.args.get("oven_id")
    status_filter = request.args.get("status")
    if oven_filter is not None:
        records = [lot for lot in records if lot["oven_id"] == oven_filter]
    if status_filter is not None:
        records = [lot for lot in records if lot["status"] == status_filter]
    page, limit, offset, total = paginate(records)
    return success_list([lot_out(lot) for lot in page], limit, offset, total)


@bp.route("/weld-shop/shops/<shop_id>/consumable-lots/<lot_id>", methods=["GET"])
@require_any
def get_lot_route(user_id, role, shop_id, lot_id):
    get_shop(shop_id)
    return success_object(lot_out(get_lot(shop_id, lot_id)))


@bp.route("/weld-shop/shops/<shop_id>/consumable-lots/<lot_id>/rebake", methods=["POST"])
@require_roles("MaterialController")
def rebake_lot(user_id, role, shop_id, lot_id):
    get_shop(shop_id)
    lot = get_lot(shop_id, lot_id)
    if lot["status"] != "QUARANTINED":
        raise ApiError(ERR_LOT_NOT_QUARANTINED, 409, "Rebake requires QUARANTINED status")
    if lot["rebake_count"] >= 1:
        raise ApiError(ERR_LOT_REBAKE_LIMIT, 422,
                       "Lot has already been rebaked once; further rebake forbidden")
    oven = db.ovens.get(lot["oven_id"])
    if oven is None or oven["status"] != "ONLINE":
        raise ApiError(ERR_OVEN_NOT_ONLINE, 409, "Oven must be ONLINE to rebake")
    lot["rebake_count"] += 1
    lot["exposed_minutes_total"] = 0
    lot["status"] = "IN_OVEN"
    mutate(lot)
    return success_object(lot_out(lot))


# ---------------------------------------------------------------------------
# Consumable issues
# ---------------------------------------------------------------------------

@bp.route("/weld-shop/shops/<shop_id>/consumable-issues", methods=["POST"])
@require_roles("MaterialController")
def create_issue(user_id, role, shop_id):
    shop = get_shop(shop_id)
    body = json_body()
    require_fields(body, ["lot_id", "oven_id", "issued_to_welder_id", "issued_kg"])
    lot = get_lot(shop_id, body["lot_id"])
    oven = get_oven(shop_id, body["oven_id"])
    get_welder(shop_id, body["issued_to_welder_id"])
    issued = kg(parse_number(body["issued_kg"], "issued_kg"))
    if oven["status"] != "ONLINE":
        raise ApiError(ERR_OVEN_NOT_ONLINE, 409, "Oven must be ONLINE to issue")
    if lot["status"] != "IN_OVEN":
        raise ApiError(ERR_LOT_NOT_IN_OVEN, 409, "Lot must be IN_OVEN to issue")
    if lot["remaining_kg"] < issued:
        raise ApiError(ERR_INSUFFICIENT_LOT_QUANTITY, 422,
                       "issued_kg exceeds lot remaining_kg")
    lot["remaining_kg"] -= issued
    lot["status"] = "ISSUED"
    mutate(lot)
    issue = stamp_new({
        "shop_id": shop["id"],
        "lot_id": lot["id"],
        "oven_id": oven["id"],
        "issued_to_welder_id": body["issued_to_welder_id"],
        "issued_kg": issued,
        "issued_at_utc": shop["current_utc"],
        "returned_at_utc": None,
        "exposure_minutes": None,
        "status": "OPEN",
    })
    db.issues[issue["id"]] = issue
    return success_object(issue_out(issue), status=201)


@bp.route("/weld-shop/shops/<shop_id>/consumable-issues", methods=["GET"])
@require_any
def list_issues(user_id, role, shop_id):
    shop = get_shop(shop_id)
    records = [i for i in db.issues.values() if i["shop_id"] == shop["id"]]
    for param in ("lot_id", "oven_id", "issued_to_welder_id"):
        value = request.args.get(param)
        if value is not None:
            records = [i for i in records if i.get(param) == value]
    page, limit, offset, total = paginate(records)
    return success_list([issue_out(i) for i in page], limit, offset, total)


@bp.route("/weld-shop/shops/<shop_id>/consumable-issues/<issue_id>/return", methods=["POST"])
@require_roles("MaterialController")
def return_issue(user_id, role, shop_id, issue_id):
    shop = get_shop(shop_id)
    issue = get_issue(shop_id, issue_id)
    oven = db.ovens.get(issue["oven_id"])
    if oven is None or oven["status"] != "ONLINE":
        raise ApiError(ERR_OVEN_NOT_ONLINE, 409, "Oven must be ONLINE to return")
    if issue["status"] != "OPEN":
        raise invalid_state("ConsumableIssue is not OPEN")
    now = shop["current_utc"]
    issue["returned_at_utc"] = now
    issue["status"] = "RETURNED"
    exposure = max(0, int((now - issue["issued_at_utc"]).total_seconds() // 60))
    issue["exposure_minutes"] = exposure
    lot = db.lots.get(issue["lot_id"])
    if lot is not None:
        lot["exposed_minutes_total"] += exposure
        lot["remaining_kg"] += issue["issued_kg"]
        if lot["process"] == "SMAW" and lot["exposed_minutes_total"] >= SMAW_EXPOSURE_LIMIT_MINUTES:
            lot["status"] = "QUARANTINED"
        elif lot["remaining_kg"] > 0:
            lot["status"] = "IN_OVEN"
        else:
            lot["status"] = "EXHAUSTED"
        mutate(lot)
    return success_object(issue_out(issue))

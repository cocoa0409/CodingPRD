"""Closed-loop scrap return endpoints: schedule, list, get, credit."""
from flask import Blueprint, request

from db import store, new_id, now_iso, next_seq, touch, clock_year
from errors import (ApiError, ERR_NOT_FOUND, ERR_PLANT_NOT_FOUND,
                    ERR_VALIDATION, ERR_INVALID_STATE,
                    ERR_PICKUP_WINDOW_CONFLICT, ERR_PICKUP_DAILY_LIMIT)
from middleware import actor, require_role, require_customer_owner
from response import ok_object, ok_list
from services import calc
from services.serialize import scrap_public
from validation import (body_json, req_str, req_num, req_enum, parse_iso_dt,
                        pagination_args)

bp = Blueprint("scrap", __name__)

GRADES = ("UBC", "PROCESS", "MIXED")


def get_scrap_or_404(sid):
    sr = store["scrap_returns"].get(sid)
    if sr is None:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Scrap return not found.")
    return sr


@bp.post("/customers/<cid>/scrap-returns")
def create_scrap_return(cid):
    user_id, role = actor()
    require_role(role, ["CustomerPlanner"])
    # Gate 2 ownership: the path Customer id must equal X-User-ID.
    require_customer_owner(user_id, cid)
    data = body_json()
    plant_id = req_str(data, "plant_id")
    pws = req_str(data, "pickup_window_start")
    pwe = req_str(data, "pickup_window_end")
    pws_dt = parse_iso_dt(pws, "pickup_window_start")
    pwe_dt = parse_iso_dt(pwe, "pickup_window_end")
    if pwe_dt <= pws_dt:
        raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                       "pickup_window_end must be strictly after pickup_window_start.")
    declared = req_num(data, "declared_weight_lbs", gt=0)
    if store["customers"].get(cid) is None:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Customer not found.")
    if store["plants"].get(plant_id) is None:
        raise ApiError(ERR_PLANT_NOT_FOUND[0], ERR_PLANT_NOT_FOUND[1],
                       "plant_id does not match an existing plant.")
    # Gate 8 temporal: closed-interval conflict before the daily cap.
    scheduled = [
        s for s in store["scrap_returns"].values()
        if s["customer_id"] == cid and s["status"] == "SCHEDULED"
    ]
    for s in scheduled:
        # CLOSED interval semantics: merely touching windows already conflict.
        if s["_pws_dt"] <= pwe_dt and pws_dt <= s["_pwe_dt"]:
            raise ApiError(ERR_PICKUP_WINDOW_CONFLICT[0], ERR_PICKUP_WINDOW_CONFLICT[1],
                           "Pickup window conflicts with another scheduled pickup.")
    day = pws_dt.date()
    same_day = [s for s in scheduled if s["_pws_dt"].date() == day]
    if len(same_day) + 1 > calc.MAX_PICKUPS_PER_DAY:
        raise ApiError(ERR_PICKUP_DAILY_LIMIT[0], ERR_PICKUP_DAILY_LIMIT[1],
                       "More than %d scheduled pickups on one UTC day." % calc.MAX_PICKUPS_PER_DAY)
    ts = now_iso()
    sr = {
        "id": new_id(),
        "customer_id": cid,
        "plant_id": plant_id,
        "pickup_window_start": pws,
        "pickup_window_end": pwe,
        "declared_weight_lbs": declared,
        "credited_weight_lbs": None,
        "grade": None,
        "status": "SCHEDULED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_created_sort": next_seq(),
        "_pws_dt": pws_dt,
        "_pwe_dt": pwe_dt,
    }
    store["scrap_returns"][sr["id"]] = sr
    return ok_object(scrap_public(sr), code=201)


@bp.get("/scrap-returns")
def list_scrap_returns():
    actor()
    limit, offset = pagination_args()
    customer_id = request.args.get("customer_id")
    plant_id = request.args.get("plant_id")
    status = request.args.get("status")
    items = sorted(store["scrap_returns"].values(), key=lambda s: s["_created_sort"])
    if customer_id is not None:
        items = [s for s in items if s["customer_id"] == customer_id]
    if plant_id is not None:
        items = [s for s in items if s["plant_id"] == plant_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([scrap_public(s) for s in page], limit, offset, total)


@bp.get("/scrap-returns/<sid>")
def get_scrap_return(sid):
    actor()
    return ok_object(scrap_public(get_scrap_or_404(sid)))


@bp.post("/scrap-returns/<sid>/credit")
def credit_scrap_return(sid):
    _, role = actor()
    require_role(role, ["PlantManager"])
    data = body_json()
    actual_weight = req_num(data, "actual_weight_lbs", gt=0)
    grade = req_enum(data, "grade", GRADES)
    sr = get_scrap_or_404(sid)
    if sr["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                       "Only a SCHEDULED scrap return can be credited.")
    sr["credited_weight_lbs"] = actual_weight
    sr["grade"] = grade
    sr["status"] = "CREDITED"
    touch(sr)
    plant = store["plants"][sr["plant_id"]]
    plant["_scrap_events"].append({"year": clock_year(), "lbs": actual_weight})
    touch(plant)
    return ok_object(scrap_public(sr))

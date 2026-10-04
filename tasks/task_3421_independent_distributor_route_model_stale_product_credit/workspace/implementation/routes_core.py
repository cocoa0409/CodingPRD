"""Core routes: logical clock, bakeries, production days, day close."""
from flask import Blueprint, request

import auth
import clock
import domain
import store
import validators as V
from constants import ROLE_COMPANY_ADMIN, ALL_ROLES
from errors import (
    ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_PRODUCTION_DAY_EXISTS, raise_err,
)
from response import ok, ok_object, ok_list, pagination_params, body, public

bp = Blueprint("core", __name__)

ADMIN = (ROLE_COMPANY_ADMIN,)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    user_id, role = auth.caller()
    auth.require_role(role, ADMIN)
    data = body()
    current_utc = V.get_str(data, "current_utc")
    if clock.set_current(current_utc) is None:
        raise_err(ERR_INVALID_REQUEST, "current_utc must be an ISO 8601 timestamp")
    return ok({"current_utc": current_utc}, "object", 200)


@bp.route("/bakeries", methods=["POST"])
def create_bakery():
    user_id, role = auth.caller()
    auth.require_role(role, ADMIN)
    data = body()
    name = V.get_str(data, "name")
    capacity = V.get_int(data, "daily_capacity_units", minimum=1)
    catalog = V.get_list(data, "product_catalog")
    seen_skus = set()
    entries = []
    for entry in catalog:
        if not isinstance(entry, dict):
            raise_err(ERR_INVALID_REQUEST, "product_catalog entries must be objects")
        sku = V.get_str(entry, "sku")
        display_name = V.get_str(entry, "display_name")
        shelf_life = V.get_int(entry, "shelf_life_days", minimum=1)
        list_price = V.get_int(entry, "list_price_cents", minimum=1)
        if sku in seen_skus:
            raise_err(ERR_INVALID_REQUEST, f"Duplicate sku in catalog: {sku}")
        seen_skus.add(sku)
        entries.append({
            "sku": sku,
            "display_name": display_name,
            "shelf_life_days": shelf_life,
            "list_price_cents": list_price,
        })
    bakery = store.insert("bakeries", {
        "name": name,
        "daily_capacity_units": capacity,
        "product_catalog": entries,
    })
    return ok_object(bakery, 201)


@bp.route("/bakeries/<rid>", methods=["GET"])
def get_bakery(rid):
    auth.caller()
    bakery = store.get("bakeries", rid)
    if bakery is None:
        raise_err(ERR_NOT_FOUND, "Bakery not found")
    return ok_object(bakery)


def day_view(day):
    view = dict(day)
    view["forecast_units"] = domain.forecast_units(day)
    return public(view)


@bp.route("/bakeries/<rid>/production-days", methods=["POST"])
def create_production_day(rid):
    user_id, role = auth.caller()
    auth.require_role(role, ADMIN)
    bakery = store.get("bakeries", rid)
    if bakery is None:
        raise_err(ERR_NOT_FOUND, "Bakery not found")
    data = body()
    date_str, date_obj = V.get_date(data, "date")
    override = V.get_int(data, "capacity_override_units", required=False, minimum=1)
    if domain.find_production_day(rid, date_str) is not None:
        raise_err(ERR_PRODUCTION_DAY_EXISTS,
                  "A production day already exists for this bakery and date")
    day = store.insert("production_days", {
        "bakery_id": rid,
        "date": date_str,
        "capacity_units": override if override is not None else bakery["daily_capacity_units"],
        "allocated_units": 0,
        "status": "PLANNING",
    })
    return ok(day_view(day), "object", 201)


@bp.route("/bakeries/<rid>/production-days", methods=["GET"])
def list_production_days(rid):
    auth.caller()
    bakery = store.get("bakeries", rid)
    if bakery is None:
        raise_err(ERR_NOT_FOUND, "Bakery not found")
    status = request.args.get("status")
    date_filter = request.args.get("date")
    days = [d for d in store.all_of("production_days") if d["bakery_id"] == rid]
    if status is not None:
        days = [d for d in days if d["status"] == status]
    if date_filter is not None:
        days = [d for d in days if d["date"] == date_filter]
    page = pagination_params()
    total = len(days)
    window = days[page["offset"]:page["offset"] + page["limit"]]
    return ok_list([day_view(d) for d in window], total, page)


@bp.route("/production-days/<rid>/close", methods=["POST"])
def close_production_day(rid):
    user_id, role = auth.caller()
    auth.require_role(role, ADMIN)
    day = store.get("production_days", rid)
    if day is None:
        raise_err(ERR_NOT_FOUND, "Production day not found")
    if day["status"] != "PLANNING":
        raise_err(ERR_INVALID_STATE, "Production day is already closed")
    today = clock.today()
    if today < clock.parse_date(day["date"]):
        raise_err(ERR_INVALID_STATE, "Cannot close a future production date")
    day["status"] = "CLOSED"
    store.touch(day)
    domain.delinquency_evaluation(today)
    domain.auto_expire_claims(today)
    return ok(day_view(day), "object", 200)

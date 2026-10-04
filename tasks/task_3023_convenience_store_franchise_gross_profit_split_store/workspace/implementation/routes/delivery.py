"""DeliveryWindow routes, including the handling buffer and the 24-hour lock rule."""

from datetime import timedelta

from flask import Blueprint

import db
import middleware
import schemas
import services
import timeutil
from errors import fail
from response import ok
from routes.common import SHARED, list_records

bp = Blueprint("delivery_windows", __name__)

DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
HANDLING_BUFFER = timedelta(minutes=30)


@bp.post("/delivery-windows")
@middleware.auth(("FranchisorAdmin",))
def create_window():
    payload = middleware.body(
        required=("store_id", "commissary_code", "day_of_week", "window_start",
                  "window_end", "capacity_units"),
    )
    store = services.require_store(payload["store_id"])
    commissary_code = middleware.string_value(payload["commissary_code"], "commissary_code")
    day_of_week = middleware.enum_value(payload["day_of_week"], DAYS, "day_of_week")
    window_start = timeutil.required_utc(payload["window_start"])
    window_end = timeutil.required_utc(payload["window_end"])
    if window_end <= window_start:
        fail("ERR_INVALID_REQUEST")
    capacity = middleware.positive_int(payload["capacity_units"], "capacity_units")

    for existing in db.all_of("delivery_windows"):
        if existing["store_id"] != store["id"]:
            continue
        if existing["commissary_code"] != commissary_code:
            continue
        if existing["status"] == "CANCELLED":
            continue
        if existing["window_end"] <= window_start < existing["window_end"] + HANDLING_BUFFER:
            fail("ERR_WINDOW_HANDLING_OVERLAP")

    record = db.insert("delivery_windows", {
        "store_id": store["id"],
        "commissary_code": commissary_code,
        "day_of_week": day_of_week,
        "window_start": window_start,
        "window_end": window_end,
        "capacity_units": capacity,
        "reserved_units": 0,
        "status": "SCHEDULED",
    })
    return ok(schemas.dump("delivery_windows", record), 201)


@bp.get("/delivery-windows")
@middleware.auth(SHARED)
def list_windows():
    return list_records("delivery_windows", ("store_id", "status", "day_of_week"))


@bp.get("/delivery-windows/<window_id>")
@middleware.auth(SHARED)
def get_window(window_id):
    window = services.require("delivery_windows", window_id)
    return ok(schemas.dump("delivery_windows", window))


@bp.post("/delivery-windows/<window_id>/lock")
@middleware.auth(("FranchisorAdmin",))
def lock_window(window_id):
    window = services.require("delivery_windows", window_id)
    services.require_state(window, "SCHEDULED")
    if db.clock() >= window["window_start"] - timedelta(hours=24):
        fail("ERR_WINDOW_LOCK_TOO_LATE")
    if int(window["reserved_units"]) > int(window["capacity_units"]):
        fail("ERR_WINDOW_CAPACITY_EXCEEDED")
    window["status"] = "LOCKED"
    db.touch(window)
    return ok(schemas.dump("delivery_windows", window))
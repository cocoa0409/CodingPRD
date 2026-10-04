"""Location endpoints (PRD 3.1) plus the timing-metrics rollup (PRD 3.5)."""
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone

from db import db, now
from errors import invalid_request, not_found
from middleware import (
    require_auth,
    body_json,
    get_str,
    get_int,
    get_enum,
)
from response import success_object
from serializers import location as ser_location
from services import make_record, touch
from . import locations_bp


@locations_bp.route("/locations", methods=["POST"])
def create_location():
    require_auth(["PlatformAdmin"])
    body = body_json()
    code = get_str(body, "code", required=True)
    name = get_str(body, "name", required=True)
    tz = get_str(body, "timezone", required=True)
    capacity = get_int(body, "stall_capacity", required=True, minimum=1)
    rec = make_record()
    rec.update(
        {
            "code": code,
            "name": name,
            "timezone": tz,
            "weather_mode": "NORMAL",
            "stall_capacity": capacity,
            "stalls_available": capacity,
            "lane_posture": "OPEN",
            "rush_index": 0,
        }
    )
    db.locations[rec["id"]] = rec
    return success_object(ser_location(rec), 201)


@locations_bp.route("/locations/<locationId>", methods=["GET"])
def get_location(locationId):
    require_auth(["PlatformAdmin", "ShiftManager", "Carhop", "KitchenStaff", "Customer"])
    loc = db.locations.get(locationId)
    if loc is None:
        not_found("Location not found")
    return success_object(ser_location(loc))


@locations_bp.route("/locations/<locationId>/weather", methods=["POST"])
def set_weather(locationId):
    require_auth(["ShiftManager", "PlatformAdmin"])
    loc = db.locations.get(locationId)
    if loc is None:
        not_found("Location not found")
    body = body_json()
    mode = get_enum(body, "weather_mode", ["NORMAL", "HEAT_ADVISORY", "STORM"], required=True)
    loc["weather_mode"] = mode
    from services import recompute_location_posture

    recompute_location_posture(loc, touch_location=True)
    return success_object(ser_location(loc))


@locations_bp.route("/locations/<locationId>/advance_rush", methods=["POST"])
def advance_rush(locationId):
    require_auth(["ShiftManager"])
    loc = db.locations.get(locationId)
    if loc is None:
        not_found("Location not found")
    loc["rush_index"] += 1
    # Expire stale drafts: DRAFT orders whose checked_in_at is older than
    # 2 rush windows (PRD 3.1, rush_admission calc).
    from services import cancel_order

    for order in list(db.orders.values()):
        if (
            order["location_id"] == loc["id"]
            and order["status"] == "DRAFT"
            and order["checked_in_at"] is not None
            and order.get("checked_in_rush_index") is not None
            and loc["rush_index"] - order["checked_in_rush_index"] > 2
        ):
            cancel_order(order)
    touch(loc)
    return success_object(ser_location(loc))


@locations_bp.route("/locations/<locationId>/metrics", methods=["GET"])
def metrics(locationId):
    require_auth(["ShiftManager", "PlatformAdmin"])
    from flask import request

    loc = db.locations.get(locationId)
    if loc is None:
        not_found("Location not found")
    channel = request.args.get("channel")
    from_raw = request.args.get("from")
    to_raw = request.args.get("to")
    if channel is not None and channel not in (
        "STALL_INTERCOM",
        "APP_CHECKIN",
        "DRIVE_THRU",
        "PATIO",
    ):
        invalid_request("channel must be a valid order channel")

    def parse_ts(raw, name):
        if raw is None:
            return None
        s = raw.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            invalid_request("{} must be an ISO 8601 timestamp".format(name))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    from_dt = parse_ts(from_raw, "from")
    to_dt = parse_ts(to_raw, "to")

    delivered = [
        o
        for o in db.orders.values()
        if o["location_id"] == loc["id"] and o["status"] == "DELIVERED"
    ]
    if channel is not None:
        delivered = [o for o in delivered if o["channel"] == channel]
    if from_dt is not None:
        delivered = [o for o in delivered if o["placed_at"] is not None and o["placed_at"] >= from_dt]
    if to_dt is not None:
        delivered = [o for o in delivered if o["placed_at"] is not None and o["placed_at"] < to_dt]

    count_delivered = len(delivered)
    if count_delivered == 0:
        data = {
            "count_delivered": 0,
            "count_late": 0,
            "avg_checkout_to_ready_seconds": None,
            "avg_ready_to_delivered_seconds": None,
            "on_time_rate": None,
        }
        return success_object(data)
    count_late = sum(1 for o in delivered if o["late_flag"])

    def mean_rounded(values):
        total = sum(values)
        return int(
            (Decimal(total) / Decimal(len(values))).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )

    c2r = [int((o["ready_at"] - o["placed_at"]).total_seconds()) for o in delivered]
    r2d = [int((o["delivered_at"] - o["ready_at"]).total_seconds()) for o in delivered]
    on_time = Decimal(count_delivered - count_late) / Decimal(count_delivered)
    on_time = on_time.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    data = {
        "count_delivered": count_delivered,
        "count_late": count_late,
        "avg_checkout_to_ready_seconds": mean_rounded(c2r),
        "avg_ready_to_delivered_seconds": mean_rounded(r2d),
        "on_time_rate": float(on_time),
    }
    return success_object(data)

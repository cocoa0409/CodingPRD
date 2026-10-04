"""Storage tanks and telemetry ingestion (PRD 3.5)."""
from flask import Blueprint, request

from helpers import (authenticate, require_role, json_body, respond,
                     v_str, v_int, v_num, v_dt, v_enum, validation,
                     as_int, by_created, paginate, PRODUCTS)
from store import db, base_entity, pub, touch, parse_dt, new_id, next_seq, \
    now_iso, ApiError
from domain import (posture_for, recompute_tank_analytics, readings_of,
                    latest_reading, has_open_delivery, create_delivery)

bp = Blueprint("tanks", __name__)


@bp.route("/gas-supply/storage-tanks", methods=["POST"])
def create_tank():
    _uid, role = authenticate()
    require_role(role, {"PlantOperator"})
    body = json_body()
    # Tier 3: body-referenced customer must exist
    cid = body.get("customer_id")
    if isinstance(cid, str) and cid not in db["customers"]:
        raise ApiError("ERR_CUSTOMER_NOT_FOUND", 404, "Customer not found")
    # Tier 9 structural
    customer_id = v_str(body, "customer_id")
    site_label = v_str(body, "site_label")
    product = v_enum(body, "product", PRODUCTS)
    capacity = v_int(body, "capacity_liters", min_value=1)
    reorder = v_int(body, "reorder_point_liters", min_value=0)
    safety = v_int(body, "safety_stock_liters", min_value=0)
    purity = v_num(body, "required_purity_percent")
    max_impurity = v_int(body, "max_impurity_ppm", min_value=0)
    if reorder <= safety:
        validation("reorder_point_liters must be strictly greater than "
                   "safety_stock_liters")
    ent = base_entity()
    ent.update({
        "customer_id": customer_id,
        "site_label": site_label,
        "product": product,
        "capacity_liters": capacity,
        "reorder_point_liters": reorder,
        "safety_stock_liters": safety,
        "required_purity_percent": purity,
        "max_impurity_ppm": max_impurity,
        "current_level_liters": None,
        "last_reading_at": None,
        "burn_rate_instant_lph": None,
        "burn_rate_wma_lph": None,
        "projected_runout_instant_at": None,
        "projected_runout_wma_at": None,
        "status": "NORMAL",
    })
    db["tanks"][ent["id"]] = ent
    return respond(pub(ent), "object", 201)


def _get_tank_or_404(tank_id):
    ent = db["tanks"].get(tank_id)
    if ent is None:
        raise ApiError("ERR_TANK_NOT_FOUND", 404, "StorageTank not found")
    return ent


@bp.route("/gas-supply/storage-tanks/<tankId>", methods=["GET"])
def get_tank(tankId):
    authenticate()
    return respond(pub(_get_tank_or_404(tankId)))


@bp.route("/gas-supply/storage-tanks", methods=["GET"])
def list_tanks():
    authenticate()
    items = list(db["tanks"].values())
    for f in ("customer_id", "status"):
        val = request.args.get(f)
        if val is not None:
            items = [t for t in items if t.get(f) == val]
    items = by_created(items)
    page, meta = paginate(items)
    return respond([pub(t) for t in page], "array", 200, meta)


@bp.route("/gas-supply/storage-tanks/<tankId>/telemetry", methods=["POST"])
def post_telemetry(tankId):
    _uid, role = authenticate()
    require_role(role, {"TelemetryGateway"})
    tank = _get_tank_or_404(tankId)
    body = json_body()
    # Tier 6: chronological ordering and in-range level (checkable parts run
    # even when the other field is structurally malformed)
    mdt = parse_dt(body.get("measured_at"))
    level = as_int(body.get("level_liters"))
    if mdt is not None:
        latest = latest_reading(tankId)
        if latest is not None and mdt <= latest["_measured"]:
            raise ApiError("ERR_READING_OUT_OF_ORDER", 422,
                           "measured_at must be strictly later than the "
                           "latest reading")
    if level is not None and (level < 0 or level > tank["capacity_liters"]):
        raise ApiError("ERR_READING_OUT_OF_ORDER", 422,
                       "level_liters must lie within [0, capacity_liters]")
    # Tier 9 structural
    measured_raw = v_dt(body, "measured_at")
    level = v_int(body, "level_liters")
    mdt = parse_dt(measured_raw)
    # Append the immutable reading (TelemetryReading has no updated_at/version)
    reading = {"id": new_id(), "created_at": now_iso(), "tank_id": tankId,
               "measured_at": measured_raw, "level_liters": level,
               "_measured": mdt, "_seq": next_seq()}
    db["readings"][reading["id"]] = reading
    # Refresh tank computed fields and posture
    old_posture = tank["status"]
    tank["current_level_liters"] = level
    tank["last_reading_at"] = measured_raw
    new_posture = posture_for(tank, level)
    tank["status"] = new_posture
    recompute_tank_analytics(tank)
    touch(tank)
    # Edge-triggered replenishment on entry into a low posture
    if (new_posture != old_posture
            and new_posture in ("REORDER_DUE", "CRITICAL")
            and not has_open_delivery(tankId)):
        create_delivery(tank, "TELEMETRY")
    return respond(pub(tank), "object", 201)


@bp.route("/gas-supply/storage-tanks/<tankId>/telemetry", methods=["GET"])
def list_telemetry(tankId):
    authenticate()
    _get_tank_or_404(tankId)
    items = readings_of(tankId)
    page, meta = paginate(items)
    return respond([pub(r) for r in page], "array", 200, meta)

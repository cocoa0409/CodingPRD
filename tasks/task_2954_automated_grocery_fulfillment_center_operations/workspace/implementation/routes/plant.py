"""The standing plant: logical clock, routes, bays, zones, stations, the
catalogue and maintenance windows (PRD 3.1, 3.8)."""

from datetime import timedelta

from flask import Blueprint

import db as store
from db import db
from errors import ApiError
import response as resp
import validation as v
from middleware import endpoint, must_get
from services import derive, money, selectors

bp = Blueprint("plant", __name__)

ALL = store.ALL_ROLES
STAFF = store.STAFF_ROLES
ADMIN = ["FulfillmentAdmin"]
ENGINEER = ["GridEngineer"]


# --------------------------------------------------------------------------
# Logical clock (PRD 2.5)
# --------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint(roles=ALL, mutating=True)
def set_clock():
    body = v.read_body()
    data = v.check_body(body, [v.f_instant("current_utc")])
    db.clock = data["current_utc"]
    money.recompute_surge_all()
    return resp.raw({"current_utc": store.fmt_instant(db.clock)})


# --------------------------------------------------------------------------
# Delivery routes
# --------------------------------------------------------------------------
@bp.route("/delivery-routes", methods=["POST"])
@endpoint(roles=ADMIN, mutating=True)
def create_route():
    body = v.read_body()
    data = v.check_body(body, [
        v.f_str("route_code", 1, 32),
        v.f_str("service_area_name", 1, 80),
        v.f_int("van_capacity_totes", 1, 400),
        v.f_int("base_delivery_fee_cents", 0, 5000),
        v.f_int("per_km_cost_cents", 1, 2000),
    ])
    v.ensure_unique(db.routes, "route_code", data["route_code"])
    route = store.insert(db.routes, {
        "route_code": data["route_code"],
        "service_area_name": data["service_area_name"],
        "van_capacity_totes": data["van_capacity_totes"],
        "base_delivery_fee_cents": data["base_delivery_fee_cents"],
        "per_km_cost_cents": data["per_km_cost_cents"],
    })
    return resp.created(route)


@bp.route("/delivery-routes/<route_id>", methods=["GET"])
@endpoint(roles=ALL)
def read_route(route_id):
    return resp.obj(must_get(db.routes, route_id, "ERR_ROUTE_NOT_FOUND"))


# --------------------------------------------------------------------------
# Dock bays
# --------------------------------------------------------------------------
@bp.route("/dock-bays", methods=["POST"])
@endpoint(roles=ADMIN, mutating=True)
def create_bay():
    body = v.read_body()
    data = v.check_body(body, [
        v.f_str("bay_code", 1, 32),
        v.f_int("parallel_van_capacity", 1, 6),
    ])
    v.ensure_unique(db.bays, "bay_code", data["bay_code"])
    bay = store.insert(db.bays, {
        "bay_code": data["bay_code"],
        "parallel_van_capacity": data["parallel_van_capacity"],
    })
    return resp.created(bay)


@bp.route("/dock-bays/<bay_id>", methods=["GET"])
@endpoint(roles=STAFF)
def read_bay(bay_id):
    return resp.obj(must_get(db.bays, bay_id, "ERR_DOCK_BAY_NOT_FOUND"))


# --------------------------------------------------------------------------
# Grid zones
# --------------------------------------------------------------------------
@bp.route("/grid-zones", methods=["POST"])
@endpoint(roles=ADMIN, mutating=True)
def create_zone():
    body = v.read_body()
    data = v.check_body(body, [
        v.f_str("zone_code", 1, 32),
        v.f_enum("temperature_zone", store.TEMPERATURE_ZONES),
        v.f_int("bot_count", 1, 1200),
    ])
    v.ensure_unique(db.zones, "zone_code", data["zone_code"])
    zone = store.insert(db.zones, {
        "zone_code": data["zone_code"],
        "temperature_zone": data["temperature_zone"],
        "bot_count": data["bot_count"],
        "status": "OPERATIONAL",
        "accuracy_score_unit_weighted": None,
        "accuracy_score_sku_weighted": None,
        "last_audited_at": None,
    })
    return resp.created(zone)


@bp.route("/grid-zones/<zone_id>", methods=["GET"])
@endpoint(roles=STAFF)
def read_zone(zone_id):
    return resp.obj(must_get(db.zones, zone_id, "ERR_ZONE_NOT_FOUND"))


@bp.route("/grid-zones/<zone_id>/audit-counts", methods=["POST"])
@endpoint(roles=ENGINEER, mutating=True)
def audit_counts(zone_id):
    zone = must_get(db.zones, zone_id, "ERR_ZONE_NOT_FOUND")
    body = v.read_body()
    # gate 6: every named SKU resolves
    raw_counts = body.get("counts")
    if isinstance(raw_counts, list):
        for row in raw_counts:
            if isinstance(row, dict) and isinstance(row.get("sku_id"), str):
                if row["sku_id"] not in db.skus:
                    raise ApiError("ERR_SKU_NOT_FOUND", "unknown SKU in counts")
    data = v.check_body(body, [v.f_counts("counts")])
    for row in data["counts"]:
        if db.skus[row["sku_id"]]["grid_zone_id"] != zone["id"]:
            raise ApiError(
                "ERR_SKU_NOT_FOUND", "SKU does not belong to the audited zone"
            )
    selectors.apply_audit(zone, data["counts"])
    return resp.obj(zone)


# --------------------------------------------------------------------------
# Pick stations
# --------------------------------------------------------------------------
@bp.route("/pick-stations", methods=["POST"])
@endpoint(roles=ADMIN, mutating=True)
def create_station():
    body = v.read_body()
    data = v.check_body(body, [
        v.f_str("station_code", 1, 32),
        v.f_zone_list("temperature_zone_capability"),
        v.f_int("max_concurrent_totes", 1, 24),
    ])
    v.ensure_unique(db.stations, "station_code", data["station_code"])
    station = store.insert(db.stations, {
        "station_code": data["station_code"],
        "temperature_zone_capability": data["temperature_zone_capability"],
        "max_concurrent_totes": data["max_concurrent_totes"],
        "current_tote_count": 0,
        "status": "IDLE",
    })
    return resp.created(station)


@bp.route("/pick-stations/<station_id>", methods=["GET"])
@endpoint(roles=STAFF)
def read_station(station_id):
    return resp.obj(must_get(db.stations, station_id, "ERR_PICK_STATION_NOT_FOUND"))


# --------------------------------------------------------------------------
# Inventory SKUs
# --------------------------------------------------------------------------
@bp.route("/inventory-skus", methods=["POST"])
@endpoint(roles=ADMIN, mutating=True)
def create_sku():
    body = v.read_body()
    zone = v.fk(body, "grid_zone_id", db.zones, "ERR_ZONE_NOT_FOUND")
    data = v.check_body(body, [
        v.f_str("sku_code", 1, 32),
        v.f_str("name", 1, 120),
        v.f_id("grid_zone_id"),
        v.f_enum("temperature_zone", store.TEMPERATURE_ZONES),
        v.f_str("substitution_group_code", 1, 32),
        v.f_bool("is_catchweight", required=False, default=False),
        v.f_int("unit_price_cents", 1, 500000),
        v.f_int("price_per_kg_cents", 1, 500000, required=False),
        v.f_int("nominal_weight_grams", 1, 100000, required=False),
        v.f_dec("weight_tolerance_pct", None, "0.50", 4, required=False,
                exclusive_min="0"),
        v.f_int("physical_units", 0, 1000000),
    ])
    catchweight = data["is_catchweight"]
    conditional = ("price_per_kg_cents", "nominal_weight_grams", "weight_tolerance_pct")
    for name in conditional:
        if catchweight and data[name] is None:
            v.bad("%s is required for a catchweight SKU" % name)
        if not catchweight and data[name] is not None:
            v.bad("%s must be omitted for a non-catchweight SKU" % name)
    v.ensure_unique(db.skus, "sku_code", data["sku_code"])
    if zone["temperature_zone"] != data["temperature_zone"]:
        v.bad("the grid zone stores a different temperature class")
    sku = store.insert(db.skus, {
        "sku_code": data["sku_code"],
        "name": data["name"],
        "grid_zone_id": zone["id"],
        "temperature_zone": data["temperature_zone"],
        "substitution_group_code": data["substitution_group_code"],
        "is_catchweight": catchweight,
        "unit_price_cents": data["unit_price_cents"],
        "price_per_kg_cents": data["price_per_kg_cents"],
        "nominal_weight_grams": data["nominal_weight_grams"],
        "weight_tolerance_pct": data["weight_tolerance_pct"],
        "physical_units": data["physical_units"],
        "allocated_units": 0,
        "on_hand_units": data["physical_units"],
        "last_count_system_units": None,
        "last_count_counted_units": None,
        "last_count_variance_units": None,
    })
    return resp.created(sku)


@bp.route("/inventory-skus/<sku_id>", methods=["GET"])
@endpoint(roles=ALL)
def read_sku(sku_id):
    return resp.obj(must_get(db.skus, sku_id, "ERR_SKU_NOT_FOUND"))


@bp.route("/inventory-skus", methods=["GET"])
@endpoint(roles=ALL)
def list_skus():
    items = resp.filtered(list(db.skus.values()), {
        "grid_zone_id": "grid_zone_id",
        "temperature_zone": "temperature_zone",
        "substitution_group_code": "substitution_group_code",
    })
    return resp.listing(items)


# --------------------------------------------------------------------------
# Maintenance windows
# --------------------------------------------------------------------------
@bp.route("/maintenance-windows", methods=["POST"])
@endpoint(roles=ENGINEER, mutating=True)
def create_window():
    body = v.read_body()
    zone = v.fk(body, "grid_zone_id", db.zones, "ERR_ZONE_NOT_FOUND")
    data = v.check_body(body, [
        v.f_id("grid_zone_id"),
        v.f_instant("window_start"),
        v.f_instant("window_end"),
    ])
    if data["window_end"] <= data["window_start"]:
        v.bad("window_end must be strictly after window_start")
    buffer_delta = timedelta(minutes=store.MAINTENANCE_BUFFER_MINUTES)
    for existing in db.windows.values():
        if existing["grid_zone_id"] != zone["id"]:
            continue
        if existing["status"] not in ("SCHEDULED", "ACTIVE"):
            continue
        if (data["window_start"] < existing["window_end"] + buffer_delta
                and existing["window_start"] < data["window_end"] + buffer_delta):
            raise ApiError(
                "ERR_MAINTENANCE_WINDOW_OVERLAP",
                "the proposed window collides with an existing window on this zone",
            )
    window = store.insert(db.windows, {
        "grid_zone_id": zone["id"],
        "window_start": data["window_start"],
        "window_end": data["window_end"],
        "status": "SCHEDULED",
    })
    return resp.created(window)


@bp.route("/maintenance-windows/<window_id>", methods=["GET"])
@endpoint(roles=STAFF)
def read_window(window_id):
    return resp.obj(
        must_get(db.windows, window_id, "ERR_MAINTENANCE_WINDOW_NOT_FOUND")
    )


@bp.route("/maintenance-windows", methods=["GET"])
@endpoint(roles=STAFF)
def list_windows():
    items = resp.filtered(list(db.windows.values()), {
        "grid_zone_id": "grid_zone_id",
        "status": "status",
    })
    return resp.listing(items)


@bp.route("/maintenance-windows/<window_id>/activate", methods=["POST"])
@endpoint(roles=ENGINEER, mutating=True)
def activate_window(window_id):
    window = must_get(db.windows, window_id, "ERR_MAINTENANCE_WINDOW_NOT_FOUND")
    v.check_body(v.read_body(), [])
    if window["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "window is not SCHEDULED")
    if not (window["window_start"] <= db.clock < window["window_end"]):
        raise ApiError("ERR_INVALID_STATE", "the clock is outside the window")
    zone = db.zones[window["grid_zone_id"]]
    if zone["status"] != "OPERATIONAL":
        raise ApiError("ERR_ZONE_NOT_OPERATIONAL", "zone is not OPERATIONAL")
    window["status"] = "ACTIVE"
    zone["status"] = "MAINTENANCE"
    return resp.obj(window)


@bp.route("/maintenance-windows/<window_id>/complete", methods=["POST"])
@endpoint(roles=ENGINEER, mutating=True)
def complete_window(window_id):
    window = must_get(db.windows, window_id, "ERR_MAINTENANCE_WINDOW_NOT_FOUND")
    v.check_body(v.read_body(), [])
    if window["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "window is not ACTIVE")
    zone = db.zones[window["grid_zone_id"]]
    window["status"] = "COMPLETED"
    if zone["status"] == "MAINTENANCE":
        zone["status"] = "OPERATIONAL"
    return resp.obj(window)

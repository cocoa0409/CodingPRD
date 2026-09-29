"""Logical clock, railroads, junctions and car types (PRD sections 2.4 and 3.1)."""
import re

from flask import Blueprint

import db
import response
import shapes
from errors import fail
from middleware import endpoint
from services import exposure, serialize

bp = Blueprint("config", __name__)

REPORTING_MARK_RE = re.compile(r"^[A-Z]{2,4}$")
PERIOD_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


# --------------------------------------------------------------------------
# logical clock -- the single endpoint exempt from the checks of section 2.1
# --------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
@bp.post("/car-hire/_clock/set_current_utc")
@endpoint(roles=db.ALL_ROLES, exempt=True)
def set_clock():
    body = shapes.body()
    current = shapes.s_dt(body, "current_utc")
    db.set_clock(current)
    return response.ok({"current_utc": db.iso(current)})


# --------------------------------------------------------------------------
# railroads
# --------------------------------------------------------------------------
@bp.post("/car-hire/railroads")
@endpoint(roles=[db.ROLE_ADMIN])
def create_railroad():
    body = shapes.body()
    reporting_mark = shapes.s_str(body, "reporting_mark")
    name = shapes.s_str(body, "name")
    status = shapes.s_str(body, "status", required=False, default="ACTIVE")
    limit = shapes.s_int(
        body,
        "per_diem_credit_limit_cents",
        required=False,
        minimum=0,
        default=db.DEFAULT_PER_DIEM_CREDIT_LIMIT_CENTS,
    )
    if not REPORTING_MARK_RE.match(reporting_mark):
        fail("ERR_INVALID_REQUEST", "reporting_mark must be two to four upper-case letters.")
    shapes.check_enum("status", status, db.RAILROAD_STATUS)
    if any(r["reporting_mark"] == reporting_mark for r in db.railroads.values()):
        fail("ERR_DUPLICATE_RESOURCE", "reporting_mark is already registered.")

    row = db.base_row()
    row.update(
        {
            "reporting_mark": reporting_mark,
            "name": name,
            "status": status,
            "per_diem_credit_limit_cents": limit,
            "foreign_car_balance": 0,
            "per_diem_exposure_cents": 0,
            "owned_car_count": 0,
        }
    )
    db.railroads[row["id"]] = row
    return response.ok(serialize.railroad(row), 201)


@bp.get("/car-hire/railroads")
@endpoint(roles=[db.ROLE_ADMIN, db.ROLE_ACCOUNTANT])
def list_railroads():
    response.page_params()
    status = shapes.q_enum("status", db.RAILROAD_STATUS)
    reporting_mark = shapes.q_str("reporting_mark")
    rows = list(db.railroads.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if reporting_mark is not None:
        rows = [r for r in rows if r["reporting_mark"] == reporting_mark]
    rows.sort(key=db.order_key)
    return response.paginate(rows, serialize.railroad)


@bp.get("/car-hire/railroads/<railroad_id>")
@endpoint(roles=db.ALL_ROLES, path_params=[("railroad_id", "railroad")])
def read_railroad(road):
    return response.ok(serialize.railroad(road))


@bp.get("/car-hire/railroads/<railroad_id>/exposure")
@endpoint(
    roles=[db.ROLE_ADMIN, db.ROLE_ACCOUNTANT, db.ROLE_FLEET_OWNER],
    path_params=[("railroad_id", "railroad")],
)
def read_exposure(road):
    variant = shapes.q_str("variant") or "SNAPSHOT"
    shapes.check_enum("variant", variant, db.EXPOSURE_VARIANT)
    return response.ok(exposure.read(road, variant))


# --------------------------------------------------------------------------
# car types (immutable: id and created_at only)
# --------------------------------------------------------------------------
@bp.post("/car-hire/car-types")
@endpoint(roles=[db.ROLE_ADMIN])
def create_car_type():
    body = shapes.body()
    code = shapes.s_str(body, "car_type_code")
    description = shapes.s_str(body, "description")
    mode = shapes.s_str(body, "time_component_mode")
    free_time_hours = shapes.s_num(body, "free_time_hours", required=False, minimum=0, default=None)
    per_diem_rate = shapes.s_int(body, "per_diem_rate_cents", required=False, minimum=0, default=0)
    tier2_threshold = shapes.s_int(body, "tier2_threshold_days", required=False, minimum=1, default=5)
    tier2_rate = shapes.s_int(body, "tier2_per_diem_rate_cents", required=False, minimum=0, default=0)
    hourly_rate = shapes.s_int(body, "hourly_rate_cents", required=False, minimum=0, default=0)
    mileage_rate = shapes.s_int(
        body, "mileage_rate_millicents_per_mile", required=False, minimum=0, default=0
    )
    loaded_only = shapes.s_bool(body, "loaded_mileage_only", required=False, default=True)
    shapes.check_enum("time_component_mode", mode, db.TIME_COMPONENT_MODE)
    if any(t["car_type_code"] == code for t in db.car_types.values()):
        fail("ERR_DUPLICATE_RESOURCE", "car_type_code is already registered.")

    row = db.base_row(versioned=False)
    row.update(
        {
            "car_type_code": code,
            "description": description,
            "time_component_mode": mode,
            "free_time_hours": free_time_hours if free_time_hours is not None else 0,
            "per_diem_rate_cents": per_diem_rate,
            "tier2_threshold_days": tier2_threshold,
            "tier2_per_diem_rate_cents": tier2_rate,
            "hourly_rate_cents": hourly_rate,
            "mileage_rate_millicents_per_mile": mileage_rate,
            "loaded_mileage_only": loaded_only,
        }
    )
    db.car_types[row["id"]] = row
    return response.ok(serialize.car_type(row), 201)


@bp.get("/car-hire/car-types")
@endpoint(roles=db.ALL_ROLES)
def list_car_types():
    response.page_params()
    code = shapes.q_str("car_type_code")
    mode = shapes.q_enum("time_component_mode", db.TIME_COMPONENT_MODE)
    rows = list(db.car_types.values())
    if code is not None:
        rows = [r for r in rows if r["car_type_code"] == code]
    if mode is not None:
        rows = [r for r in rows if r["time_component_mode"] == mode]
    rows.sort(key=db.order_key)
    return response.paginate(rows, serialize.car_type)


@bp.get("/car-hire/car-types/<car_type_id>")
@endpoint(roles=db.ALL_ROLES, path_params=[("car_type_id", "car_type")])
def read_car_type(car_type):
    return response.ok(serialize.car_type(car_type))


# --------------------------------------------------------------------------
# junctions
# --------------------------------------------------------------------------
@bp.post("/car-hire/junctions")
@endpoint(roles=[db.ROLE_ADMIN])
def create_junction():
    body = shapes.body()
    code = shapes.s_str(body, "junction_code")
    name = shapes.s_str(body, "name")
    road_a_id = shapes.s_id(body, "road_a_id")
    road_b_id = shapes.s_id(body, "road_b_id")
    status = shapes.s_str(body, "status", required=False, default="OPEN")
    if road_a_id == road_b_id:
        fail("ERR_INVALID_REQUEST", "road_a_id and road_b_id must differ.")
    shapes.check_enum("status", status, db.JUNCTION_STATUS)
    db.lookup("railroad", road_a_id)
    db.lookup("railroad", road_b_id)
    if any(j["junction_code"] == code for j in db.junctions.values()):
        fail("ERR_DUPLICATE_RESOURCE", "junction_code is already registered.")

    row = db.base_row()
    row.update(
        {
            "junction_code": code,
            "name": name,
            "road_a_id": road_a_id,
            "road_b_id": road_b_id,
            "status": status,
        }
    )
    db.junctions[row["id"]] = row
    return response.ok(serialize.junction(row), 201)


@bp.get("/car-hire/junctions")
@endpoint(roles=db.ALL_ROLES)
def list_junctions():
    response.page_params()
    status = shapes.q_enum("status", db.JUNCTION_STATUS)
    road_a_id = shapes.q_str("road_a_id")
    road_b_id = shapes.q_str("road_b_id")
    code = shapes.q_str("junction_code")
    rows = list(db.junctions.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if road_a_id is not None:
        rows = [r for r in rows if r["road_a_id"] == road_a_id]
    if road_b_id is not None:
        rows = [r for r in rows if r["road_b_id"] == road_b_id]
    if code is not None:
        rows = [r for r in rows if r["junction_code"] == code]
    rows.sort(key=db.order_key)
    return response.paginate(rows, serialize.junction)


@bp.get("/car-hire/junctions/<junction_id>")
@endpoint(roles=db.ALL_ROLES, path_params=[("junction_id", "junction")])
def read_junction(junction):
    return response.ok(serialize.junction(junction))

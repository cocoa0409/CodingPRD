"""Membership plans, technicians, styles, rental units and the logical clock."""
import string

from flask import Blueprint, request

import calc
import core
import serialize
import services
from core import (CATEGORIES, CLOCK, CONDITION_GRADES, DB, RETIREMENT_REASONS,
                  SIZES, TECH_STATUSES, UNIT_AVAILABILITY, UNIT_CONDITION,
                  fail, now_iso, ok, ok_list, parse_instant, fmt_ts)
from guards import (begin, body_json, check_duplicate, enum_query, lookup,
                    pagination, paginate, sort_rows, str_query, bool_query, validate)

bp = Blueprint("catalog", __name__)

CODE_CHARS = set(string.ascii_uppercase + string.digits + "-")
ALL_ROLES = ["Member", "WarehouseTech", "ClaimsAdjuster", "InventoryPlanner",
             "PlatformAdmin"]


# ---------------------------------------------------------------------------
# Membership plans
# ---------------------------------------------------------------------------
@bp.post("/membership-plans")
def create_plan():
    begin(["PlatformAdmin"])
    body = body_json()
    data = validate(body, [
        {"name": "code", "kind": "str", "required": True, "minlen": 3,
         "maxlen": 24, "charset": CODE_CHARS},
        {"name": "name", "kind": "str", "required": True, "minlen": 1},
        {"name": "item_slots", "kind": "int", "required": True, "min": 1, "max": 8},
        {"name": "monthly_fee_cents", "kind": "int", "required": True, "min": 0},
        {"name": "monthly_swaps_allowed", "kind": "int", "required": True, "min": 0},
        {"name": "shipping_cadence_days", "kind": "int", "required": True, "min": 1},
        {"name": "waiver_monthly_fee_cents", "kind": "int", "required": True, "min": 0},
        {"name": "waiver_coverage_cents", "kind": "int", "required": True, "min": 0},
    ])
    check_duplicate("membership_plans", "code", data["code"])
    row = services.base_row("membership_plans")
    row.update(data)
    DB["membership_plans"][row["id"]] = row
    return ok(serialize.plan_out(row), 201)


@bp.get("/membership-plans/<plan_id>")
def get_plan(plan_id):
    begin(ALL_ROLES)
    row = lookup("membership_plans", plan_id, "ERR_PLAN_NOT_FOUND")
    return ok(serialize.plan_out(row))


@bp.get("/membership-plans")
def list_plans():
    begin(ALL_ROLES)
    limit, offset = pagination()
    rows = sort_rows(list(DB["membership_plans"].values()))
    items, total = paginate(rows, limit, offset, serialize.plan_out)
    return ok_list(items, limit, offset, total)


# ---------------------------------------------------------------------------
# Technicians
# ---------------------------------------------------------------------------
@bp.post("/technicians")
def create_technician():
    begin(["PlatformAdmin"])
    body = body_json()
    data = validate(body, [
        {"name": "employee_code", "kind": "str", "required": True, "minlen": 2,
         "maxlen": 16},
        {"name": "full_name", "kind": "str", "required": True, "minlen": 1},
        {"name": "repair_certified", "kind": "bool", "default": False},
        {"name": "photography_certified", "kind": "bool", "default": False},
        {"name": "status", "kind": "enum", "values": TECH_STATUSES, "default": "ACTIVE"},
    ])
    check_duplicate("technicians", "employee_code", data["employee_code"])
    row = services.base_row("technicians")
    row.update(data)
    DB["technicians"][row["id"]] = row
    return ok(serialize.technician_out(row), 201)


@bp.patch("/technicians/<technician_id>")
def patch_technician(technician_id):
    begin(["PlatformAdmin"])
    row = lookup("technicians", technician_id, "ERR_TECHNICIAN_NOT_FOUND")
    body = body_json()
    data = validate(body, [
        {"name": "repair_certified", "kind": "bool"},
        {"name": "photography_certified", "kind": "bool"},
        {"name": "status", "kind": "enum", "values": TECH_STATUSES},
    ])
    for key in ("repair_certified", "photography_certified", "status"):
        if key in data:
            row[key] = data[key]
    services.touch(row)
    return ok(serialize.technician_out(row))


@bp.get("/technicians/<technician_id>")
def get_technician(technician_id):
    begin(["WarehouseTech", "ClaimsAdjuster", "PlatformAdmin"])
    row = lookup("technicians", technician_id, "ERR_TECHNICIAN_NOT_FOUND")
    return ok(serialize.technician_out(row))


@bp.get("/technicians")
def list_technicians():
    begin(["WarehouseTech", "ClaimsAdjuster", "PlatformAdmin"])
    status = enum_query("status", TECH_STATUSES)
    limit, offset = pagination()
    rows = [r for r in DB["technicians"].values()
            if status is None or r["status"] == status]
    rows = sort_rows(rows)
    items, total = paginate(rows, limit, offset, serialize.technician_out)
    return ok_list(items, limit, offset, total)


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------
@bp.post("/styles")
def create_style():
    begin(["InventoryPlanner"])
    body = body_json()
    data = validate(body, [
        {"name": "style_code", "kind": "str", "required": True, "minlen": 3,
         "maxlen": 32},
        {"name": "brand", "kind": "str", "required": True, "minlen": 1},
        {"name": "category", "kind": "enum", "required": True, "values": CATEGORIES},
        {"name": "retail_price_cents", "kind": "int", "required": True, "min": 1},
        {"name": "acquisition_cost_cents", "kind": "int", "required": True, "min": 1},
        {"name": "size_run", "kind": "enum_list", "required": True,
         "values": SIZES, "non_empty": True},
        {"name": "expected_rental_turns_per_unit", "kind": "int", "required": True,
         "min": 1},
        {"name": "planned_depth_units", "kind": "int", "min": 0, "default": 0},
        {"name": "planned_eol_value_cents", "kind": "int", "min": 0, "default": 0},
        {"name": "forecast_monthly_requests", "kind": "int", "min": 0, "default": 0},
        {"name": "avg_rental_days", "kind": "int", "min": 0, "default": 0},
    ])
    check_duplicate("styles", "style_code", data["style_code"])
    row = services.base_row("styles")
    row.update(data)
    DB["styles"][row["id"]] = row
    return ok(serialize.style_out(row), 201)


@bp.patch("/styles/<style_id>/depth-plan")
def patch_depth_plan(style_id):
    begin(["InventoryPlanner"])
    row = lookup("styles", style_id, "ERR_STYLE_NOT_FOUND")
    body = body_json()
    data = validate(body, [
        {"name": "forecast_monthly_requests", "kind": "int", "min": 0},
        {"name": "avg_rental_days", "kind": "int", "min": 0},
        {"name": "planned_depth_units", "kind": "int", "min": 0},
    ])
    for key in ("forecast_monthly_requests", "avg_rental_days", "planned_depth_units"):
        if key in data:
            row[key] = data[key]
    services.touch(row)
    return ok(serialize.style_out(row))


@bp.get("/styles/<style_id>")
def get_style(style_id):
    begin(ALL_ROLES)
    row = lookup("styles", style_id, "ERR_STYLE_NOT_FOUND")
    return ok(serialize.style_out(row))


@bp.get("/styles")
def list_styles():
    begin(ALL_ROLES)
    category = enum_query("category", CATEGORIES)
    flag = bool_query("replenishment_flag")
    limit, offset = pagination()
    rows = []
    for r in DB["styles"].values():
        if category is not None and r["category"] != category:
            continue
        if flag is not None and calc.style_depth(r)["replenishment_flag"] != flag:
            continue
        rows.append(r)
    rows = sort_rows(rows)
    items, total = paginate(rows, limit, offset, serialize.style_out)
    return ok_list(items, limit, offset, total)


@bp.get("/styles/<style_id>/unit-economics")
def style_unit_economics(style_id):
    begin(["InventoryPlanner", "PlatformAdmin"])
    row = lookup("styles", style_id, "ERR_STYLE_NOT_FOUND")
    variant = enum_query("variant", core.ECON_VARIANTS) or "REALIZED"
    return ok(calc.unit_economics(row, variant))


# ---------------------------------------------------------------------------
# Rental units
# ---------------------------------------------------------------------------
@bp.post("/styles/<style_id>/rental-units")
def create_rental_unit(style_id):
    begin(["InventoryPlanner"])
    style = lookup("styles", style_id, "ERR_STYLE_NOT_FOUND")
    body = body_json()
    data = validate(body, [
        {"name": "unit_code", "kind": "str", "required": True, "minlen": 3,
         "maxlen": 40},
        {"name": "size", "kind": "enum", "required": True, "values": SIZES},
        {"name": "acquisition_cost_cents", "kind": "int", "min": 1},
        {"name": "condition_grade", "kind": "enum", "values": CONDITION_GRADES,
         "default": "A"},
    ])
    if data["size"] not in style["size_run"]:
        fail("ERR_SIZE_NOT_IN_SIZE_RUN",
             "size %s is not in the style's size run" % data["size"])
    check_duplicate("rental_units", "unit_code", data["unit_code"])
    row = services.base_row("rental_units")
    row.update({
        "style_id": style["id"],
        "unit_code": data["unit_code"],
        "size": data["size"],
        "acquisition_cost_cents": data.get("acquisition_cost_cents")
                                  or style["acquisition_cost_cents"],
        "condition_grade": data["condition_grade"],
        "availability_state": "IN_STOCK",
        "condition_state": "FLOOR_READY",
        "turns_completed": 0,
        "quarantine_hold": False,
        "last_returned_at": None,
        "retired_at": None,
        "retirement_reason": None,
    })
    DB["rental_units"][row["id"]] = row
    return ok(serialize.unit_out(row), 201)


@bp.get("/rental-units/<unit_id>")
def get_rental_unit(unit_id):
    begin(ALL_ROLES)
    row = lookup("rental_units", unit_id, "ERR_RENTAL_UNIT_NOT_FOUND")
    return ok(serialize.unit_out(row))


@bp.get("/rental-units")
def list_rental_units():
    begin(ALL_ROLES)
    availability = enum_query("availability_state", UNIT_AVAILABILITY)
    condition = enum_query("condition_state", UNIT_CONDITION)
    style_id = str_query("style_id")
    size = str_query("size")
    limit, offset = pagination()
    rows = []
    for r in DB["rental_units"].values():
        if style_id is not None and r["style_id"] != style_id:
            continue
        if size is not None and r["size"] != size:
            continue
        if availability is not None and r["availability_state"] != availability:
            continue
        if condition is not None and r["condition_state"] != condition:
            continue
        rows.append(r)
    rows = sort_rows(rows)
    items, total = paginate(rows, limit, offset, serialize.unit_out)
    return ok_list(items, limit, offset, total)


@bp.post("/rental-units/<unit_id>/retirement")
def retire_rental_unit(unit_id):
    begin(["InventoryPlanner"])
    unit = lookup("rental_units", unit_id, "ERR_RENTAL_UNIT_NOT_FOUND")
    body = body_json()
    data = validate(body, [
        {"name": "retirement_reason", "kind": "enum", "required": True,
         "values": RETIREMENT_REASONS},
    ])
    # Rank 15 / 16
    if unit["availability_state"] == "SOLD":
        fail("ERR_RESOURCE_TERMINAL", "Unit is SOLD")
    if unit["availability_state"] not in ("IN_STOCK", "PROCESSING"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "Retirement is not declared from %s" % unit["availability_state"])
    # Rank 45
    for r in DB["reservations"].values():
        if (r["allocated_unit_id"] == unit["id"]
                and r["state"] in ("MATCHED", "SHIPPED", "IN_POSSESSION",
                                   "RETURN_INITIATED")):
            fail("ERR_UNIT_HAS_ACTIVE_COMMITMENT",
                 "A reservation still commits this unit")
    for c in DB["damage_claims"].values():
        if (c["rental_unit_id"] == unit["id"]
                and c["state"] in ("OPEN", "ASSESSED", "DISPUTED")):
            fail("ERR_UNIT_HAS_ACTIVE_COMMITMENT",
                 "An unsettled damage claim exists on this unit")
    services.retire_unit(unit, data["retirement_reason"])
    return ok(serialize.unit_out(unit))


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    begin(["PlatformAdmin"])
    body = body_json()
    validate(body, [
        {"name": "current_utc", "kind": "instant", "required": True},
    ])
    CLOCK["now"] = parse_instant(body["current_utc"])
    return ok({"current_utc": fmt_ts(CLOCK["now"])})

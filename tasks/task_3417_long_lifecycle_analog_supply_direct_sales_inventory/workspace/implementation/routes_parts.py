# Parts & inventory routes (PRD 3.1).
from flask import Blueprint, request

import constants as C
import derive
from auth import require_roles
from envelope import list_response, success
from errors import (
    ApiError,
    ERR_DUPLICATE_PART_NUMBER,
    ERR_INVALID_STATE,
    ERR_POOL_CAPACITY_EXCEEDED,
    ERR_POOL_NOT_OPEN,
    ERR_SITE_NOT_QUALIFIED,
)
from lookups import get_capacity_pool, get_part
from serialize import eol_notice_public, part_public, pricing_schedule_public
from store import store
from validate import (
    as_bool,
    as_enum,
    as_int_at_least,
    as_number,
    as_str,
    bad,
    check_unknown_fields,
    get_body,
    require_fields,
)

bp = Blueprint("parts", __name__)

_CREATE_ALLOWED = {
    "part_number",
    "description",
    "package_family",
    "process_technology",
    "automotive_grade",
    "demand_rate_units_per_week",
    "buffer_multiple",
}
_PATCH_ALLOWED = {"demand_rate_units_per_week", "buffer_multiple", "lifecycle_status"}
_RECEIPT_ALLOWED = {"capacity_pool_id", "units"}


@bp.post("/parts")
def create_part():
    require_roles("SupplyPlanner")
    body = get_body(required=True)
    # Priority row 4 checks in written order: required, unknown, types, enums,
    # ranges, then part_number uniqueness.
    require_fields(body, ["part_number", "description", "package_family", "process_technology"])
    check_unknown_fields(body, _CREATE_ALLOWED)
    part_number = as_str(body["part_number"], "part_number")
    description = as_str(body["description"], "description")
    package_family = as_str(body["package_family"], "package_family")
    process_technology = as_str(body["process_technology"], "process_technology")
    automotive_grade = False
    if "automotive_grade" in body:
        automotive_grade = as_bool(body["automotive_grade"], "automotive_grade")
    demand_rate = 0
    if "demand_rate_units_per_week" in body:
        demand_rate = as_int_at_least(body["demand_rate_units_per_week"], "demand_rate_units_per_week", 0)
    buffer_multiple = C.BUFFER_MULTIPLE_DEFAULT
    if "buffer_multiple" in body:
        buffer_multiple = as_number(body["buffer_multiple"], "buffer_multiple")
        if buffer_multiple < 0:
            bad("buffer_multiple must be >= 0")
    for existing in store.parts.values():
        if existing["part_number"] == part_number:
            raise ApiError(ERR_DUPLICATE_PART_NUMBER, 409, "part_number already registered: %s" % part_number)
    part = {
        "part_number": part_number,
        "description": description,
        "package_family": package_family,
        "process_technology": process_technology,
        "automotive_grade": automotive_grade,
        "lifecycle_status": "ACTIVE",
        "demand_rate_units_per_week": demand_rate,
        "buffer_multiple": buffer_multiple,
        "on_hand_units": 0,
    }
    part.update(store.stamp())
    store.parts[part["id"]] = part
    return success(part_public(part), 201)


@bp.get("/parts/<part_id>")
def fetch_part(part_id):
    require_roles("PlatformAdmin", "SupplyPlanner", "ChannelManager", "FieldEngineer", "QualityEngineer", "Customer")
    return success(part_public(get_part(part_id)))


@bp.patch("/parts/<part_id>")
def patch_part(part_id):
    require_roles("SupplyPlanner")
    part = get_part(part_id)
    body = get_body(required=True)
    check_unknown_fields(body, _PATCH_ALLOWED)
    new_demand = part["demand_rate_units_per_week"]
    new_buffer = part["buffer_multiple"]
    new_lifecycle = None
    if "demand_rate_units_per_week" in body:
        new_demand = as_int_at_least(body["demand_rate_units_per_week"], "demand_rate_units_per_week", 0)
    if "buffer_multiple" in body:
        new_buffer = as_number(body["buffer_multiple"], "buffer_multiple")
        if new_buffer < 0:
            bad("buffer_multiple must be >= 0")
    if "lifecycle_status" in body:
        requested = as_enum(body["lifecycle_status"], "lifecycle_status", C.LIFECYCLE_STATUSES)
        current = part["lifecycle_status"]
        # Only ACTIVE <-> NRND toggles are legal via this maintenance endpoint.
        if (current, requested) in (("ACTIVE", "NRND"), ("NRND", "ACTIVE")):
            new_lifecycle = requested
        else:
            raise ApiError(
                ERR_INVALID_STATE, 409,
                "lifecycle transition %s -> %s is not permitted" % (current, requested),
            )
    part["demand_rate_units_per_week"] = new_demand
    part["buffer_multiple"] = new_buffer
    if new_lifecycle is not None:
        part["lifecycle_status"] = new_lifecycle
    store.touch(part)
    return success(part_public(part))


@bp.get("/parts/<part_id>/inventory-position")
def get_inventory_position(part_id):
    require_roles("PlatformAdmin", "SupplyPlanner", "ChannelManager")
    return success(derive.inventory_position(get_part(part_id)))


@bp.get("/parts/<part_id>/pricing-schedules")
def list_part_pricing_schedules(part_id):
    require_roles("PlatformAdmin", "SupplyPlanner", "ChannelManager", "Customer")
    part = get_part(part_id)
    status_filter = request.args.get("status")
    schedules = [s for s in store.pricing_schedules.values() if s["part_id"] == part["id"]]
    if status_filter is not None:
        schedules = [s for s in schedules if s["status"] == status_filter]
    # Explicit exception to the default ordering: newest effective_from first.
    schedules.sort(key=lambda s: (s["effective_from"], ), reverse=True)
    return list_response(schedules, pricing_schedule_public)


@bp.get("/parts/<part_id>/eol-notices")
def list_part_eol_notices(part_id):
    require_roles("PlatformAdmin", "SupplyPlanner", "ChannelManager", "Customer")
    part = get_part(part_id)
    status_filter = request.args.get("status")
    notices = [n for n in store.eol_notices.values() if n["part_id"] == part["id"]]
    if status_filter is not None:
        notices = [n for n in notices if n["status"] == status_filter]
    notices.sort(key=lambda n: n["seq"])
    return list_response(notices, eol_notice_public)


@bp.post("/parts/<part_id>/receipts")
def record_receipt(part_id):
    require_roles("SupplyPlanner")
    part = get_part(part_id)
    body = get_body(required=True)
    # Existence (row 3) of the body-referenced pool precedes schema (row 4).
    pool = None
    if "capacity_pool_id" in body and body["capacity_pool_id"] is not None:
        pool = get_capacity_pool(body["capacity_pool_id"])
    require_fields(body, ["capacity_pool_id", "units"])
    check_unknown_fields(body, _RECEIPT_ALLOWED)
    as_str(body["capacity_pool_id"], "capacity_pool_id")
    units = as_int_at_least(body["units"], "units", 1)
    # Row 6: automotive compliance.
    if part["automotive_grade"] and not derive.site_qualified_for_automotive(pool["site_name"]):
        raise ApiError(ERR_SITE_NOT_QUALIFIED, 422, "Receiving site %s lacks a QUALIFIED automotive site qualification" % pool["site_name"])
    # Row 8: pool must be OPEN at the current logical clock.
    if derive.pool_status(pool) != "OPEN":
        raise ApiError(ERR_POOL_NOT_OPEN, 422, "Capacity pool is not OPEN")
    # Row 10: pool headroom.
    if units > pool["total_units"] - pool["allocated_units"]:
        raise ApiError(ERR_POOL_CAPACITY_EXCEEDED, 422, "Receipt exceeds remaining pool capacity")
    part["on_hand_units"] += units
    store.touch(part)
    pool["allocated_units"] += units
    store.touch(pool)
    return success(part_public(part), 201)

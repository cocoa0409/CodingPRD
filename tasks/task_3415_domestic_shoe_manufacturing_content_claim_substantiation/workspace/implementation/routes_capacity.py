"""CapacityAllocation endpoints (PRD 3.4): create, list, get, lock, shift,
reconcile."""
from flask import Blueprint, request

import calcs
import constants
import serializers
from errors import ApiError
from middleware import require_roles
from response import ok_obj, list_response
from state import DB, base_fields, touch, sorted_items
from validation import body, req_str, req_int, req_enum, req_iso_week

bp = Blueprint("capacity", __name__)


def get_allocation(aid):
    a = DB["allocations"].get(aid)
    if a is None:
        raise ApiError("ERR_ALLOCATION_NOT_FOUND", "capacity allocation id does not resolve")
    return a


@bp.post("/footwear/capacity-allocations")
@require_roles("PlatformAdmin")
def create_allocation(_uid, _role):
    b = body()
    # Family 4 (existence) precedes family 5 (schema).
    fid = b.get("factory_id")
    if fid is not None and fid not in DB["factories"]:
        raise ApiError("ERR_FACTORY_NOT_FOUND", "factory id does not resolve")
    fid = req_str(b, "factory_id")
    week = req_iso_week(b, "iso_week")
    total = req_int(b, "total_reserved_units", min_v=0)
    # Family 9 (structural): one allocation per (factory_id, iso_week).
    if any(a["factory_id"] == fid and a["iso_week"] == week
           for a in DB["allocations"].values()):
        raise ApiError(
            "ERR_ALLOCATION_ALREADY_EXISTS",
            "an allocation already exists for this (factory_id, iso_week)",
        )
    # Family 11 (fiscal): the total must fit within the factory's weekly capacity.
    factory = DB["factories"][fid]
    if total > factory["weekly_capacity_units"]:
        raise ApiError(
            "ERR_TOTAL_EXCEEDS_WEEKLY_CAPACITY",
            "total_reserved_units exceeds the factory's weekly_capacity_units",
        )
    a = base_fields()
    a.update({
        "factory_id": fid,
        "iso_week": week,
        "total_reserved_units": total,
        "domestic_reserved_units": 0,
        "import_reserved_units": total,
        "status": "OPEN",
    })
    DB["allocations"][a["id"]] = a
    return ok_obj(serializers.pub(a), 201)


@bp.get("/footwear/capacity-allocations")
@require_roles(*constants.ALL_ROLES)
def list_allocations(_uid, _role):
    items = sorted_items(DB["allocations"])
    fid = request.args.get("factory_id")
    week = request.args.get("iso_week")
    status = request.args.get("status")
    if fid is not None:
        items = [a for a in items if a["factory_id"] == fid]
    if week is not None:
        items = [a for a in items if a["iso_week"] == week]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return list_response([serializers.pub(a) for a in items])


@bp.get("/footwear/capacity-allocations/<aid>")
@require_roles(*constants.ALL_ROLES)
def get_one_allocation(aid, _uid, _role):
    return ok_obj(serializers.pub(get_allocation(aid)))


@bp.post("/footwear/capacity-allocations/<aid>/lock")
@require_roles("PlatformAdmin")
def lock_allocation(aid, _uid, _role):
    a = get_allocation(aid)
    if a["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "only an OPEN allocation can be locked")
    calcs.capacity_waterfall(a)
    a["status"] = "LOCKED"
    touch(a)
    return ok_obj(serializers.pub(a))


@bp.post("/footwear/capacity-allocations/<aid>/shift")
@require_roles("PlatformAdmin")
def shift_allocation(aid, _uid, _role):
    a = get_allocation(aid)
    # Family 5 (schema): direction, units >= 1, non-optional OCC field.
    b = body()
    direction = req_enum(b, "direction", constants.SHIFT_DIRECTIONS)
    units = req_int(b, "units", min_v=1)
    expected = req_int(b, "expected_allocation_version")
    # Family 6 (state).
    if a["status"] != "LOCKED":
        raise ApiError("ERR_ALLOCATION_NOT_LOCKED", "the allocation must be LOCKED to shift")
    # Family 11 (fiscal): source bucket limit, then the consumed floor.
    if direction == "TO_DOMESTIC":
        if units > a["import_reserved_units"]:
            raise ApiError(
                "ERR_SHIFT_EXCEEDS_SOURCE",
                "shift units exceed the import_reserved_units source bucket",
            )
    else:  # TO_IMPORT
        if units > a["domestic_reserved_units"]:
            raise ApiError(
                "ERR_SHIFT_EXCEEDS_SOURCE",
                "shift units exceed the domestic_reserved_units source bucket",
            )
        consumed = sum(
            r["planned_units"] for r in DB["runs"].values()
            if r["factory_id"] == a["factory_id"] and r["iso_week"] == a["iso_week"]
            and r["status"] in constants.CONSUMED_RUN_STATES
        )
        if a["domestic_reserved_units"] - units < consumed:
            raise ApiError(
                "ERR_SHIFT_BELOW_CONSUMED",
                "the shift would leave domestic_reserved_units below units already consumed",
            )
    # Family 12 (OCC) is the final gate.
    if expected != a["version"]:
        raise ApiError(
            "ERR_STALE_ALLOCATION_VERSION",
            "expected_allocation_version does not match the allocation's current version",
        )
    if direction == "TO_DOMESTIC":
        a["domestic_reserved_units"] += units
        a["import_reserved_units"] -= units
    else:
        a["domestic_reserved_units"] -= units
        a["import_reserved_units"] += units
    touch(a)
    return ok_obj(serializers.pub(a))


@bp.post("/footwear/capacity-allocations/<aid>/reconcile")
@require_roles("PlatformAdmin")
def reconcile_allocation(aid, _uid, _role):
    a = get_allocation(aid)
    if a["status"] != "LOCKED":
        raise ApiError("ERR_INVALID_STATE", "only a LOCKED allocation can be reconciled")
    if any(r["factory_id"] == a["factory_id"] and r["iso_week"] == a["iso_week"]
           and r["status"] in constants.OPEN_RUN_STATES
           for r in DB["runs"].values()):
        raise ApiError(
            "ERR_WEEK_RUNS_OPEN",
            "runs of this (factory, iso_week) are still non-terminal",
        )
    a["status"] = "RECONCILED"
    touch(a)
    return ok_obj(serializers.pub(a))

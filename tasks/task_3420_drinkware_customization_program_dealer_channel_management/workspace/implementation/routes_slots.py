"""Print slots: capacity windows with half-open overlap rules, the 20-minute
cross-technology changeover buffer, lazy CLOSED evaluation, and locking."""
from flask import Blueprint, request

from auth import context, require_roles
from calc import slot_overlap_conflict
from constants import PEAK_WINDOW_END, PEAK_WINDOW_START
from envelope import (
    get_body, new_entity, req_dt, req_enum, req_int, req_str, sort_created,
    success, success_list, touch,
)
from errors import fail
from serialize import ser_slot
from store import DB

bp = Blueprint("slots", __name__)

TECHNOLOGIES = ("LASER", "PAD")
ALL_ROLES_READ = [
    "PlatformAdmin", "ChannelManager", "FieldInspector", "Dealer", "Buyer",
    "PrepressTech", "ProductionLead", "WarrantyAgent", "CustomerCare",
]


def load_slot(slot_id):
    s = DB.slots.get(slot_id)
    if s is None:
        fail("ERR_SLOT_NOT_FOUND", "no print slot with id %s" % slot_id)
    return s


@bp.post("/drinkware/print-slots")
def create_slot():
    _, role = context()
    require_roles(role, ["ProductionLead"])
    body = get_body()
    station_code = req_str(body, "station_code")
    technology = req_enum(body, "technology", TECHNOLOGIES)
    window_start = req_dt(body, "window_start")
    window_end = req_dt(body, "window_end")
    capacity_minutes = req_int(body, "capacity_minutes", minimum=1)
    if slot_overlap_conflict(station_code, technology, window_start, window_end):
        fail("ERR_SLOT_OVERLAP_CONFLICT",
             "window collides with another slot on this station (half-open overlap or < 20-minute changeover)")
    if window_end <= window_start:
        fail("ERR_INVALID_WINDOW_ORDER", "window_end must be after window_start")
    duration_minutes = int((window_end - window_start).total_seconds() // 60)
    if capacity_minutes > duration_minutes:
        fail("ERR_CAPACITY_EXCEEDS_WINDOW",
             "capacity_minutes may not exceed the window's duration in minutes")
    peak_overlap = window_start < PEAK_WINDOW_END and PEAK_WINDOW_START < window_end
    slot = new_entity({
        "station_code": station_code,
        "technology": technology,
        "window_start": window_start,
        "window_end": window_end,
        "capacity_minutes": capacity_minutes,
        "peak_overlap": peak_overlap,
        "status": "OPEN",
    })
    DB.slots[slot["id"]] = slot
    return success(ser_slot(slot), 201)


@bp.get("/drinkware/print-slots/<slot_id>")
def get_slot(slot_id):
    _, role = context()
    require_roles(role, ALL_ROLES_READ)
    return success(ser_slot(load_slot(slot_id)))


@bp.get("/drinkware/print-slots")
def list_slots():
    _, role = context()
    require_roles(role, ALL_ROLES_READ)
    station_code = request.args.get("station_code")
    technology = request.args.get("technology")
    status = request.args.get("status")
    items = sort_created(list(DB.slots.values()))
    if station_code is not None:
        items = [s for s in items if s["station_code"] == station_code]
    if technology is not None:
        items = [s for s in items if s["technology"] == technology]
    if status is not None:
        for s in items:
            from calc import refresh_slot
            refresh_slot(s)
        items = [s for s in items if s["status"] == status]
    return success_list([ser_slot(s) for s in items])


@bp.post("/drinkware/print-slots/<slot_id>/lock")
def lock_slot(slot_id):
    _, role = context()
    require_roles(role, ["ProductionLead"])
    slot = load_slot(slot_id)
    get_body()
    from calc import refresh_slot
    refresh_slot(slot)
    if slot["status"] != "OPEN":
        fail("ERR_INVALID_STATE_TRANSITION", "only an OPEN slot can be locked")
    slot["status"] = "LOCKED"
    touch(slot)
    return success(ser_slot(slot))

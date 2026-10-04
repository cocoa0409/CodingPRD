"""MaintenanceWindow endpoints."""
from flask import Blueprint

from core import (
    ApiError,
    D,
    body,
    db,
    dump,
    endpoint,
    f_dt,
    f_int,
    f_str,
    forbid_unless_owner_host,
    new_row,
    paginate,
    q_enum,
    q_str,
    respond_object,
    touch,
)
import svc

bp = Blueprint("windows", __name__, url_prefix="/rail/maintenance-windows")


def _serialize(row):
    out = dict(row)
    # window_hours and equipment_week_hours_available serialized as float (Decimal)
    return out


@bp.post("")
@endpoint("HostRailroadRep")
def create_window():
    payload = body()
    track_segment_id = f_str(payload, "track_segment_id")
    window_start_at = f_dt(payload, "window_start_at")
    window_end_at = f_dt(payload, "window_end_at")
    equipment_unit_id = f_str(payload, "equipment_unit_id")
    clearance_buffer_minutes = f_int(
        payload, "clearance_buffer_minutes", required=False, default=15, minimum=0
    )
    if window_end_at <= window_start_at:
        raise ApiError(
            "ERR_VALIDATION", "window_end_at must be greater than window_start_at."
        )
    segment = svc.need_segment(track_segment_id)
    forbid_unless_owner_host(svc.host_for_segment(segment))
    wh = svc.window_hours(window_start_at, window_end_at)
    avail = svc.equipment_available(equipment_unit_id, window_start_at)
    row = new_row(
        "maintenance_window",
        track_segment_id=track_segment_id,
        window_start_at=window_start_at,
        window_end_at=window_end_at,
        clearance_buffer_minutes=clearance_buffer_minutes,
        equipment_unit_id=equipment_unit_id,
        window_hours=wh,
        equipment_week_hours_available=avail,
        status="PLANNED",
    )
    db.maintenance_windows[row["id"]] = row
    return respond_object(dump(_serialize(row)), status=201)


@bp.get("")
@endpoint()
def list_windows():
    rows = list(db.maintenance_windows.values())
    track_segment_id = q_str("track_segment_id")
    equipment_unit_id = q_str("equipment_unit_id")
    status = q_enum("status", svc.WINDOW_STATUSES)
    if track_segment_id is not None:
        rows = [r for r in rows if r["track_segment_id"] == track_segment_id]
    if equipment_unit_id is not None:
        rows = [r for r in rows if r["equipment_unit_id"] == equipment_unit_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["window_start_at"], r["created_at"], r["_seq"]))
    return paginate(rows, dumper=lambda r: dump(_serialize(r)))


@bp.get("/<rid>")
@endpoint()
def get_window(rid):
    row = svc.need_window(rid)
    return respond_object(dump(_serialize(row)))


@bp.post("/<rid>/lock")
@endpoint("HostRailroadRep")
def lock_window(rid):
    row = svc.need_window(rid)
    segment = svc.need_segment(row["track_segment_id"])
    forbid_unless_owner_host(svc.host_for_segment(segment))
    if row["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", "Window is not PLANNED.")
    # Equipment budget check
    week_key = svc.iso_week_key(row["window_start_at"])
    consumed = svc.consumed_hours(row["equipment_unit_id"], week_key)
    if consumed + D(row["window_hours"]) > svc.WEEKLY_EQUIPMENT_ALLOWANCE_HOURS:
        raise ApiError(
            "ERR_EQUIPMENT_ALLOWANCE_EXCEEDED",
            "Locking this window would exceed the unit's weekly allowance.",
        )
    row["status"] = "LOCKED"
    touch(row)
    svc.refresh_window_availability(row["equipment_unit_id"], week_key)
    # Cascade: skip conflicting PLANNED passages on this segment
    svc.cascade_skip_passages_for_window(row)
    return respond_object(dump(_serialize(row)))


@bp.post("/<rid>/release")
@endpoint("HostRailroadRep")
def release_window(rid):
    row = svc.need_window(rid)
    segment = svc.need_segment(row["track_segment_id"])
    forbid_unless_owner_host(svc.host_for_segment(segment))
    if row["status"] not in ("PLANNED", "LOCKED"):
        raise ApiError("ERR_INVALID_STATE", "Window is not PLANNED or LOCKED.")
    was_locked = row["status"] == "LOCKED"
    row["status"] = "RELEASED"
    touch(row)
    if was_locked:
        week_key = svc.iso_week_key(row["window_start_at"])
        svc.refresh_window_availability(row["equipment_unit_id"], week_key)
    return respond_object(dump(_serialize(row)))

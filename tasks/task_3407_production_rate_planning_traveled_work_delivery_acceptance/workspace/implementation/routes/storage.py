"""Storage and preservation of undelivered aircraft (PRD 3.7)."""
from datetime import timedelta

from flask import Blueprint

import calc
import svc
from core import (
    ApiError,
    body,
    db,
    endpoint,
    f_dt,
    f_int,
    f_str,
    new_row,
    now,
    paginate,
    parse_dt,
    q_enum,
    respond_object,
    sort_created,
    touch,
)

bp = Blueprint("storage", __name__, url_prefix="/api")

STORAGE_STATUSES = ("ACTIVE", "RELEASED")


@bp.post("/aircraft-units/<aircraft_id>/storage-preservations")
@endpoint("DeliveryManager")
def create_storage(aircraft_id):
    aircraft = svc.need_aircraft(aircraft_id)
    payload = body()
    # rung 5 -- only an ASSEMBLY_COMPLETE aircraft can enter storage; creation
    # moves it to IN_STORAGE, so a second ACTIVE record is structurally blocked.
    if aircraft["production_status"] != "ASSEMBLY_COMPLETE":
        raise ApiError("ERR_INVALID_TRANSITION")
    # rung 7 -- closed window: window_end strictly after window_start
    window_start = parse_dt(payload.get("window_start"))
    window_end = parse_dt(payload.get("window_end"))
    if window_start is not None and window_end is not None and not window_end > window_start:
        raise ApiError("ERR_WINDOW_INVALID")
    # rung 8 -- closed window plus a 2-day turnaround buffer must not intersect
    # another ACTIVE preservation on the same bay_code (PRD 3.7).
    bay_code = payload.get("bay_code")
    if window_start is not None and window_end is not None and isinstance(bay_code, str):
        buffer = timedelta(days=calc.BAY_BUFFER_DAYS)
        for other in db.storages.values():
            if other["bay_code"] != bay_code or other["status"] != "ACTIVE":
                continue
            if (
                window_start <= other["window_end"] + buffer
                and other["window_start"] <= window_end + buffer
            ):
                raise ApiError("ERR_BAY_WINDOW_OVERLAP")
    # rung 10 -- body shape
    bay_code = f_str(payload, "bay_code")
    window_start = f_dt(payload, "window_start")
    window_end = f_dt(payload, "window_end")
    daily_rate_cents = f_int(payload, "daily_rate_cents", minimum=1)
    preservation_cycle_days = f_int(payload, "preservation_cycle_days", minimum=1)
    storage = new_row(
        "StoragePreservation",
        aircraft_id=aircraft["id"],
        bay_code=bay_code,
        window_start=window_start,
        window_end=window_end,
        daily_rate_cents=daily_rate_cents,
        preservation_cycle_days=preservation_cycle_days,
        last_preserved_at=window_start,
        status="ACTIVE",
    )
    db.storages[storage["id"]] = storage
    aircraft["production_status"] = "IN_STORAGE"
    touch(aircraft)
    return respond_object(svc.dump_storage(storage), 201)


@bp.get("/aircraft-units/<aircraft_id>/storage-preservations")
@endpoint("ProgramAdmin", "DeliveryManager")
def list_storages(aircraft_id):
    svc.need_aircraft(aircraft_id)
    status = q_enum("status", STORAGE_STATUSES)
    rows = [s for s in db.storages.values() if s["aircraft_id"] == aircraft_id]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    return paginate(sort_created(rows), svc.dump_storage)


@bp.post("/storage-preservations/<storage_id>/maintain")
@endpoint("DeliveryManager")
def maintain_storage(storage_id):
    storage = svc.need_storage(storage_id)
    if storage["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_TRANSITION")
    # Resets last_preserved_at to the logical clock; due date and overdue flag
    # recompute live at read time (PRD 3.7).
    storage["last_preserved_at"] = now()
    touch(storage)
    return respond_object(svc.dump_storage(storage))


@bp.post("/storage-preservations/<storage_id>/release")
@endpoint("DeliveryManager")
def release_storage(storage_id):
    storage = svc.need_storage(storage_id)
    # rung 5a -- state gate (RELEASED is terminal)
    if storage["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_TRANSITION")
    # rung 5b -- blocked while any rework order of the aircraft remains OPEN
    aircraft = svc.need_aircraft(storage["aircraft_id"])
    if svc.any_open_rework(aircraft["id"]):
        raise ApiError("ERR_REWORK_ORDERS_OPEN")
    storage["status"] = "RELEASED"
    touch(storage)
    aircraft["production_status"] = "ASSEMBLY_COMPLETE"
    touch(aircraft)
    return respond_object(svc.dump_storage(storage))

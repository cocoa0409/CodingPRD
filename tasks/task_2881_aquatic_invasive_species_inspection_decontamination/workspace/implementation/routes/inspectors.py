"""The inspection workforce: enrollment, training and standing (PRD 3.2)."""

from flask import Blueprint

import services
from envelope import created, ok
from errors import ApiError
from routes._common import ALL_ROLES, listing, matches, read_pagination
from store import base_row, db, fmt_iso, now, parse_iso, serialize, touch
from validate import (arg_bool_filter, arg_filter, opt_bool, opt_dt, opt_str,
                      read_body, req_bool, req_enum, req_num, req_ref, req_str,
                      require_auth)

bp = Blueprint("inspectors", __name__)

LEVELS = ("TRAINEE", "LEVEL_1", "LEVEL_2", "DECON_CERTIFIED")
INSPECTOR_STATUSES = ("PROBATIONARY", "ACTIVE", "SUSPENDED", "EXPIRED")


@bp.post("/inspectors")
def create_inspector():
    require_auth(("ProgramAdmin",))
    body = read_body()
    full_name = req_str(body, "full_name")
    home_station_id = req_ref(body, "home_station_id")
    endorsement = opt_bool(body, "decon_endorsement", False)

    services.station_or_404(home_station_id)

    row = base_row()
    row.update({
        "full_name": full_name,
        "home_station_id": home_station_id,
        "decon_endorsement": endorsement,
        "training_hours_total": 0,
        "certification_level": "TRAINEE",
        "certification_expires_at": None,
        "status": "PROBATIONARY",
    })
    db.inspectors[row["id"]] = row
    return created(serialize(row))


@bp.get("/inspectors/<iid>")
def get_inspector(iid):
    require_auth(ALL_ROLES)
    return ok(serialize(services.inspector_or_404(iid)))


@bp.get("/inspectors")
def list_inspectors():
    require_auth(ALL_ROLES)
    limit, offset = read_pagination()
    filters = {
        "home_station_id": arg_filter("home_station_id"),
        "certification_level": arg_filter("certification_level"),
        "status": arg_filter("status"),
        "decon_endorsement": arg_bool_filter("decon_endorsement"),
    }
    rows = [r for r in db.inspectors.values() if matches(r, filters)]
    return listing(rows, limit, offset)


@bp.post("/inspectors/<iid>/status")
def set_inspector_status(iid):
    require_auth(("ProgramAdmin",))
    body = read_body()
    target = req_enum(body, "target_status", INSPECTOR_STATUSES)
    opt_str(body, "reason", min_len=None)

    inspector = services.inspector_or_404(iid)
    current = inspector["status"]

    if target == "SUSPENDED" and current in ("PROBATIONARY", "ACTIVE"):
        inspector["status"] = "SUSPENDED"
    elif target == "ACTIVE" and current == "SUSPENDED":
        expires = parse_iso(inspector["certification_expires_at"])
        if inspector["certification_level"] == "TRAINEE":
            raise ApiError("ERR_INVALID_INSPECTOR_STATE")
        if expires is None or not (now() < expires):
            raise ApiError("ERR_INVALID_INSPECTOR_STATE")
        inspector["status"] = "ACTIVE"
    elif target == "ACTIVE" and current == "EXPIRED":
        if inspector["certification_level"] == "TRAINEE":
            raise ApiError("ERR_INVALID_INSPECTOR_STATE")
        inspector["status"] = "ACTIVE"
        services.stamp_certification_expiry(inspector)
    else:
        raise ApiError("ERR_INVALID_INSPECTOR_STATE")

    touch(inspector)
    services.station_staffing_cascade(inspector)
    return ok(serialize(inspector))


@bp.post("/inspectors/<iid>/training-records")
def create_training_record(iid):
    require_auth(("TrainingOfficer",))
    body = read_body()
    module_code = req_str(body, "module_code", max_len=32)
    hours = req_num(body, "hours", exclusive_min=0, max_decimals=2)
    passed = req_bool(body, "passed")
    completed_at = opt_dt(body, "completed_at")

    inspector = services.inspector_or_404(iid)

    row = base_row(with_mutable=False)
    row.update({
        "inspector_id": inspector["id"],
        "module_code": module_code,
        "hours": hours,
        "passed": passed,
        "completed_at": fmt_iso(completed_at),
    })
    db.training_records[row["id"]] = row
    services.recompute_training(inspector)
    return created(serialize(row))


@bp.get("/inspectors/<iid>/training-records")
def list_training_records(iid):
    require_auth(ALL_ROLES)
    limit, offset = read_pagination()
    inspector = services.inspector_or_404(iid)
    rows = [t for t in db.training_records.values()
            if t["inspector_id"] == inspector["id"]]
    return listing(rows, limit, offset)

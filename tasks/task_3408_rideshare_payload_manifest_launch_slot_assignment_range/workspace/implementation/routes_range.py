"""Range scheduling routes: range slots (request/reserve/confirm) and
exclusion windows (WEATHER range-scoped, COLA orbit-scoped)."""
from flask import Blueprint

from calc import cola_blocked, range_slot_conflicts
from envelope import success
from errors import (
    ERR_COLA_CONFLICT,
    ERR_INVALID_STATE,
    ERR_LICENSE_NOT_GRANTED,
    ERR_MISSION_NOT_FOUND,
    ERR_RANGE_SLOT_NOT_FOUND,
    ERR_RANGE_WINDOW_CONFLICT,
    ERR_WINDOW_INCOMPATIBLE,
    bad_request,
    conflict,
    not_found,
    unprocessable,
)
from middleware import require_roles
from serialize import ser_exclusion_window, ser_range_slot
from store import bump, db, new_append_only, new_entity
from validate import (
    as_dt,
    as_enum,
    as_str,
    body_json,
    check_window,
    req_field,
)

bp = Blueprint("range", __name__)

RANGE_CODES = {"CCAFS", "VAFB"}
ORBITS = {"SSO", "LEO", "GTO"}
SCOPE_TYPES = {"RANGE", "ORBIT"}
EXCLUSION_KINDS = {"WEATHER", "COLA"}


def _load_slot(sid):
    s = db["range_slots"].get(sid)
    if s is None:
        raise not_found(ERR_RANGE_SLOT_NOT_FOUND, f"range slot {sid} not found")
    return s


@bp.post("/rideshare/range-slots")
@require_roles("RangeOfficer")
def create_range_slot():
    body = body_json()
    mission_id = as_str(req_field(body, "mission_id"), "mission_id")
    range_code = as_enum(req_field(body, "range_code"), "range_code", RANGE_CODES)
    wopen = as_dt(req_field(body, "window_open_utc"), "window_open_utc")
    wclose = as_dt(req_field(body, "window_close_utc"), "window_close_utc")
    check_window(wopen, wclose)

    mission = db["missions"].get(mission_id)
    if mission is None:
        raise not_found(ERR_MISSION_NOT_FOUND, f"mission {mission_id} not found")

    s = new_entity()
    s.update(
        {
            "mission_id": mission["id"],
            "range_code": range_code,
            "window_open_utc": wopen,
            "window_close_utc": wclose,
            "status": "REQUESTED",
        }
    )
    db["range_slots"][s["id"]] = s
    return success(ser_range_slot(s), 201)


@bp.post("/rideshare/range-slots/<sid>/reserve")
@require_roles("RangeOfficer")
def reserve_range_slot(sid):
    s = _load_slot(sid)
    if s["status"] != "REQUESTED":
        raise conflict(
            ERR_INVALID_STATE, f"range slot is {s['status']}, expected REQUESTED"
        )
    if range_slot_conflicts(s):
        raise unprocessable(
            ERR_RANGE_WINDOW_CONFLICT,
            "slot violates the 45-minute turnaround buffer on this range",
        )
    s["status"] = "RESERVED"
    bump(s)
    return success(ser_range_slot(s))


@bp.post("/rideshare/range-slots/<sid>/confirm")
@require_roles("RangeOfficer")
def confirm_range_slot(sid):
    s = _load_slot(sid)
    if s["status"] != "RESERVED":
        raise conflict(
            ERR_INVALID_STATE, f"range slot is {s['status']}, expected RESERVED"
        )
    mission = db["missions"][s["mission_id"]]
    if mission["status"] != "MANIFEST_LOCKED":
        raise conflict(
            ERR_INVALID_STATE,
            f"mission is {mission['status']}, expected MANIFEST_LOCKED",
        )
    # regulatory gate: GRANTED LAUNCH_AUTHORIZATION valid through slot close
    licensed = any(
        lic["subject_type"] == "MISSION"
        and lic["mission_id"] == mission["id"]
        and lic["kind"] == "LAUNCH_AUTHORIZATION"
        and lic["status"] == "GRANTED"
        and lic["valid_until"] >= s["window_close_utc"]
        for lic in db["licenses"].values()
    )
    if not licensed:
        raise unprocessable(
            ERR_LICENSE_NOT_GRANTED,
            "mission holds no GRANTED LAUNCH_AUTHORIZATION valid through slot close",
        )
    if cola_blocked(mission["target_orbit"], s):
        raise unprocessable(
            ERR_COLA_CONFLICT,
            "slot window intersects a COLA exclusion window for the mission orbit",
        )
    if not (
        s["window_open_utc"] <= mission["window_open_utc"]
        and s["window_close_utc"] >= mission["window_close_utc"]
    ):
        raise unprocessable(
            ERR_WINDOW_INCOMPATIBLE,
            "slot window does not contain the mission window",
        )
    s["status"] = "CONFIRMED"
    bump(s)
    mission["status"] = "RANGE_SCHEDULED"
    bump(mission)
    return success(ser_range_slot(s))


@bp.post("/rideshare/exclusion-windows")
@require_roles("RangeOfficer")
def create_exclusion_window():
    body = body_json()
    scope_type = as_enum(req_field(body, "scope_type"), "scope_type", SCOPE_TYPES)
    scope_value = as_str(req_field(body, "scope_value"), "scope_value")
    kind = as_enum(req_field(body, "kind"), "kind", EXCLUSION_KINDS)
    start = as_dt(req_field(body, "start_utc"), "start_utc")
    end = as_dt(req_field(body, "end_utc"), "end_utc")
    check_window(start, end, "start_utc", "end_utc")

    # scope/kind coherence and scope_value domain
    if kind == "WEATHER" and scope_type != "RANGE":
        raise bad_request("WEATHER windows must be range-scoped")
    if kind == "COLA" and scope_type != "ORBIT":
        raise bad_request("COLA windows must be orbit-scoped")
    if scope_type == "RANGE" and scope_value not in RANGE_CODES:
        raise bad_request(
            f"scope_value must be one of {sorted(RANGE_CODES)} when scope_type is RANGE"
        )
    if scope_type == "ORBIT" and scope_value not in ORBITS:
        raise bad_request(
            f"scope_value must be one of {sorted(ORBITS)} when scope_type is ORBIT"
        )

    w = new_append_only()
    w.update(
        {
            "scope_type": scope_type,
            "scope_value": scope_value,
            "kind": kind,
            "start_utc": start,
            "end_utc": end,
        }
    )
    db["exclusion_windows"][w["id"]] = w
    return success(ser_exclusion_window(w), 201)

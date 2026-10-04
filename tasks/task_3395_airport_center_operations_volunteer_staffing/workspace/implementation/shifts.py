"""Shift and shift-assignment endpoints."""

from flask import Blueprint, request

from constants import SHIFT_ROLES
from helpers import (
    authn,
    base_entity,
    body,
    bump,
    err,
    get_assignment,
    get_center,
    get_shift,
    get_volunteer,
    now,
    paginate,
    req_datetime,
    req_enum,
    req_int,
    req_number,
    req_str,
    require_role,
    serialize,
    success_list,
    success_object,
    validation,
)
from services import (
    apply_no_show,
    recompute_center,
    refresh_shift_status,
    settle_affected_centers,
)
from storage import STORE

bp = Blueprint("shifts", __name__)

READ_ROLES = ("PlatformAdmin", "CenterManager", "Volunteer", "Guest")
ASSIGNMENT_READ_ROLES = ("PlatformAdmin", "CenterManager", "Volunteer")


# ---------------------------------------------------------------------------
# Shifts
# ---------------------------------------------------------------------------

@bp.route("/centers/<cid>/shifts", methods=["POST"])
def create_shift(cid):
    _, role = authn()
    require_role(role, ("CenterManager",))
    b = body()
    start_at = req_datetime(b, "start_at")
    end_at = req_datetime(b, "end_at")
    if not end_at > start_at:
        validation("end_at must be later than start_at")
    role_required = req_enum(b, "role_required", SHIFT_ROLES)
    capacity = req_int(b, "capacity", minimum=1)
    center = get_center(cid)

    shift = base_entity()
    shift.update({
        "center_id": center["id"],
        "start_at": start_at,
        "end_at": end_at,
        "role_required": role_required,
        "capacity": capacity,
        "confirmed_count": 0,
        "status": "OPEN",
    })
    STORE.shifts[shift["id"]] = shift
    return success_object(serialize(shift), status=201)


@bp.route("/centers/<cid>/shifts", methods=["GET"])
def list_shifts(cid):
    _, role = authn()
    require_role(role, READ_ROLES)
    center = get_center(cid)
    items = [s for s in STORE.shifts.values() if s["center_id"] == center["id"]]
    page, meta = paginate(items)
    return success_list(page, meta)


@bp.route("/shifts/<sid>", methods=["GET"])
def get_shift_route(sid):
    _, role = authn()
    require_role(role, READ_ROLES)
    shift = get_shift(sid)
    return success_object(serialize(shift))


# ---------------------------------------------------------------------------
# Assignments
# ---------------------------------------------------------------------------

@bp.route("/shifts/<sid>/assignments", methods=["POST"])
def create_assignment(sid):
    _, role = authn()
    require_role(role, ("CenterManager",))
    b = body()
    volunteer_id = req_str(b, "volunteer_id")
    shift = get_shift(sid)
    volunteer = get_volunteer(volunteer_id)

    if volunteer["status"] not in ("CLEARED", "ACTIVE"):
        err("ERR_VOLUNTEER_NOT_ELIGIBLE", 409, "Volunteer is not CLEARED or ACTIVE")

    # Half-open overlap against the volunteer's ASSIGNED/CONFIRMED shifts.
    for a in STORE.assignments.values():
        if a["volunteer_id"] != volunteer["id"]:
            continue
        if a["status"] not in ("ASSIGNED", "CONFIRMED"):
            continue
        s = STORE.shifts.get(a["shift_id"])
        if s is None:
            continue
        if shift["start_at"] < s["end_at"] and s["start_at"] < shift["end_at"]:
            err("ERR_SHIFT_OVERLAP", 409, "Shift overlaps an existing assignment of the volunteer")

    asg = base_entity()
    asg.update({
        "shift_id": shift["id"],
        "volunteer_id": volunteer["id"],
        "status": "ASSIGNED",
        "actual_hours": None,
    })
    STORE.assignments[asg["id"]] = asg
    return success_object(serialize(asg), status=201)


@bp.route("/shift-assignments/<aid>", methods=["GET"])
def get_assignment_route(aid):
    uid, role = authn()
    require_role(role, ASSIGNMENT_READ_ROLES)
    asg = get_assignment(aid)
    if role == "Volunteer" and asg["volunteer_id"] != uid:
        err("ERR_FORBIDDEN", 403, "Volunteers may only view their own assignments")
    return success_object(serialize(asg))


@bp.route("/shift-assignments", methods=["GET"])
def list_assignments():
    uid, role = authn()
    require_role(role, ASSIGNMENT_READ_ROLES)
    shift_id = request.args.get("shift_id")
    volunteer_id = request.args.get("volunteer_id")
    if role == "Volunteer":
        if volunteer_id is not None and volunteer_id != uid:
            err("ERR_FORBIDDEN", 403, "Volunteers are scoped to their own assignments")
        volunteer_id = uid
    items = list(STORE.assignments.values())
    if shift_id is not None:
        items = [a for a in items if a["shift_id"] == shift_id]
    if volunteer_id is not None:
        items = [a for a in items if a["volunteer_id"] == volunteer_id]
    page, meta = paginate(items)
    return success_list(page, meta)


@bp.route("/shift-assignments/<aid>/confirm", methods=["POST"])
def confirm_assignment(aid):
    uid, role = authn()
    require_role(role, ("Volunteer",))
    asg = get_assignment(aid)
    if asg["volunteer_id"] != uid:
        err("ERR_FORBIDDEN", 403, "A volunteer may confirm only its own assignment")
    if asg["status"] != "ASSIGNED":
        err("ERR_INVALID_STATE", 409, "Only an ASSIGNED assignment can be confirmed")

    volunteer = get_volunteer(asg["volunteer_id"])
    if volunteer["status"] not in ("CLEARED", "ACTIVE"):
        err("ERR_VOLUNTEER_NOT_ELIGIBLE", 409, "Volunteer is not CLEARED or ACTIVE")

    shift = STORE.shifts.get(asg["shift_id"])
    if shift["confirmed_count"] >= shift["capacity"]:
        err("ERR_SHIFT_FULL", 409, "Shift has no remaining capacity")

    asg["status"] = "CONFIRMED"
    bump(asg)

    shift["confirmed_count"] += 1
    refresh_shift_status(shift)
    bump(shift)

    if volunteer["status"] == "CLEARED":
        volunteer["status"] = "ACTIVE"
        bump(volunteer)

    center = STORE.centers.get(shift["center_id"])
    if center is not None:
        recompute_center(center)
    return success_object(serialize(asg))


@bp.route("/shift-assignments/<aid>/complete", methods=["POST"])
def complete_assignment(aid):
    _, role = authn()
    require_role(role, ("CenterManager",))
    b = body()
    actual_hours = req_number(b, "actual_hours")
    if not actual_hours > 0:
        validation("actual_hours must be greater than 0")
    asg = get_assignment(aid)
    if asg["status"] != "CONFIRMED":
        err("ERR_INVALID_STATE", 409, "Only a CONFIRMED assignment can be completed")
    shift = STORE.shifts.get(asg["shift_id"])
    if not shift["end_at"] <= now():
        err("ERR_INVALID_STATE", 409, "Shift has not ended yet")

    asg["status"] = "COMPLETED"
    asg["actual_hours"] = actual_hours
    bump(asg)

    volunteer = STORE.volunteers.get(asg["volunteer_id"])
    if volunteer is not None:
        volunteer["total_hours"] += actual_hours
        bump(volunteer)
    return success_object(serialize(asg))


@bp.route("/shift-assignments/<aid>/mark-no-show", methods=["POST"])
def mark_no_show(aid):
    _, role = authn()
    require_role(role, ("CenterManager",))
    asg = get_assignment(aid)
    if asg["status"] != "CONFIRMED":
        err("ERR_INVALID_STATE", 409, "Only a CONFIRMED assignment can be marked no-show")
    shift = STORE.shifts.get(asg["shift_id"])
    if not shift["end_at"] <= now():
        err("ERR_INVALID_STATE", 409, "Shift has not ended yet")

    affected = set()
    apply_no_show(asg, shift, now(), affected, set())
    settle_affected_centers(affected)

    center = STORE.centers.get(shift["center_id"])
    if center is not None:
        recompute_center(center)
    return success_object(serialize(asg))


@bp.route("/shift-assignments/<aid>/cancel", methods=["POST"])
def cancel_assignment(aid):
    uid, role = authn()
    require_role(role, ("Volunteer", "CenterManager"))
    asg = get_assignment(aid)
    if role == "Volunteer" and asg["volunteer_id"] != uid:
        err("ERR_FORBIDDEN", 403, "A volunteer may cancel only its own assignment")
    if asg["status"] not in ("ASSIGNED", "CONFIRMED"):
        err("ERR_INVALID_STATE", 409, "Only an ASSIGNED or CONFIRMED assignment can be cancelled")

    was_confirmed = asg["status"] == "CONFIRMED"
    asg["status"] = "CANCELLED"
    bump(asg)

    if was_confirmed:
        shift = STORE.shifts.get(asg["shift_id"])
        shift["confirmed_count"] -= 1
        refresh_shift_status(shift)
        bump(shift)
        center = STORE.centers.get(shift["center_id"])
        if center is not None:
            recompute_center(center)
    return success_object(serialize(asg))

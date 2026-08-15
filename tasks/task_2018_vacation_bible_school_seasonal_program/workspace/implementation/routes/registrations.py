"""Registrations: creation fork, cancel, offer accept/decline (PRD §3.2, §3.3)."""

from flask import Blueprint, request

import clock
import store
from auth import authenticate, require_role
from cascade import (
    cancel_registration,
    on_registration_enrolled,
    seat_freed,
)
from derived import (
    registration_view,
    open_seats,
    enrolled_count,
    regs_of_child,
)
from envelope import ok_object
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_REGISTRATION_WINDOW_CLOSED,
    ERR_AGE_OUT_OF_RANGE,
    ERR_DUPLICATE_REGISTRATION,
    ERR_FAMILY_ARCHIVED,
    ERR_OFFER_EXPIRED,
    ERR_CLASSROOM_FULL,
)
from routes.common import paginate, empty_body, guard_program_writable
from util import age_in_years
from validate import Field, get_body, validate_body

bp = Blueprint("registrations", __name__)

_CREATE_SPEC = {
    "child_id": Field("str", required=True),
    "classroom_id": Field("str", required=True),
}

ACTIVE_REG_STATUSES = ("ENROLLED", "WAITLISTED", "OFFERED")


def get_registration_or_404(registration_id):
    reg = store.get("registrations", registration_id)
    if reg is None:
        raise_err(ERR_NOT_FOUND, "registration not found")
    return reg


def _owning_family_id(reg):
    child = store.get("children", reg["child_id"])
    return child["family_id"] if child else None


def _check_parent_owns(ctx, reg):
    if ctx.role == "Parent" and _owning_family_id(reg) != ctx.user_id:
        raise_err(ERR_FORBIDDEN, "parents may only act on their own children's registrations")


def _guard_reg_program_writable(reg):
    """An ARCHIVED program is read-only for all writes under it."""
    classroom = store.get("classrooms", reg["classroom_id"])
    if classroom is not None:
        guard_program_writable(store.get("programs", classroom["program_id"]))


@bp.post("/vbs/registrations")
def create_registration():
    body = get_body()
    data = validate_body(body, _CREATE_SPEC)
    ctx = authenticate()
    require_role(ctx, "Parent", "RegistrationCoordinator")
    classroom = store.get("classrooms", data["classroom_id"])
    child = store.get("children", data["child_id"])
    # P2 ownership (evaluable only once the child is known to exist).
    if ctx.role == "Parent" and child is not None and child["family_id"] != ctx.user_id:
        raise_err(ERR_FORBIDDEN, "parents may only register their own children")
    # P3 existence, left-to-right per the reference hierarchy: classroom, then child.
    if classroom is None:
        raise_err(ERR_NOT_FOUND, "classroom not found")
    if child is None:
        raise_err(ERR_NOT_FOUND, "child not found")
    program = store.get("programs", classroom["program_id"])
    # P6: the classroom ACCEPTING-or-FULL gate (an ARCHIVED program is read-only).
    if classroom["status"] not in ("ACCEPTING", "FULL"):
        raise_err(ERR_INVALID_STATE, "classroom is not accepting registrations")
    guard_program_writable(program)
    # P7(i): program REGISTRATION_OPEN and the clock inside the inclusive window.
    now = clock.now()
    if (
        program is None
        or program["status"] != "REGISTRATION_OPEN"
        or not (program["registration_opens_at"] <= now <= program["registration_closes_at"])
    ):
        raise_err(ERR_REGISTRATION_WINDOW_CLOSED, "registration window is closed")
    # P8: inclusive age band, then one active registration per child per program.
    age = age_in_years(child["birth_date"], program["start_date"])
    if age < classroom["age_min"] or age > classroom["age_max"]:
        raise_err(ERR_AGE_OUT_OF_RANGE, "child age %d is outside [%d, %d]"
                  % (age, classroom["age_min"], classroom["age_max"]))
    for other in regs_of_child(child["id"]):
        if other["status"] not in ACTIVE_REG_STATUSES:
            continue
        other_classroom = store.get("classrooms", other["classroom_id"])
        if other_classroom is not None and other_classroom["program_id"] == program["id"]:
            raise_err(ERR_DUPLICATE_REGISTRATION, "child already has an active registration in this program")
    # P9: the family must be ACTIVE.
    family = store.get("families", child["family_id"])
    if family is not None and family["status"] != "ACTIVE":
        raise_err(ERR_FAMILY_ARCHIVED, "family is archived")
    reg = store.new_record(
        child_id=child["id"],
        classroom_id=classroom["id"],
        status="WAITLISTED",
        age_at_registration=age,
        offer_expires_at=None,
        enrolled_at=None,
        cancellation_reason=None,
    )
    if open_seats(classroom) >= 1:
        reg["status"] = "ENROLLED"
        store.put("registrations", reg)
        # enrolled_at stamping is part of the creation act (no version bump yet).
        on_registration_enrolled(reg, classroom, program)
    else:
        store.put("registrations", reg)
    return ok_object(registration_view(reg), status=201)


@bp.get("/vbs/registrations/<registration_id>")
def get_registration(registration_id):
    ctx = authenticate()
    require_role(ctx, "ProgramDirector", "RegistrationCoordinator", "Parent")
    reg = store.get("registrations", registration_id)
    if reg is not None:
        _check_parent_owns(ctx, reg)
    if reg is None:
        raise_err(ERR_NOT_FOUND, "registration not found")
    return ok_object(registration_view(reg))


@bp.get("/vbs/registrations")
def list_registrations():
    ctx = authenticate()
    require_role(ctx, "ProgramDirector", "RegistrationCoordinator", "Parent")
    items = list(store.all_of("registrations"))
    if ctx.role == "Parent":
        own_children = {
            c["id"] for c in store.all_of("children") if c["family_id"] == ctx.user_id
        }
        items = [r for r in items if r["child_id"] in own_children]
    child_id = request.args.get("child_id")
    classroom_id = request.args.get("classroom_id")
    status = request.args.get("status")
    if child_id is not None:
        items = [r for r in items if r["child_id"] == child_id]
    if classroom_id is not None:
        items = [r for r in items if r["classroom_id"] == classroom_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return paginate(items, registration_view)


@bp.post("/vbs/registrations/<registration_id>/cancel")
def cancel(registration_id):
    empty_body()
    ctx = authenticate()
    require_role(ctx, "Parent", "RegistrationCoordinator")
    reg = get_registration_or_404(registration_id)
    _check_parent_owns(ctx, reg)
    _guard_reg_program_writable(reg)
    if reg["status"] not in ("ENROLLED", "WAITLISTED"):
        raise_err(ERR_INVALID_STATE, "only ENROLLED or WAITLISTED registrations may be cancelled")
    reason = "FAMILY_REQUEST" if ctx.role == "Parent" else "ADMIN"
    cancel_registration(reg, reason)
    return ok_object(registration_view(reg))


@bp.post("/vbs/registrations/<registration_id>/accept")
def accept(registration_id):
    empty_body()
    ctx = authenticate()
    require_role(ctx, "Parent")
    reg = get_registration_or_404(registration_id)
    _check_parent_owns(ctx, reg)
    _guard_reg_program_writable(reg)
    if reg["status"] != "OFFERED":
        raise_err(ERR_INVALID_STATE, "registration is not OFFERED")
    now = clock.now()
    if reg["offer_expires_at"] is not None and now >= reg["offer_expires_at"]:
        # Late acceptance: the offer lapses inline and the waterfall re-runs.
        reg["status"] = "EXPIRED"
        reg["offer_expires_at"] = None
        store.touch(reg)
        classroom = store.get("classrooms", reg["classroom_id"])
        if classroom is not None:
            seat_freed(classroom)
        raise_err(ERR_OFFER_EXPIRED, "the waitlist offer has expired")
    classroom = store.get("classrooms", reg["classroom_id"])
    if enrolled_count(classroom) >= classroom["capacity"]:
        raise_err(ERR_CLASSROOM_FULL, "the classroom has no remaining capacity")
    program = store.get("programs", classroom["program_id"])
    reg["status"] = "ENROLLED"
    reg["offer_expires_at"] = None
    on_registration_enrolled(reg, classroom, program)
    store.touch(reg)
    return ok_object(registration_view(reg))


@bp.post("/vbs/registrations/<registration_id>/decline")
def decline(registration_id):
    empty_body()
    ctx = authenticate()
    require_role(ctx, "Parent")
    reg = get_registration_or_404(registration_id)
    _check_parent_owns(ctx, reg)
    _guard_reg_program_writable(reg)
    if reg["status"] != "OFFERED":
        raise_err(ERR_INVALID_STATE, "registration is not OFFERED")
    reg["status"] = "DECLINED"
    reg["offer_expires_at"] = None
    store.touch(reg)
    classroom = store.get("classrooms", reg["classroom_id"])
    if classroom is not None:
        seat_freed(classroom)
    return ok_object(registration_view(reg))

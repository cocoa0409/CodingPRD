"""Screening checks: submit, decide, resubmit (PRD §3.4)."""

from flask import Blueprint, request

import clock
import store
from auth import authenticate, require_role
from cascade import recompute_volunteer_status
from derived import screening_check_view
from envelope import ok_object
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_FORBIDDEN,
    ERR_SELF_REVIEW_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_DUPLICATE_CHECK,
)
from routes.common import paginate
from validate import Field, get_body, validate_body

bp = Blueprint("screening", __name__)

CHECK_TYPES = {"BACKGROUND", "REFERENCE", "SAFE_MINISTRY_TRAINING"}
ACTIVE_CHECK_STATUSES = ("SUBMITTED", "INFO_REQUESTED", "CLEARED")

_CREATE_SPEC = {
    "volunteer_id": Field("str", required=True),
    "check_type": Field("enum", enum=CHECK_TYPES, required=True),
}

_DECIDE_SPEC = {
    "decision": Field("enum", enum={"CLEARED", "REJECTED", "INFO_REQUESTED"}, required=True),
    "decision_notes": Field("str", default=None, nullable=True),
}

_RESUBMIT_SPEC = {
    "response_notes": Field("str", default=None, nullable=True),
}


def get_check_or_404(check_id):
    check = store.get("screening_checks", check_id)
    if check is None:
        raise_err(ERR_NOT_FOUND, "screening check not found")
    return check


def _guard_check_program_writable(check):
    from routes.common import guard_program_writable

    volunteer = store.get("volunteers", check["volunteer_id"])
    if volunteer is not None:
        guard_program_writable(store.get("programs", volunteer["program_id"]))


@bp.post("/vbs/screening-checks")
def create_check():
    body = get_body()
    data = validate_body(body, _CREATE_SPEC)
    ctx = authenticate()
    require_role(ctx, "Volunteer", "VolunteerCoordinator")
    # P2 ownership: a Volunteer files only their own checks.
    if ctx.role == "Volunteer" and data["volunteer_id"] != ctx.user_id:
        raise_err(ERR_FORBIDDEN, "volunteers may only submit their own screening checks")
    volunteer = store.get("volunteers", data["volunteer_id"])
    if volunteer is None:
        raise_err(ERR_NOT_FOUND, "volunteer not found")
    from routes.common import guard_program_writable

    guard_program_writable(store.get("programs", volunteer["program_id"]))
    for other in store.all_of("screening_checks"):
        if (
            other["volunteer_id"] == volunteer["id"]
            and other["check_type"] == data["check_type"]
            and other["status"] in ACTIVE_CHECK_STATUSES
        ):
            raise_err(ERR_DUPLICATE_CHECK, "an active check of this type already exists")
    check = store.new_record(
        volunteer_id=volunteer["id"],
        check_type=data["check_type"],
        status="SUBMITTED",
        decision_notes=None,
        response_notes=None,
        resubmission_count=0,
        reviewer_id=None,
        decided_at=None,
    )
    store.put("screening_checks", check)
    if volunteer["status"] == "APPLIED":
        volunteer["status"] = "SCREENING"
        store.touch(volunteer)
    return ok_object(screening_check_view(check), status=201)


@bp.post("/vbs/screening-checks/<check_id>/decide")
def decide_check(check_id):
    body = get_body()
    data = validate_body(body, _DECIDE_SPEC)
    ctx = authenticate()
    require_role(ctx, "SafetyOfficer")
    check = get_check_or_404(check_id)
    # P5 safety: segregation of duties fires ahead of the state gate.
    if ctx.user_id == check["volunteer_id"]:
        raise_err(ERR_SELF_REVIEW_FORBIDDEN, "an officer may not decide their own screening check")
    if check["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "only a SUBMITTED check may be decided")
    _guard_check_program_writable(check)
    check["status"] = data["decision"]
    check["reviewer_id"] = ctx.user_id
    check["decision_notes"] = data["decision_notes"]
    check["decided_at"] = clock.now()
    store.touch(check)
    volunteer = store.get("volunteers", check["volunteer_id"])
    if volunteer is not None and data["decision"] in ("CLEARED", "REJECTED"):
        recompute_volunteer_status(volunteer)
    return ok_object(screening_check_view(check))


@bp.post("/vbs/screening-checks/<check_id>/resubmit")
def resubmit_check(check_id):
    body = get_body()
    data = validate_body(body, _RESUBMIT_SPEC)
    ctx = authenticate()
    require_role(ctx, "Volunteer")
    check = get_check_or_404(check_id)
    if check["volunteer_id"] != ctx.user_id:
        raise_err(ERR_FORBIDDEN, "only the owning volunteer may resubmit")
    if check["status"] != "INFO_REQUESTED":
        raise_err(ERR_INVALID_STATE, "only an INFO_REQUESTED check may be resubmitted")
    _guard_check_program_writable(check)
    check["status"] = "SUBMITTED"
    check["response_notes"] = data["response_notes"]
    check["resubmission_count"] += 1
    store.touch(check)
    return ok_object(screening_check_view(check))


@bp.get("/vbs/screening-checks/<check_id>")
def get_check(check_id):
    ctx = authenticate()
    require_role(ctx, "VolunteerCoordinator", "SafetyOfficer", "Volunteer")
    check = store.get("screening_checks", check_id)
    if check is not None and ctx.role == "Volunteer" and check["volunteer_id"] != ctx.user_id:
        raise_err(ERR_FORBIDDEN, "volunteers may only read their own checks")
    if check is None:
        raise_err(ERR_NOT_FOUND, "screening check not found")
    return ok_object(screening_check_view(check))


@bp.get("/vbs/screening-checks")
def list_checks():
    ctx = authenticate()
    require_role(ctx, "VolunteerCoordinator", "SafetyOfficer")
    items = list(store.all_of("screening_checks"))
    volunteer_id = request.args.get("volunteer_id")
    status = request.args.get("status")
    if volunteer_id is not None:
        items = [c for c in items if c["volunteer_id"] == volunteer_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return paginate(items, screening_check_view)

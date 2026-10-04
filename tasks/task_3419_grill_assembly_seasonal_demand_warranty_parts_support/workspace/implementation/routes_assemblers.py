"""Assembler registration, read, and lifecycle (PRD §3.6)."""

from flask import Blueprint

import derive
from auth import authenticate, check_action_role, check_ownership, require_role
from constants import (
    CERTIFICATION_LEVELS,
    DECERTIFY_MAX_OFFICIAL_BP,
    DEFAULT_MAX_CONCURRENT_JOBS,
    REINSTATE_MIN_PROVISIONAL_BP,
)
from errors import api_error, not_found, validation
from serialize import assembler_out
from store import db, new_entity, touch
from util import as_list, get_body, ok, opt_int, req_str, require

bp = Blueprint("assemblers", __name__, url_prefix="/grillops")

ACTION_ROLES = {
    "CERTIFY": ("PlannerAdmin",),
    "SUSPEND": ("PlannerAdmin", "ServiceAgent"),
    "DECERTIFY": ("PlannerAdmin",),
}
VALID_FROM = {
    "CERTIFY": ("APPLIED", "SUSPENDED"),
    "SUSPEND": ("CERTIFIED",),
    "DECERTIFY": ("CERTIFIED", "SUSPENDED"),
}


@bp.post("/assemblers")
def create_assembler():
    _, role = authenticate()
    require_role(role, ("PlannerAdmin",))
    data = get_body()
    name = req_str(data, "name")
    certification_level = data.get("certification_level")
    if certification_level is None:
        certification_level = "BASIC"
    elif certification_level not in CERTIFICATION_LEVELS:
        raise validation("certification_level must be BASIC, CERTIFIED_PRO or MASTER")
    service_regions = as_list(require(data, "service_regions"), "service_regions")
    max_concurrent_jobs = opt_int(data, "max_concurrent_jobs", DEFAULT_MAX_CONCURRENT_JOBS)
    if max_concurrent_jobs is not None and max_concurrent_jobs < 0:
        raise validation("max_concurrent_jobs must be >= 0")
    assembler = new_entity({
        "name": name,
        "certification_level": certification_level,
        "service_regions": service_regions,
        "max_concurrent_jobs": max_concurrent_jobs,
        "status": "APPLIED",
        "active_job_count": 0,
        "jobs_completed": 0,
        "no_show_count": 0,
        "no_show_history": [],
        "completion_history": [],
        "official_quality_bp": 10000,
        "provisional_quality_bp": 10000,
    })
    db.assemblers[assembler["id"]] = assembler
    return ok(assembler_out(assembler), status=201)


@bp.get("/assemblers/<assembler_id>")
def get_assembler(assembler_id):
    user_id, role = authenticate()
    require_role(role, ("PlannerAdmin", "ServiceAgent", "Assembler"))
    assembler = db.assemblers.get(assembler_id)
    if assembler is None:
        raise not_found("ASSEMBLER")
    if role == "Assembler":
        check_ownership(user_id, assembler["id"])
    return ok(assembler_out(assembler))


def _cascade_suspend(assembler):
    """Every SCHEDULED job of this assembler returns to REQUESTED with the
    assignment cleared; IN_PROGRESS jobs are deliberately not touched."""
    for job in db.jobs.values():
        if job["assembler_id"] == assembler["id"] and job["status"] == "SCHEDULED":
            job["status"] = "REQUESTED"
            job["assembler_id"] = None
            job["window_start"] = None
            job["window_end"] = None
            touch(job)


@bp.post("/assemblers/<assembler_id>/status")
def assembler_status(assembler_id):
    _, role = authenticate()
    require_role(role, ("PlannerAdmin", "ServiceAgent"))
    assembler = db.assemblers.get(assembler_id)
    if assembler is None:
        raise not_found("ASSEMBLER")
    data = get_body()
    action = data.get("action")
    check_action_role(role, action, ACTION_ROLES)
    if action is None:
        raise validation("action is required")
    if action not in ACTION_ROLES:
        raise validation("action must be one of CERTIFY, SUSPEND, DECERTIFY")
    if assembler["status"] not in VALID_FROM[action]:
        raise api_error(
            "ERR_INVALID_STATE",
            "action %s is not available from status %s" % (action, assembler["status"]),
        )
    if action == "CERTIFY":
        if assembler["status"] == "SUSPENDED":
            # reinstatement guard reads the rolling 90-day quality score
            derive.recompute_assembler(assembler)
            if assembler["provisional_quality_bp"] < REINSTATE_MIN_PROVISIONAL_BP:
                raise api_error("ERR_INVALID_STATE", "provisional quality is below the reinstatement threshold")
        assembler["status"] = "CERTIFIED"
    elif action == "SUSPEND":
        assembler["status"] = "SUSPENDED"
        _cascade_suspend(assembler)
    elif action == "DECERTIFY":
        # decertify guard reads the lifetime quality score
        derive.recompute_assembler(assembler)
        if assembler["official_quality_bp"] > DECERTIFY_MAX_OFFICIAL_BP:
            raise api_error("ERR_INVALID_STATE", "official quality is above the decertification threshold")
        if assembler["status"] == "CERTIFIED":
            # harsher cascade: scheduled work unassigned, in-progress cancelled
            _cascade_suspend(assembler)
            for job in db.jobs.values():
                if job["assembler_id"] == assembler["id"] and job["status"] == "IN_PROGRESS":
                    job["status"] = "CANCELLED"
                    touch(job)
        assembler["status"] = "DECERTIFIED"
    derive.recompute_assembler(assembler)  # active_job_count after cascades
    touch(assembler)
    return ok(assembler_out(assembler))

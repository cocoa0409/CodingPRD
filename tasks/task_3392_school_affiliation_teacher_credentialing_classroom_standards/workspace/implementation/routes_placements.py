"""Practicum placements (PRD 3.4): creation, hour logging, verification,
cancellation. Supervisor capacity and half-open window overlap live here."""

from flask import Blueprint, request

from envelope import ok, pagination_params, list_response
from errors import (
    ApiError,
    ERR_VALIDATION,
    ERR_FORBIDDEN,
    ERR_LEARNER_NOT_FOUND,
    ERR_CREDENTIAL_NOT_FOUND,
    ERR_SCHOOL_NOT_FOUND,
    ERR_PLACEMENT_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_PLACEMENT_WINDOW_INVALID,
    ERR_PLACEMENT_WINDOW_OVERLAP,
    ERR_HOST_SCHOOL_INELIGIBLE,
    ERR_AGE_LEVEL_MISMATCH,
    ERR_SUPERVISOR_CREDENTIAL_INACTIVE,
    ERR_SUPERVISOR_CAPACITY_EXCEEDED,
    ERR_NO_ACTIVE_CATALOG,
)
from serializers import serialize_placement
from store import (
    db,
    new_id,
    stamp_new,
    touch,
    now_date,
    active_catalog,
    parse_date,
)
from validation import authenticate, require_role, payload, req_int

bp = Blueprint("placements", __name__)

PLACEMENT_READ_ROLES = {
    "SocietyAdmin",
    "ProgramDirector",
    "AdultLearner",
    "Registrar",
    "AccreditationReviewer",
}
PLACEMENT_LIST_ROLES = {"SocietyAdmin", "ProgramDirector", "Registrar", "AccreditationReviewer"}
HOST_ELIGIBLE_LEVELS = {"AFFILIATE", "MEMBER", "ACCREDITED"}
SUPERVISOR_MAX_ACTIVE = 3


def get_placement_or_404(placement_id):
    p = db.placements.get(placement_id)
    if p is None:
        raise ApiError(ERR_PLACEMENT_NOT_FOUND[0], ERR_PLACEMENT_NOT_FOUND[1],
                       "No practicum placement with id %r." % placement_id)
    return p


@bp.route("/practicum-placements", methods=["POST"])
def create_placement():
    uid, role = authenticate()
    require_role(role, {"ProgramDirector"})
    body = payload()
    # Tier 3: learner_id, supervisor_credential_id, host_school_id (global FK order).
    learner_id = body.get("learner_id")
    learner = None
    if isinstance(learner_id, str):
        learner = db.learners.get(learner_id)
        if learner is None:
            raise ApiError(ERR_LEARNER_NOT_FOUND[0], ERR_LEARNER_NOT_FOUND[1],
                           "No adult learner with id %r." % learner_id)
    sup_raw = body.get("supervisor_credential_id")
    supervisor = None
    if sup_raw is not None and isinstance(sup_raw, str):
        supervisor = db.credentials.get(sup_raw)
        if supervisor is None:
            raise ApiError(ERR_CREDENTIAL_NOT_FOUND[0], ERR_CREDENTIAL_NOT_FOUND[1],
                           "No credential with id %r." % sup_raw)
    host_id = body.get("host_school_id")
    host = None
    if isinstance(host_id, str):
        host = db.schools.get(host_id)
        if host is None:
            raise ApiError(ERR_SCHOOL_NOT_FOUND[0], ERR_SCHOOL_NOT_FOUND[1],
                           "No school with id %r." % host_id)
    # Tier 4: shape.
    if not isinstance(learner_id, str):
        raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                       "Field 'learner_id' is required and must be a string.")
    if sup_raw is not None and not isinstance(sup_raw, str):
        raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                       "Field 'supervisor_credential_id' must be a string when present.")
    if not isinstance(host_id, str):
        raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                       "Field 'host_school_id' is required and must be a string.")
    start_s = body.get("start_date")
    end_s = body.get("end_date")
    start = parse_date(start_s)
    end = parse_date(end_s)
    if start is None or end is None:
        raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                       "start_date and end_date are required ISO dates (YYYY-MM-DD).")
    # Tier 5: the director's X-User-ID must equal the learner's program_id.
    if uid != learner["program_id"]:
        raise ApiError(ERR_FORBIDDEN[0], ERR_FORBIDDEN[1],
                       "ProgramDirector may only place learners of their own program.")
    # Tier 7: window validity, then the half-open overlap rule.
    today = now_date()
    if not (end > start and end > today):
        raise ApiError(ERR_PLACEMENT_WINDOW_INVALID[0], ERR_PLACEMENT_WINDOW_INVALID[1],
                       "end_date must be strictly after start_date and after today.")
    for p in db.placements.values():
        if p["learner_id"] != learner["id"]:
            continue
        if p["status"] not in ("ACTIVE", "HOURS_COMPLETE"):
            continue
        p_start = parse_date(p["start_date"])
        p_end = parse_date(p["end_date"])
        # Half-open [start, end) intersection; end == start adjacency allowed.
        if p_start < end and start < p_end:
            raise ApiError(ERR_PLACEMENT_WINDOW_OVERLAP[0], ERR_PLACEMENT_WINDOW_OVERLAP[1],
                           "The learner already holds an overlapping placement.")
    # Tier 8: host school eligibility and supervisor age-level agreement.
    if host["membership_level"] not in HOST_ELIGIBLE_LEVELS:
        raise ApiError(ERR_HOST_SCHOOL_INELIGIBLE[0], ERR_HOST_SCHOOL_INELIGIBLE[1],
                       "Host school must be AFFILIATE, MEMBER or ACCREDITED.")
    if supervisor is not None and supervisor["age_level"] != learner["age_level"]:
        raise ApiError(ERR_AGE_LEVEL_MISMATCH[0], ERR_AGE_LEVEL_MISMATCH[1],
                       "Supervisor credential age level does not match the learner's.")
    # Tier 9: supervisor posture (ACTIVE, capacity), then ACTIVE catalog.
    if supervisor is not None:
        if supervisor["status"] != "ACTIVE":
            raise ApiError(ERR_SUPERVISOR_CREDENTIAL_INACTIVE[0],
                           ERR_SUPERVISOR_CREDENTIAL_INACTIVE[1],
                           "Supervisor credential is not ACTIVE.")
        supervised = sum(
            1 for p in db.placements.values()
            if p.get("supervisor_credential_id") == supervisor["id"]
            and p["status"] == "ACTIVE"
        )
        if supervised >= SUPERVISOR_MAX_ACTIVE:
            raise ApiError(ERR_SUPERVISOR_CAPACITY_EXCEEDED[0],
                           ERR_SUPERVISOR_CAPACITY_EXCEEDED[1],
                           "Supervisor already oversees 3 ACTIVE placements.")
    cat = active_catalog()
    if cat is None:
        raise ApiError(ERR_NO_ACTIVE_CATALOG[0], ERR_NO_ACTIVE_CATALOG[1],
                       "No ACTIVE standards catalog exists.")
    placement = {
        "id": new_id(),
        "learner_id": learner["id"],
        "host_school_id": host["id"],
        "supervisor_credential_id": supervisor["id"] if supervisor else None,
        "age_level": learner["age_level"],
        "start_date": start_s,
        "end_date": end_s,
        "target_hours": cat["practicum_min_hours_by_level"].get(learner["age_level"], 0),
        "hours_logged": 0,
        "status": "ACTIVE",
    }
    stamp_new(placement)
    db.placements[placement["id"]] = placement
    # Creating a placement advances an ENROLLED learner to IN_PRACTICUM.
    if learner["status"] == "ENROLLED":
        learner["status"] = "IN_PRACTICUM"
        touch(learner)
    return ok(serialize_placement(placement), 201)


@bp.route("/practicum-placements/<placement_id>", methods=["GET"])
def get_placement(placement_id):
    _, role = authenticate()
    require_role(role, PLACEMENT_READ_ROLES)
    return ok(serialize_placement(get_placement_or_404(placement_id)), 200)


@bp.route("/practicum-placements", methods=["GET"])
def list_placements():
    _, role = authenticate()
    require_role(role, PLACEMENT_LIST_ROLES)
    args = request.args
    items = list(db.placements.values())
    for f in ("learner_id", "host_school_id", "supervisor_credential_id", "status"):
        v = args.get(f)
        if v is not None:
            items = [p for p in items if p.get(f) == v]
    items.sort(key=lambda p: (p["created_at"], p["_seq"]))
    limit, offset = pagination_params()
    return list_response(items, limit, offset, serialize_placement)


@bp.route("/practicum-placements/<placement_id>/log-hours", methods=["POST"])
def log_hours(placement_id):
    uid, role = authenticate()
    require_role(role, {"AdultLearner"})
    placement = get_placement_or_404(placement_id)
    body = payload()
    # Tier 4: hours > 0 (whole number), work_date well-formed.
    hours = req_int(body, "hours", minimum=1)
    work_s = body.get("work_date")
    work_date = parse_date(work_s)
    if work_date is None:
        raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                       "Field 'work_date' is required and must be an ISO date.")
    # Tier 5: only the placement's own learner logs hours.
    if uid != placement["learner_id"]:
        raise ApiError(ERR_FORBIDDEN[0], ERR_FORBIDDEN[1],
                       "AdultLearner may only log hours on their own placement.")
    # Tier 6: logging is accepted only while ACTIVE.
    if placement["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                       "Placement is %s; no further hours may be logged." % placement["status"])
    # Tier 7: work_date must fall inside [start_date, end_date].
    start = parse_date(placement["start_date"])
    end = parse_date(placement["end_date"])
    if not (start <= work_date <= end):
        raise ApiError(ERR_PLACEMENT_WINDOW_INVALID[0], ERR_PLACEMENT_WINDOW_INVALID[1],
                       "work_date is outside the placement window.")
    placement["hours_logged"] += hours
    if placement["hours_logged"] >= placement["target_hours"]:
        placement["status"] = "HOURS_COMPLETE"
    touch(placement)
    return ok(serialize_placement(placement), 200)


@bp.route("/practicum-placements/<placement_id>/verify", methods=["POST"])
def verify_placement(placement_id):
    uid, role = authenticate()
    require_role(role, {"ProgramDirector"})
    placement = get_placement_or_404(placement_id)
    learner = db.learners[placement["learner_id"]]
    # Tier 5: only the director of the learner's program verifies.
    if uid != learner["program_id"]:
        raise ApiError(ERR_FORBIDDEN[0], ERR_FORBIDDEN[1],
                       "ProgramDirector may only verify placements of their own program.")
    # Tier 6: verification only from HOURS_COMPLETE.
    if placement["status"] != "HOURS_COMPLETE":
        raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                       "Only a HOURS_COMPLETE placement can be verified.")
    placement["status"] = "VERIFIED"
    touch(placement)
    if learner["status"] == "IN_PRACTICUM":
        learner["status"] = "PRACTICUM_COMPLETE"
        touch(learner)
    return ok(serialize_placement(placement), 200)


@bp.route("/practicum-placements/<placement_id>/cancel", methods=["POST"])
def cancel_placement(placement_id):
    uid, role = authenticate()
    require_role(role, {"ProgramDirector"})
    placement = get_placement_or_404(placement_id)
    learner = db.learners[placement["learner_id"]]
    # Tier 5: only the director of the learner's program cancels.
    if uid != learner["program_id"]:
        raise ApiError(ERR_FORBIDDEN[0], ERR_FORBIDDEN[1],
                       "ProgramDirector may only cancel placements of their own program.")
    # Tier 6: only an ACTIVE placement can be cancelled.
    if placement["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                       "Only an ACTIVE placement can be cancelled.")
    placement["status"] = "CANCELLED"
    touch(placement)
    return ok(serialize_placement(placement), 200)

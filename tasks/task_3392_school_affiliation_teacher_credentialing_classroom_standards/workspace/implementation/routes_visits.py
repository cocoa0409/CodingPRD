"""Verification visits (PRD 3.6): scheduling with consultant travel buffers,
cancellation, and report filing with the improvement-plan / standing cascades."""

from datetime import timedelta

from flask import Blueprint, request

from cascade import auto_create_plan, apply_standing_transition
from envelope import ok, pagination_params, list_response
from errors import (
    ApiError,
    ERR_FORBIDDEN,
    ERR_VALIDATION,
    ERR_SCHOOL_NOT_FOUND,
    ERR_SELF_STUDY_NOT_FOUND,
    ERR_VISIT_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_VISIT_WINDOW_INVALID,
    ERR_CONSULTANT_SCHEDULE_CONFLICT,
    ERR_AGE_LEVEL_MISMATCH,
    ERR_NO_ACTIVE_CATALOG,
)
from serializers import serialize_visit
from store import (
    db,
    new_id,
    stamp_new,
    touch,
    now_date,
    now_iso,
    active_catalog,
    parse_date,
)
from validation import authenticate, require_role, payload, req_str, req_enum, req_list

bp = Blueprint("visits", __name__)

VISIT_ROLES = {"SocietyAdmin", "AccreditationReviewer", "SchoolAdmin", "Consultant"}
REPORT_VERDICTS = {"COMPLIANT", "IMPROVEMENT_REQUIRED", "NONCOMPLIANT"}


def get_visit_or_404(visit_id):
    v = db.visits.get(visit_id)
    if v is None:
        raise ApiError(ERR_VISIT_NOT_FOUND[0], ERR_VISIT_NOT_FOUND[1],
                       "No verification visit with id %r." % visit_id)
    return v


@bp.route("/verification-visits", methods=["POST"])
def create_visit():
    _, role = authenticate()
    require_role(role, {"AccreditationReviewer"})
    body = payload()
    # Tier 3: school_id then self_study_id body FKs.
    school_id = body.get("school_id")
    school = None
    if isinstance(school_id, str):
        school = db.schools.get(school_id)
        if school is None:
            raise ApiError(ERR_SCHOOL_NOT_FOUND[0], ERR_SCHOOL_NOT_FOUND[1],
                           "No school with id %r." % school_id)
    study_id = body.get("self_study_id")
    study = None
    if isinstance(study_id, str):
        study = db.self_studies.get(study_id)
        if study is None:
            raise ApiError(ERR_SELF_STUDY_NOT_FOUND[0], ERR_SELF_STUDY_NOT_FOUND[1],
                           "No self-study with id %r." % study_id)
    # Tier 4: shape.
    if not isinstance(school_id, str):
        raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                       "Field 'school_id' is required and must be a string.")
    if not isinstance(study_id, str):
        raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                       "Field 'self_study_id' is required and must be a string.")
    consultant_id = req_str(body, "consultant_id")
    ws_s = body.get("window_start")
    we_s = body.get("window_end")
    ws = parse_date(ws_s)
    we = parse_date(we_s)
    if ws is None or we is None:
        raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                       "window_start and window_end are required ISO dates.")
    # Tier 7: window well-formed and not in the past; then consultant buffers.
    today = now_date()
    if we < ws or ws < today:
        raise ApiError(ERR_VISIT_WINDOW_INVALID[0], ERR_VISIT_WINDOW_INVALID[1],
                       "window_end must be on or after window_start, and "
                       "window_start must not be before the current date.")
    cat = active_catalog()
    if cat is None:
        raise ApiError(ERR_NO_ACTIVE_CATALOG[0], ERR_NO_ACTIVE_CATALOG[1],
                       "No ACTIVE standards catalog exists.")
    buffer = timedelta(days=int(cat["consultant_travel_buffer_days"]))
    for v in db.visits.values():
        if v["consultant_id"] != consultant_id or v["status"] == "CANCELLED":
            continue
        evs = parse_date(v["window_start"])
        eve = parse_date(v["window_end"])
        # Expanded-window closed-interval intersection; touching conflicts.
        if ws <= eve + buffer and evs <= we + buffer:
            raise ApiError(ERR_CONSULTANT_SCHEDULE_CONFLICT[0],
                           ERR_CONSULTANT_SCHEDULE_CONFLICT[1],
                           "The consultant has a conflicting visit window.")
    # Tier 8: the referenced study must belong to the school and be ACCEPTED.
    if study["school_id"] != school["id"] or study["status"] != "ACCEPTED":
        raise ApiError(ERR_AGE_LEVEL_MISMATCH[0], ERR_AGE_LEVEL_MISMATCH[1],
                       "The self-study must belong to the school and be ACCEPTED.")
    visit = {
        "id": new_id(),
        "school_id": school["id"],
        "self_study_id": study["id"],
        "consultant_id": consultant_id,
        "window_start": ws_s,
        "window_end": we_s,
        "status": "SCHEDULED",
        "verdict": None,
        "findings": [],
        "report_filed_at": None,
    }
    stamp_new(visit)
    db.visits[visit["id"]] = visit
    return ok(serialize_visit(visit), 201)


@bp.route("/verification-visits/<visit_id>", methods=["GET"])
def get_visit(visit_id):
    _, role = authenticate()
    require_role(role, VISIT_ROLES)
    return ok(serialize_visit(get_visit_or_404(visit_id)), 200)


@bp.route("/verification-visits", methods=["GET"])
def list_visits():
    _, role = authenticate()
    require_role(role, VISIT_ROLES)
    args = request.args
    items = list(db.visits.values())
    for f in ("school_id", "self_study_id", "consultant_id", "status"):
        v = args.get(f)
        if v is not None:
            items = [x for x in items if x.get(f) == v]
    items.sort(key=lambda v: (v["created_at"], v["_seq"]))
    limit, offset = pagination_params()
    return list_response(items, limit, offset, serialize_visit)


@bp.route("/verification-visits/<visit_id>/cancel", methods=["POST"])
def cancel_visit(visit_id):
    _, role = authenticate()
    require_role(role, {"AccreditationReviewer"})
    visit = get_visit_or_404(visit_id)
    if visit["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                       "Only a SCHEDULED visit can be cancelled.")
    visit["status"] = "CANCELLED"
    touch(visit)
    return ok(serialize_visit(visit), 200)


@bp.route("/verification-visits/<visit_id>/reports", methods=["POST"])
def file_report(visit_id):
    uid, role = authenticate()
    require_role(role, {"Consultant"})
    visit = get_visit_or_404(visit_id)
    body = payload()
    # Tier 4: findings array of strings; verdict enum.
    findings = req_list(body, "findings")
    for f in findings:
        if not isinstance(f, str):
            raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                           "Each finding must be a string.")
    verdict = req_enum(body, "verdict", REPORT_VERDICTS)
    # Tier 5: only the visit's own consultant may file.
    if uid != visit["consultant_id"]:
        raise ApiError(ERR_FORBIDDEN[0], ERR_FORBIDDEN[1],
                       "Only the visit's assigned consultant may file the report.")
    # Tier 6: the visit must still be SCHEDULED.
    if visit["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                       "The visit is not SCHEDULED.")
    # Tier 7: the current logical date must have reached window_start.
    if now_date() < parse_date(visit["window_start"]):
        raise ApiError(ERR_VISIT_WINDOW_INVALID[0], ERR_VISIT_WINDOW_INVALID[1],
                       "The visit window has not started yet.")
    visit["verdict"] = verdict
    visit["findings"] = list(findings)
    visit["report_filed_at"] = now_iso()
    visit["status"] = "REPORT_FILED"
    touch(visit)
    # Verdict cascades (PRD 3.6).
    if verdict in ("IMPROVEMENT_REQUIRED", "NONCOMPLIANT"):
        auto_create_plan(visit["school_id"], visit["id"], findings)
    if verdict == "NONCOMPLIANT":
        school = db.schools.get(visit["school_id"])
        if school is not None and school["standing"] == "GOOD_STANDING":
            apply_standing_transition(school, "PROBATION")
    return ok(serialize_visit(visit), 201)

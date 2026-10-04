"""Interviews: scheduling (half-open overlap), completion scoring, cancellation."""
from flask import Blueprint, request

from authz import auth, require_roles
from calc import interview_result
from db import ROLES, STORE, fmt_ts, new_record, parse_dt, touch, ts_sec
from errors import err, ok_object, paginate
from routes_applications import get_application_or_404
from validate import as_dt, as_number, as_str, body

bp = Blueprint("interviews", __name__)


def get_interview_or_404(iid):
    interview = STORE["interviews"].get(iid)
    if interview is None:
        err("ERR_INTERVIEW_NOT_FOUND", 404, "Interview not found")
    return interview


@bp.post("/volunteer-portal/applications/<aid>/interviews")
def create_interview(aid):
    auth()
    require_roles(request.headers.get("X-User-Role"), ("PlacementOfficer",))
    app = get_application_or_404(aid)
    data = body()
    # State guard (priority 6): scheduling requires UNDER_REVIEW.
    if app["status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE", 409,
            "interview scheduling requires UNDER_REVIEW, found %s" % app["status"])
    # Overlap rule (priority 8): same interviewer, SCHEDULED, half-open windows;
    # adjacency allowed. Runs only when the window parses; shape errors surface
    # at priority 10 below.
    start = parse_dt(data.get("scheduled_start"))
    end = parse_dt(data.get("scheduled_end"))
    interviewer = data.get("interviewer_id")
    if start is not None and end is not None and isinstance(interviewer, str):
        for other in STORE["interviews"].values():
            if other["interviewer_id"] != interviewer or other["status"] != "SCHEDULED":
                continue
            o_start = parse_dt(other["scheduled_start"])
            o_end = parse_dt(other["scheduled_end"])
            if ts_sec(start) < ts_sec(o_end) and ts_sec(o_start) < ts_sec(end):
                err("ERR_INTERVIEW_OVERLAP", 409,
                    "Interviewer %s already has a SCHEDULED interview in that window"
                    % interviewer)
    # Field shape (priority 10)
    interviewer = as_str(data, "interviewer_id")
    start = as_dt(data, "scheduled_start")
    end = as_dt(data, "scheduled_end")
    if ts_sec(end) <= ts_sec(start):
        err("ERR_VALIDATION", 400, "scheduled_end must be strictly after scheduled_start")
    rec = new_record()
    rec.update({
        "application_id": aid,
        "interviewer_id": interviewer,
        "scheduled_start": fmt_ts(start),
        "scheduled_end": fmt_ts(end),
        "motivation_score": None,
        "adaptability_score": None,
        "skill_competency_score": None,
        "cross_cultural_score": None,
        "overall_score": None,
        "recommendation": None,
        "status": "SCHEDULED",
    })
    STORE["interviews"][rec["id"]] = rec
    app["status"] = "INTERVIEWING"
    touch(app)
    return ok_object(rec, 201)


@bp.get("/volunteer-portal/applications/<aid>/interviews")
def list_interviews(aid):
    auth()
    require_roles(request.headers.get("X-User-Role"), ROLES)
    get_application_or_404(aid)
    records = sorted(
        (iv for iv in STORE["interviews"].values() if iv["application_id"] == aid),
        key=lambda r: r["created_at"])
    return paginate(records)


@bp.post("/volunteer-portal/interviews/<iid>/complete")
def complete_interview(iid):
    auth()
    require_roles(request.headers.get("X-User-Role"), ("PlacementOfficer",))
    interview = get_interview_or_404(iid)
    if interview["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", 409,
            "complete requires SCHEDULED, found %s" % interview["status"])
    data = body()
    motivation = as_number(data, "motivation_score", minimum=1.0, maximum=5.0)
    adaptability = as_number(data, "adaptability_score", minimum=1.0, maximum=5.0)
    competency = as_number(data, "skill_competency_score", minimum=1.0, maximum=5.0)
    cross_cultural = as_number(data, "cross_cultural_score", minimum=1.0, maximum=5.0)
    overall, recommendation = interview_result(motivation, adaptability,
                                               competency, cross_cultural)
    interview["motivation_score"] = motivation
    interview["adaptability_score"] = adaptability
    interview["skill_competency_score"] = competency
    interview["cross_cultural_score"] = cross_cultural
    interview["overall_score"] = overall
    interview["recommendation"] = recommendation
    interview["status"] = "COMPLETED"
    touch(interview)
    app = STORE["applications"].get(interview["application_id"])
    if app is not None and app["status"] == "INTERVIEWING":
        app["status"] = "EVALUATED"
        touch(app)
    return ok_object(interview)


@bp.post("/volunteer-portal/interviews/<iid>/cancel")
def cancel_interview(iid):
    auth()
    require_roles(request.headers.get("X-User-Role"), ("PlacementOfficer",))
    interview = get_interview_or_404(iid)
    if interview["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", 409,
            "cancel requires SCHEDULED, found %s" % interview["status"])
    interview["status"] = "CANCELLED"
    touch(interview)
    app_id = interview["application_id"]
    remaining = any(
        iv["application_id"] == app_id and iv["status"] == "SCHEDULED"
        for iv in STORE["interviews"].values())
    app = STORE["applications"].get(app_id)
    if not remaining and app is not None and app["status"] == "INTERVIEWING":
        app["status"] = "UNDER_REVIEW"
        touch(app)
    return ok_object(interview)

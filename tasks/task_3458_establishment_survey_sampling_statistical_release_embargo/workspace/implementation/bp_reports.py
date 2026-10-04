"""/survey/response-reports: create, list, read, advance (PRD 3.3)."""
from flask import Blueprint, request

from authz import get_auth, require_role, require_action_role, require_ownership
from burden import burden_apply
from envelope import ok, ok_list, paginate
from errors import (
    raise_err, ERR_VALIDATION, ERR_ENROLLMENT_NOT_FOUND, ERR_CYCLE_NOT_FOUND,
    ERR_REPORT_NOT_FOUND, ERR_INVALID_STATE, ERR_CYCLE_NOT_COLLECTING,
    ERR_ENROLLMENT_NOT_ACTIVE, ERR_REPORT_WINDOW_CLOSED, ERR_DUPLICATE_REPORT,
)
from store import (
    DB, new_entity, sorted_entities, touch, now,
    BURDEN_MINUTES_PER_SUBMISSION, LIVE_CASE_STATUSES,
)
from validate import get_body, req_str, req_int

bp = Blueprint("reports", __name__)

ACTION_ROLES = {
    "SUBMIT": {"Respondent"},
    "ACCEPT": {"CollectionOfficer"},
    "RETURN": {"CollectionOfficer"},
}


@bp.post("/response-reports")
def create_report():
    user, role = get_auth()
    require_role(role, {"Respondent"})
    data = get_body()

    # Stage 4 body references; ownership (stage 2) needs the enrollment.
    enrollment = None
    if data.get("enrollment_id") is not None:
        enrollment = DB["enrollments"].get(data["enrollment_id"])
        if enrollment is None:
            raise_err(ERR_ENROLLMENT_NOT_FOUND, "enrollment_id does not resolve")
        require_ownership(user, enrollment["establishment_id"], "enrollment")
    cycle = None
    if data.get("cycle_id") is not None:
        cycle = DB["cycles"].get(data["cycle_id"])
        if cycle is None:
            raise_err(ERR_CYCLE_NOT_FOUND, "cycle_id does not resolve")

    # Stage 5 shape.
    req_str(data, "enrollment_id")
    req_str(data, "cycle_id")
    employment = req_int(data, "employment", minimum=0)

    # Stage 8 specific state gates (cycle first, then enrollment).
    if cycle["cycle_status"] != "COLLECTING":
        raise_err(ERR_CYCLE_NOT_COLLECTING, "cycle is not COLLECTING")
    if enrollment["enrollment_status"] != "ENROLLED":
        raise_err(ERR_ENROLLMENT_NOT_ACTIVE, "enrollment is not ENROLLED")

    # Stage 10 temporal: the collection window closes at collection_close_at
    # even while the cycle still reads COLLECTING on paper.
    if now() > cycle["collection_close_at"]:
        raise_err(ERR_REPORT_WINDOW_CLOSED, "collection window has closed")

    # Stage 11 uniqueness.
    if any(r for r in DB["reports"].values()
           if r["enrollment_id"] == enrollment["id"] and r["cycle_id"] == cycle["id"]):
        raise_err(ERR_DUPLICATE_REPORT,
                  "a report already exists for this enrollment and cycle")

    report = new_entity("reports", {
        "enrollment_id": enrollment["id"],
        "cycle_id": cycle["id"],
        "employment": employment,
        "report_status": "SUBMITTED",
        "submit_count": 1,
        "submitted_at": now(),
        "return_reason": None,
    })
    burden_apply(enrollment, BURDEN_MINUTES_PER_SUBMISSION)
    return ok(report, status=201)


@bp.get("/response-reports")
def list_reports():
    get_auth()
    items = sorted_entities("reports")
    for param in ("enrollment_id", "cycle_id", "report_status"):
        value = request.args.get(param)
        if value is not None:
            items = [r for r in items if r[param] == value]
    page, pagination = paginate(items)
    return ok_list(page, pagination)


def _load_report(rid):
    report = DB["reports"].get(rid)
    if report is None:
        raise_err(ERR_REPORT_NOT_FOUND, "response report not found")
    return report


@bp.get("/response-reports/<rid>")
def get_report(rid):
    get_auth()
    return ok(_load_report(rid))


@bp.post("/response-reports/<rid>/advance")
def advance_report(rid):
    user, role = get_auth()
    require_role(role, {"Respondent", "CollectionOfficer"})
    # Stage 2 per-action authorization precedes stage 3 path existence
    # (PRD 2.8). Peek at the body without raising so a malformed body still
    # reports at stage 5, after the path-existence check.
    peek = request.get_json(silent=True)
    if isinstance(peek, dict):
        require_action_role(role, peek.get("action"), ACTION_ROLES)
    report = _load_report(rid)
    enrollment = DB["enrollments"].get(report["enrollment_id"])
    if role == "Respondent" and enrollment is not None:
        require_ownership(user, enrollment["establishment_id"], "report")
    data = get_body()
    action = req_str(data, "action")
    if action not in ACTION_ROLES:
        raise_err(ERR_VALIDATION, f"unknown report action '{action}'")
    if action == "RETURN":
        req_str(data, "return_reason")

    cycle = DB["cycles"].get(report["cycle_id"])
    status = report["report_status"]

    if action == "ACCEPT":
        if status != "SUBMITTED":
            raise_err(ERR_INVALID_STATE, f"cannot accept a report in {status}")
        if cycle["cycle_status"] not in ("COLLECTING", "PROCESSING"):
            raise_err(ERR_CYCLE_NOT_COLLECTING,
                      "accept requires the cycle to be COLLECTING or PROCESSING")
        report["report_status"] = "ACCEPTED"
        touch(report)
        # Cascade: a live follow-up case for this enrollment+cycle closes.
        for case in DB["cases"].values():
            if (case["enrollment_id"] == report["enrollment_id"]
                    and case["cycle_id"] == report["cycle_id"]
                    and case["case_status"] in LIVE_CASE_STATUSES):
                case["case_status"] = "CLOSED_RESPONDED"
                touch(case)
    elif action == "RETURN":
        if status != "SUBMITTED":
            raise_err(ERR_INVALID_STATE, f"cannot return a report in {status}")
        if cycle["cycle_status"] != "COLLECTING":
            raise_err(ERR_CYCLE_NOT_COLLECTING,
                      "return requires the cycle to be COLLECTING")
        report["report_status"] = "RETURNED"
        report["return_reason"] = data["return_reason"]
        touch(report)
    elif action == "SUBMIT":
        if status != "RETURNED":
            raise_err(ERR_INVALID_STATE, f"cannot submit a report in {status}")
        if cycle["cycle_status"] != "COLLECTING":
            raise_err(ERR_CYCLE_NOT_COLLECTING,
                      "resubmission requires the cycle to be COLLECTING")
        if enrollment is not None and enrollment["enrollment_status"] != "ENROLLED":
            raise_err(ERR_ENROLLMENT_NOT_ACTIVE, "enrollment is not ENROLLED")
        if now() > cycle["collection_close_at"]:
            raise_err(ERR_REPORT_WINDOW_CLOSED, "collection window has closed")
        report["report_status"] = "SUBMITTED"
        report["submit_count"] += 1
        report["submitted_at"] = now()
        report["return_reason"] = None
        touch(report)
        if enrollment is not None:
            burden_apply(enrollment, BURDEN_MINUTES_PER_SUBMISSION)
    return ok(report)

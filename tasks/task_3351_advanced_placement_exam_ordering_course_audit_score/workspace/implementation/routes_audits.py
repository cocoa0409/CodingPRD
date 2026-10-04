"""Course audits: filing, listing and the review machine."""

from flask import request

import auth
import cascades
import clock
import core
from constants import APPROVAL_TERM_END_UTC, MAX_SYLLABUS_REVISIONS
from core import app, body, insert, rows, str_field
from entities import make, serialize
from errors import fail
from response import list_response, ok
from validation import require_fk, transition_gate


@app.route("/ap-program/course-audits", methods=["POST"])
def create_course_audit():
    auth.authenticate(["SchoolCoordinator"])
    payload = body()
    school_id = str_field(payload, "school_id")
    course_title = str_field(payload, "course_title")
    syllabus_hash = str_field(payload, "syllabus_hash")
    submitted_by = str_field(payload, "submitted_by_user_id")
    require_fk("schools", school_id, "school_id")
    audit = insert("course_audits", make(
        "course_audits",
        school_id=school_id,
        course_title=course_title,
        syllabus_hash=syllabus_hash,
        submitted_by_user_id=submitted_by,
        decision_notes=None,
    ))
    audit["_last_submitted_hash"] = syllabus_hash
    return ok(serialize("course_audits", audit), status=201)


@app.route("/ap-program/course-audits", methods=["GET"])
def list_course_audits():
    auth.authenticate(["PlatformAdmin", "SchoolCoordinator", "CourseAuditReviewer"])
    args = request.args
    school_id = args.get("school_id")
    status = args.get("status")
    matching = [
        a for a in rows("course_audits")
        if (school_id is None or a["school_id"] == school_id)
        and (status is None or a["status"] == status)
    ]
    matching.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return list_response(matching, args, lambda r: serialize("course_audits", r))


@app.route("/ap-program/course-audits/<rid>/status-transitions", methods=["POST"])
def transition_course_audit(rid):
    _role, actor = auth.authenticate(["CourseAuditReviewer", "SchoolCoordinator"])
    payload = body()
    audit, to_status = transition_gate(
        "course_audits", rid, payload,
        occ_field="expected_course_audit_version", actor=actor,
    )
    notes = payload.get("decision_notes")

    if to_status == "IN_REVIEW":
        if not (audit.get("syllabus_hash") or "").strip():
            fail("ERR_INVALID_STATE", "The audit carries no syllabus hash.")
        audit["review_round"] = audit["review_round"] + 1
        audit["status"] = "IN_REVIEW"
        core.touch(audit)

    elif to_status == "REVISION_REQUESTED":
        _require_decision(audit, notes)
        audit["status"] = "REVISION_REQUESTED"
        core.touch(audit)

    elif to_status == "SUBMITTED":
        if audit["syllabus_revision_count"] >= MAX_SYLLABUS_REVISIONS:
            fail("ERR_INVALID_STATE", "The audit has exhausted its syllabus revisions.")
        new_hash = payload.get("syllabus_hash")
        if new_hash is None or not str(new_hash).strip():
            fail("ERR_INVALID_REQUEST", "Field 'syllabus_hash' is required.")
        if new_hash == audit.get("_last_submitted_hash"):
            fail("ERR_SYLLABUS_UNCHANGED")
        audit["syllabus_hash"] = new_hash
        audit["_last_submitted_hash"] = new_hash
        audit["syllabus_revision_count"] = audit["syllabus_revision_count"] + 1
        audit["status"] = "SUBMITTED"
        core.touch(audit)

    elif to_status == "APPROVED":
        _require_decision(audit, notes)
        school = core.require("schools", audit["school_id"])
        if school["test_center_status"] != "ACTIVE":
            fail("ERR_INVALID_STATE", "The owning school's test center is not ACTIVE.")
        audit["approval_term_end_utc"] = APPROVAL_TERM_END_UTC
        audit["status"] = "APPROVED"
        core.touch(audit)
        cascades.recompute_school_audit_counters(audit["school_id"])
        cascades.approve_audit_cascade(audit, school)

    elif to_status == "REJECTED":
        _require_decision(audit, notes)
        if audit["syllabus_revision_count"] < 2:
            fail("ERR_INVALID_STATE", "Rejection requires at least two syllabus revisions.")
        audit["status"] = "REJECTED"
        core.touch(audit)
        cascades.recompute_school_audit_counters(audit["school_id"])

    return ok(serialize("course_audits", audit))


def _require_decision(audit, notes=None):
    effective = notes if notes is not None else audit.get("decision_notes")
    if audit["review_round"] < 1 or not (effective or "").strip():
        fail("ERR_AUDIT_NOT_REVIEWED")
    audit["decision_notes"] = effective


def expire_due_audits():
    """Time-driven APPROVED -> EXPIRED sweep, run whenever the clock moves."""
    now = clock.now()
    for audit in rows("course_audits"):
        if audit["status"] != "APPROVED":
            continue
        term = audit.get("approval_term_end_utc")
        if term and now > clock.parse_instant(term):
            cascades.expire_audit(audit)

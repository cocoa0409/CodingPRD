"""Job postings: creation, listing with EXPIRED projection, lifecycle,
and per-university clearance."""

from flask import Blueprint, request

import db
from db import wall_now
from errors import fail
from services import (
    block_posting_at_university,
    posting_reported_status,
    posting_view,
    posting_visible_to_university,
)
from util import Body, get_context, paginate, require_role, success_object

bp = Blueprint("postings", __name__)

POSITION_TYPES = ("FULL_TIME", "INTERNSHIP", "COOP")
WORK_AUTHORIZATIONS = ("US_CITIZEN", "PERMANENT_RESIDENT", "VISA_OPT_CPT", "SPONSORSHIP_REQUIRED")
DOC_TYPES = ("RESUME", "COVER_LETTER", "TRANSCRIPT", "PORTFOLIO")
POSTING_STATUSES = ("DRAFT", "SUBMITTED", "PUBLISHED", "PAUSED", "CLOSED", "EXPIRED")
CLEARANCE_DECISIONS = ("BLOCK", "CLEAR")


@bp.route("/job-postings", methods=["POST"])
def create_posting():
    user_id, role = get_context()
    require_role(role, "EmployerRecruiter")
    body = Body()
    employer_id = body.str_f("employer_id", required=True)
    title = body.str_f("title", required=True)
    position_type = body.str_f("position_type", required=True, enum=POSITION_TYPES)
    required_majors = body.list_f("required_majors")
    min_year = body.int_f("min_graduation_year", required=True)
    max_year = body.int_f("max_graduation_year", required=True)
    accepted_auths = body.list_f("accepted_work_authorizations", item_enum=WORK_AUTHORIZATIONS)
    required_documents = body.list_f("required_documents", item_enum=DOC_TYPES)
    deadline = body.dt_f("application_deadline", required=True)
    if min_year is not None and max_year is not None and min_year > max_year:
        body.bad = True
    # Priority 3 ownership, then 4 existence, then 5 state.
    if employer_id is not None and employer_id != user_id:
        fail("ERR_FORBIDDEN_OWNERSHIP", "Recruiter may post only for their own employer")
    employer = db.get("employers", employer_id) if employer_id else None
    if employer_id is not None and employer is None:
        fail("ERR_EMPLOYER_NOT_FOUND", "Employer id does not exist")
    if employer is not None and employer["status"] != "APPROVED":
        fail("ERR_EMPLOYER_NOT_APPROVED", "Employer must be APPROVED to create postings")
    body.finalize()
    record = {
        "id": db.new_id(),
        "employer_id": employer_id,
        "title": title,
        "position_type": position_type,
        "required_majors": required_majors or [],
        "min_graduation_year": min_year,
        "max_graduation_year": max_year,
        "accepted_work_authorizations": accepted_auths or [],
        "required_documents": required_documents or [],
        "application_deadline": deadline,
        "status": "DRAFT",
        "blocked_university_ids": [],
        "created_at": wall_now(),
        "updated_at": wall_now(),
        "version": 1,
    }
    db.insert("job_postings", record)
    return success_object(posting_view(record), 201)


@bp.route("/job-postings", methods=["GET"])
def list_postings():
    user_id, role = get_context()
    require_role(role, "Student", "EmployerRecruiter", "CareerCenterAdmin", "PlatformAdmin")
    records = db.all_of("job_postings")
    if role == "EmployerRecruiter":
        records = [p for p in records if p["employer_id"] == user_id]
    elif role == "Student":
        student = db.get("students", user_id)
        own_university = student["university_id"] if student else None
        records = [
            p for p in records
            if own_university is not None and posting_visible_to_university(p, own_university)
        ]
    f_employer = request.args.get("employer_id")
    f_status = request.args.get("status")
    f_university = request.args.get("university_id")
    if f_employer is not None:
        records = [p for p in records if p["employer_id"] == f_employer]
    if f_status is not None:
        records = [p for p in records if posting_reported_status(p) == f_status]
    if f_university is not None:
        records = [p for p in records if posting_visible_to_university(p, f_university)]
    return paginate(records, posting_view)


@bp.route("/job-postings/<posting_id>", methods=["GET"])
def get_posting(posting_id):
    user_id, role = get_context()
    require_role(role, "Student", "EmployerRecruiter", "CareerCenterAdmin", "PlatformAdmin")
    posting = db.get("job_postings", posting_id)
    if posting is None:
        fail("ERR_JOB_POSTING_NOT_FOUND", "JobPosting id does not exist")
    if role == "EmployerRecruiter" and user_id != posting["employer_id"]:
        fail("ERR_FORBIDDEN_OWNERSHIP", "Recruiter may read only their own postings")
    return success_object(posting_view(posting))


@bp.route("/job-postings/<posting_id>/transition", methods=["POST"])
def transition_posting(posting_id):
    user_id, role = get_context()
    require_role(role, "EmployerRecruiter", "PlatformAdmin")
    body = Body()
    to = body.str_f("to", required=True, enum=POSTING_STATUSES)
    # Priority 2 per-target role rules that do not need the entity.
    if role == "PlatformAdmin" and to is not None and to != "PUBLISHED":
        fail("ERR_UNAUTHORIZED_ROLE", "PlatformAdmin may only publish (to=PUBLISHED)")
    posting = db.get("job_postings", posting_id)
    if posting is None:
        fail("ERR_JOB_POSTING_NOT_FOUND", "JobPosting id does not exist")
    current = posting["status"]
    # Per-target role rules that depend on the stored status.
    if to == "PUBLISHED":
        if role == "EmployerRecruiter" and current == "SUBMITTED":
            fail("ERR_UNAUTHORIZED_ROLE", "Publication from SUBMITTED is the platform gate")
        if role == "PlatformAdmin" and current == "PAUSED":
            fail("ERR_UNAUTHORIZED_ROLE", "Resumption from PAUSED belongs to the owning recruiter")
    # Priority 3 ownership.
    if role == "EmployerRecruiter" and user_id != posting["employer_id"]:
        fail("ERR_FORBIDDEN_OWNERSHIP", "Recruiter may transition only their own postings")
    # Priority 5 state machine.
    if to is not None:
        if current == "CLOSED":
            fail("ERR_POSTING_TERMINAL", "Posting is CLOSED; no further transitions")
        legal = (
            (current == "DRAFT" and to == "SUBMITTED")
            or (current == "SUBMITTED" and to == "PUBLISHED")
            or (current == "PUBLISHED" and to == "PAUSED")
            or (current == "PAUSED" and to == "PUBLISHED")
            or (current in ("DRAFT", "SUBMITTED", "PUBLISHED", "PAUSED") and to == "CLOSED")
        )
        if not legal:
            fail("ERR_INVALID_POSTING_TRANSITION",
                 "Posting transition %s -> %s is not allowed" % (current, to))
        if to == "PUBLISHED":
            employer = db.get("employers", posting["employer_id"])
            if employer is None or employer["status"] != "APPROVED":
                fail("ERR_EMPLOYER_NOT_APPROVED", "Employer must be APPROVED to publish")
    body.finalize()
    posting["status"] = to
    db.touch(posting)
    return success_object(posting_view(posting))


@bp.route("/job-postings/<posting_id>/clearance", methods=["POST"])
def clearance_posting(posting_id):
    user_id, role = get_context()
    require_role(role, "CareerCenterAdmin")
    posting = db.get("job_postings", posting_id)
    if posting is None:
        fail("ERR_JOB_POSTING_NOT_FOUND", "JobPosting id does not exist")
    body = Body()
    university_id = body.str_f("university_id", required=True)
    decision = body.str_f("decision", required=True, enum=CLEARANCE_DECISIONS)
    # Priority 3 ownership: clearance applies at the caller's own university.
    if university_id is not None and university_id != user_id:
        fail("ERR_FORBIDDEN_OWNERSHIP", "Career center may clear only at its own university")
    if university_id is not None and db.get("universities", university_id) is None:
        fail("ERR_UNIVERSITY_NOT_FOUND", "University id does not exist")
    # Priority 5 state: posting must be PUBLISHED or PAUSED (stored).
    if posting["status"] == "CLOSED":
        fail("ERR_POSTING_TERMINAL", "Posting is CLOSED")
    if posting["status"] not in ("PUBLISHED", "PAUSED"):
        fail("ERR_INVALID_POSTING_TRANSITION",
             "Clearance requires stored status PUBLISHED or PAUSED")
    body.finalize()
    if decision == "BLOCK":
        block_posting_at_university(posting, university_id)
    else:
        if university_id in posting["blocked_university_ids"]:
            posting["blocked_university_ids"].remove(university_id)
        db.touch(posting)
    return success_object(posting_view(posting))

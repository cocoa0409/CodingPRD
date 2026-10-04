"""Applications (full gate chain) and interview scheduling."""

from flask import Blueprint, request

import db
from db import now, wall_now
from errors import fail
from services import (
    ACTIVE_APP_STATUSES,
    TERMINAL_APP_STATUSES,
    application_view,
    approval_exists,
    interview_conflict,
    interview_view,
    posting_reported_status,
    terminate_application,
)
from util import Body, get_context, paginate, require_role, success_object

bp = Blueprint("applications", __name__)

DOC_TYPES = ("RESUME", "COVER_LETTER", "TRANSCRIPT", "PORTFOLIO")
APPLICATION_STATUSES = (
    "SUBMITTED", "UNDER_REVIEW", "INTERVIEWING", "OFFER_EXTENDED",
    "ACCEPTED", "DECLINED", "REJECTED", "WITHDRAWN", "AUTO_WITHDRAWN",
)
INTERVIEW_MODES = ("VIRTUAL", "IN_PERSON")
RECRUITER_TARGETS = ("UNDER_REVIEW", "INTERVIEWING", "OFFER_EXTENDED", "REJECTED")
STUDENT_TARGETS = ("WITHDRAWN", "ACCEPTED", "DECLINED")

# Legal (from -> to) pairs of the application pipeline.
APPLICATION_TRANSITIONS = {
    ("SUBMITTED", "UNDER_REVIEW"),
    ("UNDER_REVIEW", "INTERVIEWING"),
    ("INTERVIEWING", "OFFER_EXTENDED"),
}
for _src in ACTIVE_APP_STATUSES:
    APPLICATION_TRANSITIONS.add((_src, "REJECTED"))
    APPLICATION_TRANSITIONS.add((_src, "WITHDRAWN"))
APPLICATION_TRANSITIONS.add(("OFFER_EXTENDED", "ACCEPTED"))
APPLICATION_TRANSITIONS.add(("OFFER_EXTENDED", "DECLINED"))


def _application_scope_check(role, user_id, application):
    if role == "Student" and user_id != application["student_id"]:
        fail("ERR_FORBIDDEN_OWNERSHIP", "Student may access only their own applications")
    if role == "EmployerRecruiter":
        posting = db.get("job_postings", application["job_posting_id"])
        if posting is None or posting["employer_id"] != user_id:
            fail("ERR_FORBIDDEN_OWNERSHIP", "Recruiter may access only applications to their own postings")
    if role == "CareerCenterAdmin":
        student = db.get("students", application["student_id"])
        if student is None or student["university_id"] != user_id:
            fail("ERR_FORBIDDEN_OWNERSHIP", "Career center may access only its own students' applications")


@bp.route("/applications", methods=["POST"])
def create_application():
    user_id, role = get_context()
    require_role(role, "Student")
    body = Body()
    student_id = body.str_f("student_id", required=True)
    job_posting_id = body.str_f("job_posting_id", required=True)
    submitted_documents = None
    if body.has("submitted_documents"):
        raw_docs = body.raw("submitted_documents")
        if (
            not isinstance(raw_docs, list)
            or any(not isinstance(d, dict) for d in raw_docs)
            or any(d.get("doc_type") not in DOC_TYPES or not isinstance(d.get("file_uri"), str) for d in raw_docs)
        ):
            body.bad = True
        else:
            submitted_documents = [
                {"doc_type": d["doc_type"], "file_uri": d["file_uri"]} for d in raw_docs
            ]
    else:
        body.bad = True
    # Priority 3 ownership.
    if student_id is not None and student_id != user_id:
        fail("ERR_FORBIDDEN_OWNERSHIP", "Student may apply only as themselves")
    # Priority 4 existence, body FK order: student_id, then job_posting_id.
    student = db.get("students", student_id) if student_id else None
    if student_id is not None and student is None:
        fail("ERR_STUDENT_NOT_FOUND", "Student id does not exist")
    posting = db.get("job_postings", job_posting_id) if job_posting_id else None
    if job_posting_id is not None and posting is None:
        fail("ERR_JOB_POSTING_NOT_FOUND", "JobPosting id does not exist")
    # Priority 5 state gates: ENROLLED, university ACTIVE, stored PUBLISHED.
    if student is not None and student["status"] != "ENROLLED":
        fail("ERR_STUDENT_NOT_ENROLLED", "Student must be ENROLLED")
    if student is not None:
        university = db.get("universities", student["university_id"])
        if university is not None and university["status"] != "ACTIVE":
            fail("ERR_UNIVERSITY_NOT_ACTIVE", "University is not ACTIVE")
    if posting is not None and posting["status"] != "PUBLISHED":
        fail("ERR_POSTING_NOT_PUBLISHED", "Application requires stored posting status PUBLISHED")
    # Priority 7 safety gates: university-level approval, then block list.
    if student is not None and posting is not None:
        if not approval_exists(posting["employer_id"], student["university_id"]):
            fail("ERR_EMPLOYER_NOT_APPROVED_FOR_UNIVERSITY",
                 "No APPROVED employer approval exists for this university")
        if student["university_id"] in posting["blocked_university_ids"]:
            fail("ERR_POSTING_BLOCKED_FOR_UNIVERSITY",
                 "This posting is blocked at the student's university")
    # Priority 8 temporal: inclusive application deadline.
    if posting is not None and now() > posting["application_deadline"]:
        fail("ERR_APPLICATION_DEADLINE_PASSED", "The application deadline has passed")
    # Priority 9 constraints: eligibility in pinned order, then duplicate.
    if student is not None and posting is not None:
        if posting["required_majors"] and student["major"] not in posting["required_majors"]:
            fail("ERR_MAJOR_NOT_ELIGIBLE", "Student major is not eligible for this posting")
        if not (posting["min_graduation_year"] <= student["graduation_year"] <= posting["max_graduation_year"]):
            fail("ERR_GRAD_YEAR_NOT_ELIGIBLE", "Student graduation year is outside the eligible bounds")
        if posting["accepted_work_authorizations"] and student["work_authorization"] not in posting["accepted_work_authorizations"]:
            fail("ERR_WORK_AUTHORIZATION_NOT_ELIGIBLE", "Student work authorization is not accepted")
        if submitted_documents is not None:
            submitted_types = [d["doc_type"] for d in submitted_documents]
            if any(t not in submitted_types for t in posting["required_documents"]):
                fail("ERR_DOCUMENT_REQUIREMENTS_NOT_MET", "A required document type is missing")
        duplicate = any(
            a["student_id"] == student_id
            and a["job_posting_id"] == job_posting_id
            and a["status"] in ACTIVE_APP_STATUSES
            for a in db.all_of("applications")
        )
        if duplicate:
            fail("ERR_DUPLICATE_APPLICATION", "An active application already exists for this pair")
    body.finalize()
    record = {
        "id": db.new_id(),
        "student_id": student_id,
        "job_posting_id": job_posting_id,
        "status": "SUBMITTED",
        "submitted_documents": submitted_documents,
        "submitted_at": now(),
        "decided_at": None,
        "created_at": wall_now(),
        "updated_at": wall_now(),
        "version": 1,
    }
    db.insert("applications", record)
    return success_object(application_view(record), 201)


@bp.route("/applications", methods=["GET"])
def list_applications():
    user_id, role = get_context()
    require_role(role, "Student", "EmployerRecruiter", "CareerCenterAdmin", "PlatformAdmin")
    records = db.all_of("applications")
    if role == "Student":
        records = [a for a in records if a["student_id"] == user_id]
    elif role == "EmployerRecruiter":
        scoped = []
        for a in records:
            posting = db.get("job_postings", a["job_posting_id"])
            if posting is not None and posting["employer_id"] == user_id:
                scoped.append(a)
        records = scoped
    elif role == "CareerCenterAdmin":
        scoped = []
        for a in records:
            student = db.get("students", a["student_id"])
            if student is not None and student["university_id"] == user_id:
                scoped.append(a)
        records = scoped
    f_student = request.args.get("student_id")
    f_posting = request.args.get("job_posting_id")
    f_status = request.args.get("status")
    if f_student is not None:
        records = [a for a in records if a["student_id"] == f_student]
    if f_posting is not None:
        records = [a for a in records if a["job_posting_id"] == f_posting]
    if f_status is not None:
        records = [a for a in records if a["status"] == f_status]
    return paginate(records, application_view)


@bp.route("/applications/<application_id>", methods=["GET"])
def get_application(application_id):
    user_id, role = get_context()
    require_role(role, "Student", "EmployerRecruiter", "CareerCenterAdmin", "PlatformAdmin")
    application = db.get("applications", application_id)
    if application is None:
        fail("ERR_APPLICATION_NOT_FOUND", "Application id does not exist")
    _application_scope_check(role, user_id, application)
    return success_object(application_view(application))


@bp.route("/applications/<application_id>/transition", methods=["POST"])
def transition_application(application_id):
    user_id, role = get_context()
    require_role(role, "EmployerRecruiter", "Student")
    body = Body()
    to = body.str_f("to", required=True, enum=APPLICATION_STATUSES)
    # Priority 2 per-target role rules.
    if to is not None:
        if role == "EmployerRecruiter" and to not in RECRUITER_TARGETS:
            fail("ERR_UNAUTHORIZED_ROLE", "Recruiter may target only %s" % (", ".join(RECRUITER_TARGETS)))
        if role == "Student" and to not in STUDENT_TARGETS:
            fail("ERR_UNAUTHORIZED_ROLE", "Student may target only %s" % (", ".join(STUDENT_TARGETS)))
    application = db.get("applications", application_id)
    if application is None:
        fail("ERR_APPLICATION_NOT_FOUND", "Application id does not exist")
    _application_scope_check(role, user_id, application)
    # Priority 5 state machine.
    if to is not None:
        if application["status"] in TERMINAL_APP_STATUSES:
            fail("ERR_APPLICATION_TERMINAL", "Application is already in a terminal status")
        if (application["status"], to) not in APPLICATION_TRANSITIONS:
            fail("ERR_INVALID_APPLICATION_TRANSITION",
                 "Application transition %s -> %s is not allowed" % (application["status"], to))
    body.finalize()
    if to in TERMINAL_APP_STATUSES:
        terminate_application(application, to)
    else:
        application["status"] = to
        db.touch(application)
    return success_object(application_view(application))


@bp.route("/applications/<application_id>/interviews", methods=["POST"])
def create_interview(application_id):
    user_id, role = get_context()
    require_role(role, "EmployerRecruiter")
    application = db.get("applications", application_id)
    if application is None:
        fail("ERR_APPLICATION_NOT_FOUND", "Application id does not exist")
    _application_scope_check(role, user_id, application)
    body = Body()
    interviewer_email = body.str_f("interviewer_email", required=True)
    mode = body.str_f("mode", required=True, enum=INTERVIEW_MODES)
    starts_at = body.dt_f("starts_at", required=True)
    ends_at = body.dt_f("ends_at", required=True)
    # Priority 5 state.
    if application["status"] != "INTERVIEWING":
        fail("ERR_APPLICATION_NOT_INTERVIEWING",
             "Interview creation requires application status INTERVIEWING")
    # Priority 8 temporal.
    if starts_at is not None and ends_at is not None and not starts_at < ends_at:
        fail("ERR_TIME_RANGE_INVALID", "starts_at must be strictly before ends_at")
    # Priority 9 constraint: buffered interviewer overlap across the marketplace.
    if (
        interviewer_email is not None and starts_at is not None and ends_at is not None
        and interview_conflict(interviewer_email, starts_at, ends_at)
    ):
        fail("ERR_INTERVIEW_SCHEDULE_CONFLICT",
             "Interviewer has a SCHEDULED interview within the buffered window")
    body.finalize()
    record = {
        "id": db.new_id(),
        "application_id": application["id"],
        "interviewer_email": interviewer_email,
        "mode": mode,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "status": "SCHEDULED",
        "created_at": wall_now(),
        "updated_at": wall_now(),
        "version": 1,
    }
    db.insert("interviews", record)
    return success_object(interview_view(record), 201)


@bp.route("/applications/<application_id>/interviews", methods=["GET"])
def list_interviews(application_id):
    user_id, role = get_context()
    require_role(role, "EmployerRecruiter", "Student", "CareerCenterAdmin", "PlatformAdmin")
    application = db.get("applications", application_id)
    if application is None:
        fail("ERR_APPLICATION_NOT_FOUND", "Application id does not exist")
    _application_scope_check(role, user_id, application)
    records = [iv for iv in db.all_of("interviews") if iv["application_id"] == application["id"]]
    return paginate(records, interview_view)

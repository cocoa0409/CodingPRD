"""Proactive employer outreach with the daily messaging allowance."""

from flask import Blueprint, request

import db
from db import now, wall_now
from errors import fail
from services import (
    approval_exists,
    message_view,
    messaging_effective_cap,
    messages_sent_today,
)
from util import Body, get_context, paginate, require_role, success_object

bp = Blueprint("outreach", __name__)


def _message_scope_check(role, user_id, message):
    if role == "EmployerRecruiter" and user_id != message["employer_id"]:
        fail("ERR_FORBIDDEN_OWNERSHIP", "Recruiter may access only their own messages")
    if role == "Student" and user_id != message["student_id"]:
        fail("ERR_FORBIDDEN_OWNERSHIP", "Student may access only their own messages")
    if role == "CareerCenterAdmin" and user_id != message["university_id"]:
        fail("ERR_FORBIDDEN_OWNERSHIP", "Career center may access only its own university's messages")


@bp.route("/outreach-messages", methods=["POST"])
def create_message():
    user_id, role = get_context()
    require_role(role, "EmployerRecruiter")
    body = Body()
    employer_id = body.str_f("employer_id", required=True)
    student_id = body.str_f("student_id", required=True)
    text = body.str_f("body", required=True)
    # Priority 3 ownership.
    if employer_id is not None and employer_id != user_id:
        fail("ERR_FORBIDDEN_OWNERSHIP", "Recruiter may send only as their own employer")
    # Priority 4 existence, body FK order: employer_id, then student_id.
    employer = db.get("employers", employer_id) if employer_id else None
    if employer_id is not None and employer is None:
        fail("ERR_EMPLOYER_NOT_FOUND", "Employer id does not exist")
    student = db.get("students", student_id) if student_id else None
    if student_id is not None and student is None:
        fail("ERR_STUDENT_NOT_FOUND", "Student id does not exist")
    # Priority 5 state gates.
    if employer is not None and employer["status"] != "APPROVED":
        fail("ERR_EMPLOYER_NOT_APPROVED", "Employer must be APPROVED to send outreach")
    if student is not None and student["status"] != "ENROLLED":
        fail("ERR_STUDENT_NOT_ENROLLED", "Student must be ENROLLED")
    university = db.get("universities", student["university_id"]) if student else None
    if university is not None and university["status"] != "ACTIVE":
        fail("ERR_UNIVERSITY_NOT_ACTIVE", "University is not ACTIVE")
    # Priority 7 safety gates: approval, then profile visibility.
    if employer is not None and student is not None:
        if not approval_exists(employer["id"], student["university_id"]):
            fail("ERR_EMPLOYER_NOT_APPROVED_FOR_UNIVERSITY",
                 "No APPROVED employer approval exists for the student's university")
        if student["profile_visibility"] != "PUBLIC_TO_APPROVED_EMPLOYERS":
            fail("ERR_PROFILE_NOT_VISIBLE", "Student profile is not visible to employers")
    # Priority 10 capacity: the daily messaging allowance.
    if employer is not None and university is not None:
        effective_cap = messaging_effective_cap(employer, university)
        sent_today = messages_sent_today(employer["id"], university["id"])
        if not sent_today < effective_cap:
            fail("ERR_MESSAGE_LIMIT_REACHED", "Daily messaging allowance reached")
    body.finalize()
    record = {
        "id": db.new_id(),
        "employer_id": employer_id,
        "student_id": student_id,
        "university_id": student["university_id"],
        "body": text,
        "sent_day": now().strftime("%Y-%m-%d"),
        "created_at": wall_now(),
        "updated_at": wall_now(),
        "version": 1,
    }
    db.insert("outreach_messages", record)
    return success_object(message_view(record), 201)


@bp.route("/outreach-messages", methods=["GET"])
def list_messages():
    user_id, role = get_context()
    require_role(role, "EmployerRecruiter", "Student", "CareerCenterAdmin", "PlatformAdmin")
    records = db.all_of("outreach_messages")
    if role == "EmployerRecruiter":
        records = [m for m in records if m["employer_id"] == user_id]
    elif role == "Student":
        records = [m for m in records if m["student_id"] == user_id]
    elif role == "CareerCenterAdmin":
        records = [m for m in records if m["university_id"] == user_id]
    f_employer = request.args.get("employer_id")
    f_student = request.args.get("student_id")
    f_university = request.args.get("university_id")
    if f_employer is not None:
        records = [m for m in records if m["employer_id"] == f_employer]
    if f_student is not None:
        records = [m for m in records if m["student_id"] == f_student]
    if f_university is not None:
        records = [m for m in records if m["university_id"] == f_university]
    return paginate(records, message_view)


@bp.route("/outreach-messages/<message_id>", methods=["GET"])
def get_message(message_id):
    user_id, role = get_context()
    require_role(role, "EmployerRecruiter", "Student", "CareerCenterAdmin", "PlatformAdmin")
    message = db.get("outreach_messages", message_id)
    if message is None:
        fail("ERR_OUTREACH_MESSAGE_NOT_FOUND", "OutreachMessage id does not exist")
    _message_scope_check(role, user_id, message)
    return success_object(message_view(message))

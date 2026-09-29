"""Lesson plans: submission, revision under OCC, approval and revision requests."""
from flask import Blueprint, g

import serial
from core import base_row, fail, now, store, touch
from routes.common import body_fk, created, listing, ok, path_row, require_roles
from validate import body, opt_str, query_enum, query_str, req_decimal, req_int, req_str

bp = Blueprint("plans", __name__)

PLAN_STATUSES = ("SUBMITTED", "REVISION_REQUESTED", "APPROVED")
READ_ROLES = ("AcademyDirector", "TrainingCoordinator", "RecordsCustodian", "AcademyInstructor")


def _owner_gate(plan):
    """Rung 4: an AcademyInstructor may only act on their own plan."""
    if g.role == "AcademyInstructor" and g.user_id != plan["instructor_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "acting user does not author this lesson plan")


@bp.post("/lesson-plans")
def create_plan():
    require_roles("AcademyInstructor", "TrainingCoordinator")
    payload = body()
    instructor = body_fk(payload, "instructor_id", "instructors")
    instructor_id = req_str(payload, "instructor_id", min_len=1)
    topic_code = req_str(payload, "topic_code", min_len=1, max_len=24, upper=True)
    title = req_str(payload, "title", min_len=1, max_len=160)
    contact_hours = req_decimal(payload, "contact_hours", minimum=0, exclusive_min=True)
    if instructor is None:
        fail("ERR_INSTRUCTOR_NOT_FOUND")

    if g.role == "AcademyInstructor" and g.user_id != instructor_id:
        fail("ERR_NOT_RESOURCE_OWNER",
             "an instructor may only author their own lesson plan")

    row = base_row()
    row.update({
        "instructor_id": instructor_id,
        "topic_code": topic_code,
        "title": title,
        "contact_hours": contact_hours,
        "status": "SUBMITTED",
        "revision_number": 1,
        "approved_revision_number": None,
        "approved_at": None,
        "approved_by_user_id": None,
        "reviewer_notes": None,
    })
    store.plans[row["id"]] = row
    return created(serial.plan_json(row))


@bp.get("/lesson-plans/<lesson_plan_id>")
def read_plan(lesson_plan_id):
    require_roles(*READ_ROLES)
    row = path_row("plans", lesson_plan_id)
    return ok(serial.plan_json(row))


@bp.get("/lesson-plans")
def list_plans():
    require_roles(*READ_ROLES)
    instructor_id = query_str("instructor_id")
    topic_code = query_str("topic_code")
    status = query_enum("status", PLAN_STATUSES)

    def predicate(row):
        if instructor_id is not None and row["instructor_id"] != instructor_id:
            return False
        if topic_code is not None and row["topic_code"] != topic_code:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return listing("plans", serial.plan_json, predicate)


@bp.post("/lesson-plans/<lesson_plan_id>/revisions")
def revise_plan(lesson_plan_id):
    require_roles("AcademyInstructor", "TrainingCoordinator")
    row = path_row("plans", lesson_plan_id)
    _owner_gate(row)
    payload = body()
    expected = req_int(payload, "expected_lesson_plan_version")
    contact_hours = req_decimal(payload, "contact_hours", minimum=0, exclusive_min=True)
    req_str(payload, "revision_notes", min_len=1, max_len=2000)

    if expected != row["version"]:
        fail("ERR_STALE_LESSON_PLAN_VERSION",
             "expected_lesson_plan_version does not match the plan's version")

    if row["status"] not in ("REVISION_REQUESTED", "APPROVED"):
        fail("ERR_INVALID_STATE", "a revision is not declared from %s" % row["status"])

    row["status"] = "SUBMITTED"
    row["revision_number"] = row["revision_number"] + 1
    row["contact_hours"] = contact_hours
    row["reviewer_notes"] = None
    touch(row)
    return ok(serial.plan_json(row))


@bp.post("/lesson-plans/<lesson_plan_id>/approve")
def approve_plan(lesson_plan_id):
    require_roles("AcademyDirector")
    row = path_row("plans", lesson_plan_id)

    if row["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "approval is not declared from %s" % row["status"])

    instructor = store.instructors.get(row["instructor_id"])
    if (instructor is None
            or instructor["certification_status"] != "CERTIFIED"
            or row["topic_code"] not in instructor["authorized_topic_codes"]):
        fail("ERR_INSTRUCTOR_NOT_AUTHORIZED",
             "the authoring instructor is not certified for this topic")

    if g.user_id == row["instructor_id"]:
        fail("ERR_SAME_ACTOR_ADJUDICATION",
             "the approving user may not be the authoring instructor")

    row["status"] = "APPROVED"
    row["approved_revision_number"] = row["revision_number"]
    row["approved_at"] = now()
    row["approved_by_user_id"] = g.user_id
    touch(row)
    return ok(serial.plan_json(row))


@bp.post("/lesson-plans/<lesson_plan_id>/request-revision")
def request_revision(lesson_plan_id):
    require_roles("AcademyDirector")
    row = path_row("plans", lesson_plan_id)
    payload = body()
    reviewer_notes = req_str(payload, "reviewer_notes", min_len=1, max_len=2000)

    if row["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE",
             "a revision request is not declared from %s" % row["status"])

    row["status"] = "REVISION_REQUESTED"
    row["reviewer_notes"] = reviewer_notes
    row["approved_revision_number"] = None
    row["approved_at"] = None
    row["approved_by_user_id"] = None
    touch(row)
    return ok(serial.plan_json(row))

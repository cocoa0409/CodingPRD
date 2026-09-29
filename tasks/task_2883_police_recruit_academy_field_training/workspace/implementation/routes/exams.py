"""Examinations: scheduling, grading (cascade A) and remediation."""
from decimal import Decimal

from flask import Blueprint, g

import calc
import ops
import serial
from core import ZERO2, base_row, d2, fail, now, store, touch
from routes.common import (
    body_fk,
    check_recruit_in_academy,
    check_recruit_not_terminal,
    created,
    listing,
    ok,
    path_row,
    require_roles,
)
from validate import body, query_enum, query_str, req_decimal, req_str

bp = Blueprint("exams", __name__)

EXAM_STATUSES = ("SCHEDULED", "PASSED", "FAILED", "REMEDIATION_ASSIGNED", "FAILED_FINAL")
READ_ONE_ROLES = ("AcademyDirector", "TrainingCoordinator", "RecordsCustodian",
                  "AcademyInstructor", "Recruit")
LIST_ROLES = ("AcademyDirector", "TrainingCoordinator", "RecordsCustodian",
              "AcademyInstructor")


@bp.post("/examinations")
def create_exam():
    require_roles("TrainingCoordinator", "AcademyInstructor")
    payload = body()
    recruit = body_fk(payload, "recruit_id", "recruits")
    recruit_id = req_str(payload, "recruit_id", min_len=1)
    topic_code = req_str(payload, "topic_code", min_len=1, max_len=24, upper=True)

    check_recruit_not_terminal(recruit)
    check_recruit_in_academy(recruit)

    standard = calc.standard_for_recruit(recruit)
    requirement = (calc.topic_requirement(standard, topic_code)
                   if standard is not None else None)
    if requirement is None:
        fail("ERR_TOPIC_NOT_IN_STANDARD",
             "topic %s is not part of the cohort's certification standard" % topic_code)
    if not requirement["exam_required"]:
        fail("ERR_EXAM_NOT_REQUIRED_FOR_TOPIC",
             "topic %s does not require an examination" % topic_code)

    prior = [row for row in calc.recruit_exams(recruit_id)
             if row["topic_code"] == topic_code]

    row = base_row()
    row.update({
        "recruit_id": recruit_id,
        "topic_code": topic_code,
        "attempt_number": 1 + len(prior),
        "raw_score": None,
        "passing_score": d2(standard["min_passing_score"]),
        "status": "SCHEDULED",
        "remediation_hours": ZERO2,
        "graded_at": None,
        "graded_by_user_id": None,
    })
    store.exams[row["id"]] = row
    return created(serial.exam_json(row))


@bp.get("/examinations/<examination_id>")
def read_exam(examination_id):
    require_roles(*READ_ONE_ROLES)
    row = path_row("exams", examination_id)
    return ok(serial.exam_json(row))


@bp.get("/examinations")
def list_exams():
    require_roles(*LIST_ROLES)
    recruit_id = query_str("recruit_id")
    topic_code = query_str("topic_code")
    status = query_enum("status", EXAM_STATUSES)

    def predicate(row):
        if recruit_id is not None and row["recruit_id"] != recruit_id:
            return False
        if topic_code is not None and row["topic_code"] != topic_code:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return listing("exams", serial.exam_json, predicate)


@bp.post("/examinations/<examination_id>/grade")
def grade_exam(examination_id):
    require_roles("AcademyInstructor", "TrainingCoordinator")
    exam = path_row("exams", examination_id)
    payload = body()
    raw_score = req_decimal(payload, "raw_score", minimum=0, maximum=100)

    if exam["status"] not in ("SCHEDULED", "REMEDIATION_ASSIGNED"):
        fail("ERR_INVALID_STATE", "an examination at %s cannot be graded" % exam["status"])

    recruit = store.recruits.get(exam["recruit_id"])
    if recruit is None:
        fail("ERR_RECRUIT_NOT_FOUND")
    check_recruit_in_academy(recruit)

    standard = calc.standard_for_recruit(recruit)
    max_attempts = 1 + (standard["max_remediation_attempts"] if standard is not None else 0)

    exam["raw_score"] = raw_score
    exam["graded_at"] = now()
    exam["graded_by_user_id"] = g.user_id

    passed = raw_score >= d2(exam["passing_score"])
    if passed:
        exam["status"] = "PASSED"
    elif exam["attempt_number"] < max_attempts:
        exam["status"] = "FAILED"
    else:
        exam["status"] = "FAILED_FINAL"
    touch(exam)

    ops.append_entry(
        recruit,
        "EXAM_RESULT",
        stage_code="ACADEMY",
        topic_code=exam["topic_code"],
        subject_entity="Examination",
        subject_entity_id=exam["id"],
        detail="examination graded %s" % exam["status"],
    )
    touch(recruit)

    if exam["status"] == "FAILED_FINAL":
        ops.cascade_a(recruit)
    elif passed:
        if recruit["academy_status"] == "REMEDIATION":
            held = [row for row in calc.recruit_exams(recruit["id"])
                    if row["id"] != exam["id"]
                    and row["status"] in ("FAILED", "REMEDIATION_ASSIGNED")]
            if not held:
                recruit["academy_status"] = "IN_PROGRESS"
        if recruit["academy_status"] == "IN_PROGRESS" and calc.curriculum_satisfied(recruit):
            recruit["academy_status"] = "COMPLETE"

    return ok(serial.exam_json(exam))


@bp.post("/examinations/<examination_id>/assign-remediation")
def assign_remediation(examination_id):
    require_roles("TrainingCoordinator")
    exam = path_row("exams", examination_id)
    payload = body()
    hours = req_decimal(payload, "remediation_hours", minimum=0)

    if exam["status"] != "FAILED":
        fail("ERR_INVALID_STATE",
             "remediation is not declared from %s" % exam["status"])

    recruit = store.recruits.get(exam["recruit_id"])
    if recruit is None:
        fail("ERR_RECRUIT_NOT_FOUND")
    check_recruit_in_academy(recruit)

    standard = calc.standard_for_recruit(recruit)
    budget = standard["max_remediation_attempts"] if standard is not None else 0
    if calc.recruit_remediation_attempts_used(recruit) >= budget:
        fail("ERR_REMEDIATION_ATTEMPTS_EXHAUSTED",
             "the recruit's remediation budget is exhausted")

    exam["status"] = "REMEDIATION_ASSIGNED"
    exam["attempt_number"] = exam["attempt_number"] + 1
    exam["remediation_hours"] = d2(d2(exam["remediation_hours"]) + hours)
    touch(exam)

    if recruit["academy_status"] == "IN_PROGRESS":
        recruit["academy_status"] = "REMEDIATION"
    touch(recruit)

    return ok(serial.exam_json(exam))

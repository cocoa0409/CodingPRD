"""Office encounters and administration records."""
from flask import Blueprint, request

import calc
import cascades
import serializers as ser
from auth import (ALL_READ_ROLES, ALL_READ_ROLES_WITH_GUARDIAN, authorize,
                  guardian_owns, insert, must_exist, nurse_owns, resolve, rows)
from envelope import created, listing, ok, parse_pagination
from errors import fail
from store import (db, floor_minutes, minutes, new_record, same_utc_day,
                   sorted_rows, touch, days)
from validators import Field, get_body, supplied, validate, value_or

bp = Blueprint("visits", __name__)

COMPLAINTS = {"INJURY", "ILLNESS", "MEDICATION", "CHRONIC_CARE",
              "MENTAL_HEALTH", "SCREENING_FOLLOWUP"}
ACUITIES = {"ROUTINE", "URGENT", "EMERGENT"}
DISPOSITIONS = {"RETURN_TO_CLASS", "SEND_HOME", "EMS_TRANSPORT", "REFERRED_EXTERNAL"}
CLINICAL_ROLES = ["SchoolNurse", "HealthAide"]


def _credential_allows(nurse, is_controlled):
    if nurse is None:
        return False
    if nurse.get("credential") == "RN":
        return True
    return bool(nurse.get("delegation_authorized")) and not is_controlled


# ---------------------------------------------------------------------------
# HealthVisit
# ---------------------------------------------------------------------------

@bp.post("/health-office/health-visits")
def create_visit():
    authorize(CLINICAL_ROLES)
    body = get_body(request)
    student = resolve("students", body.get("student_id"), "Student")
    school = resolve("schools", body.get("school_id"), "School")
    nurse = resolve("nurses", body.get("nurse_id"), "Nurse")
    if student is not None and school is not None and student["school_id"] != school["id"]:
        fail("ERR_RESOURCE_NOT_FOUND", "The student is not enrolled at that building.")
    values = validate(body, [
        Field("student_id", "string"),
        Field("school_id", "string"),
        Field("nurse_id", "string"),
        Field("complaint_code", "enum", enum=COMPLAINTS),
        Field("acuity", "enum", enum=ACUITIES),
    ])
    if student["enrollment_status"] != "ENROLLED":
        fail("ERR_STUDENT_NOT_ENROLLED", "The student is not enrolled.")
    derived = calc.school_derived(school)
    if derived["coverage_posture"] not in ("FULL", "LIMITED"):
        fail("ERR_SCHOOL_COVERAGE_UNAVAILABLE",
             "The building has no nurse coverage for new encounters.")
    if derived["occupied_cot_count"] >= school["cot_capacity"]:
        fail("ERR_OFFICE_CAPACITY_EXCEEDED", "Every cot in the health office is occupied.")
    record = new_record({
        "student_id": student["id"],
        "school_id": school["id"],
        "nurse_id": nurse["id"],
        "complaint_code": values["complaint_code"],
        "acuity": values["acuity"],
        "assessment_note": None,
        "arrival_at": db.now(),
        "closed_at": None,
        "disposition": None,
        "guardian_notified": False,
        "reopen_count": 0,
        "minutes_in_office": None,
        "status": "OPEN",
    })
    score = calc.triage_score(record, student, school)
    record["triage_score"] = score
    record["requires_ems_review"] = score >= calc.EMS_REVIEW_MIN
    insert("health_visits", record)
    return created(ser.visit_json(record))


@bp.get("/health-office/health-visits/<visit_id>")
def get_visit(visit_id):
    user_id, role = authorize(ALL_READ_ROLES_WITH_GUARDIAN)
    visit = db.health_visits.get(visit_id)
    guardian_owns(visit, user_id, role)
    visit = must_exist("health_visits", visit_id, "HealthVisit")
    return ok(ser.visit_json(visit))


@bp.get("/health-office/health-visits")
def list_visits():
    authorize(ALL_READ_ROLES)
    limit, offset = parse_pagination(request.args)
    result = rows("health_visits")
    for key in ("student_id", "school_id", "nurse_id", "status", "disposition"):
        value = request.args.get(key)
        if value:
            result = [r for r in result if r.get(key) == value]
    return listing([ser.visit_json(r) for r in sorted_rows(result)], limit, offset)


@bp.post("/health-office/health-visits/<visit_id>/assess")
def assess_visit(visit_id):
    user_id, role = authorize(CLINICAL_ROLES)
    visit = db.health_visits.get(visit_id)
    nurse_owns(visit, user_id, role, "nurse_id")
    visit = must_exist("health_visits", visit_id, "HealthVisit")
    body = get_body(request)
    values = validate(body, [Field("assessment_note", "string", required=False)])
    if visit["status"] not in ("OPEN", "REOPENED"):
        fail("ERR_VISIT_INVALID_STATE", "Only an OPEN or REOPENED encounter may be assessed.")
    if not calc.nurse_on_active_coverage(visit["nurse_id"], visit["school_id"]):
        fail("ERR_NURSE_NOT_ON_COVERAGE",
             "The nurse holds no active coverage block at this building right now.")
    visit["status"] = "IN_ASSESSMENT"
    if supplied(values, "assessment_note"):
        visit["assessment_note"] = values["assessment_note"]
    touch(visit)
    return ok(ser.visit_json(visit))


@bp.post("/health-office/health-visits/<visit_id>/dispose")
def dispose_visit(visit_id):
    user_id, role = authorize(CLINICAL_ROLES)
    visit = db.health_visits.get(visit_id)
    nurse_owns(visit, user_id, role, "nurse_id")
    visit = must_exist("health_visits", visit_id, "HealthVisit")
    body = get_body(request)
    values = validate(body, [
        Field("disposition", "enum", enum=DISPOSITIONS),
        Field("guardian_notified", "boolean", required=False),
    ])
    disposition = values["disposition"]
    if visit["status"] != "IN_ASSESSMENT":
        fail("ERR_VISIT_INVALID_STATE", "Only an encounter in assessment may be dispositioned.")
    if disposition == "REFERRED_EXTERNAL" and visit["complaint_code"] != "SCREENING_FOLLOWUP":
        fail("ERR_VISIT_INVALID_STATE",
             "REFERRED_EXTERNAL requires a SCREENING_FOLLOWUP complaint.")
    student = db.students.get(visit["student_id"])
    if disposition == "RETURN_TO_CLASS":
        if visit["complaint_code"] == "ILLNESS" and student is not None \
                and student.get("immunization_status") == "NONCOMPLIANT":
            fail("ERR_IMMUNIZATION_HOLD",
                 "A noncompliant student with an illness may not be returned to class.")
    elif disposition == "SEND_HOME":
        if value_or(values, "guardian_notified", False) is not True:
            fail("ERR_GUARDIAN_NOTIFICATION_REQUIRED",
                 "SEND_HOME requires guardian_notified to be true.")
    elif disposition == "EMS_TRANSPORT":
        if visit["acuity"] != "EMERGENT" and visit["triage_score"] < calc.EMS_REVIEW_MIN:
            fail("ERR_EMS_DISPOSITION_NOT_JUSTIFIED",
                 "EMS transport requires an EMERGENT acuity or a triage score of 85.")

    visit["disposition"] = disposition
    visit["status"] = "DISPOSITIONED"
    if disposition == "SEND_HOME":
        visit["guardian_notified"] = True
    elif disposition == "EMS_TRANSPORT":
        visit["guardian_notified"] = True
    touch(visit)

    clock = db.now()
    if disposition == "SEND_HOME":
        for screening in db.screenings.values():
            if screening["student_id"] != visit["student_id"]:
                continue
            if screening["status"] != "SCHEDULED":
                continue
            if not same_utc_day(screening["scheduled_for"], clock):
                continue
            screening["status"] = "RESCREEN_DUE"
            screening["rescreen_due_at"] = clock + days(calc.RESCREEN_DAYS)
            touch(screening)
        cascades.recompute_observed(student)
    elif disposition == "EMS_TRANSPORT":
        cascades.recompute_observed(student)
    elif disposition == "REFERRED_EXTERNAL":
        for screening in db.screenings.values():
            if screening["student_id"] != visit["student_id"]:
                continue
            if screening["status"] != "REFERRED":
                continue
            screening["referral_due_at"] = clock + days(calc.REFERRAL_DAYS)
            touch(screening)
    return ok(ser.visit_json(visit))


@bp.post("/health-office/health-visits/<visit_id>/close")
def close_visit(visit_id):
    user_id, role = authorize(CLINICAL_ROLES)
    visit = db.health_visits.get(visit_id)
    nurse_owns(visit, user_id, role, "nurse_id")
    visit = must_exist("health_visits", visit_id, "HealthVisit")
    if visit["status"] != "DISPOSITIONED":
        fail("ERR_VISIT_INVALID_STATE", "Only a dispositioned encounter may be closed.")
    if calc.pending_administration_count(visit["id"]) != 0:
        fail("ERR_PENDING_ADMINISTRATION", "A dose is still reserved for this encounter.")
    clock = db.now()
    visit["closed_at"] = clock
    visit["status"] = "CLOSED"
    visit["minutes_in_office"] = floor_minutes(clock - visit["arrival_at"])
    touch(visit)
    cascades.recompute_observed(db.students.get(visit["student_id"]))
    return ok(ser.visit_json(visit))


@bp.post("/health-office/health-visits/<visit_id>/reopen")
def reopen_visit(visit_id):
    user_id, role = authorize(["SchoolNurse"])
    visit = db.health_visits.get(visit_id)
    nurse_owns(visit, user_id, role, "nurse_id")
    visit = must_exist("health_visits", visit_id, "HealthVisit")
    body = get_body(request)
    values = validate(body, [Field("reason_code", "string", required=False)])
    if visit["status"] != "CLOSED":
        fail("ERR_VISIT_INVALID_STATE", "Only a closed encounter may be reopened.")
    school = db.schools.get(visit["school_id"])
    if calc.occupied_cot_count(visit["school_id"]) >= school["cot_capacity"]:
        fail("ERR_OFFICE_CAPACITY_EXCEEDED", "Every cot in the health office is occupied.")
    clock = db.now()
    if not clock < visit["closed_at"] + minutes(calc.REOPEN_WINDOW_MINUTES):
        fail("ERR_REOPEN_WINDOW_CLOSED", "The reopen window has closed.")
    if visit["reopen_count"] >= calc.MAX_REOPENS:
        fail("ERR_REOPEN_LIMIT_REACHED", "This encounter has already been reopened.")
    visit["status"] = "REOPENED"
    visit["disposition"] = None
    visit["closed_at"] = None
    visit["minutes_in_office"] = None
    visit["reopen_count"] += 1
    if supplied(values, "reason_code"):
        visit["reason_code"] = values["reason_code"]
    student = db.students.get(visit["student_id"])
    score = calc.triage_score(visit, student, school)
    visit["triage_score"] = score
    visit["requires_ems_review"] = score >= calc.EMS_REVIEW_MIN
    touch(visit)
    return ok(ser.visit_json(visit))

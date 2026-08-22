"""Screenings, disclosure requests, the logical clock and the daily checkpoint."""
from flask import Blueprint, request

import calc
import cascades
import serializers as ser
from auth import (ALL_READ_ROLES, ALL_READ_ROLES_WITH_GUARDIAN, authorize,
                  guardian_owns, insert, must_exist, resolve, rows)
from envelope import created, listing, ok, parse_pagination
from errors import fail
from store import db, days, iso, new_record, parse_dt, sorted_rows, touch
from validators import Field, get_body, supplied, validate

bp = Blueprint("records", __name__)

SCREENING_TYPES = {"VISION", "HEARING", "SCOLIOSIS"}
REFERRAL_OUTCOMES = {"TREATED", "NO_ACTION", "LOST_TO_FOLLOWUP"}
REQUESTER_TYPES = {"GUARDIAN", "EXTERNAL_PROVIDER", "SCHOOL_STAFF", "AGENCY"}
SCOPE_MEMBERS = {"VISITS", "MEDICATIONS", "SCREENINGS", "ACTION_PLANS"}
PURPOSE_CODES = {"TREATMENT", "ENROLLMENT", "LEGAL", "RESEARCH"}
DISCLOSURE_READ_ROLES = ["DistrictHealthAdmin", "SchoolPhysician", "RecordsOfficer"]


# ---------------------------------------------------------------------------
# Screening
# ---------------------------------------------------------------------------

@bp.post("/health-office/screenings")
def create_screening():
    authorize(["SchoolNurse"])
    body = get_body(request)
    student = resolve("students", body.get("student_id"), "Student")
    school = resolve("schools", body.get("school_id"), "School")
    if student is not None and school is not None and student["school_id"] != school["id"]:
        fail("ERR_RESOURCE_NOT_FOUND", "The student is not enrolled at that building.")
    values = validate(body, [
        Field("student_id", "string"),
        Field("school_id", "string"),
        Field("screening_type", "enum", enum=SCREENING_TYPES),
        Field("scheduled_for", "datetime"),
    ])
    if student["enrollment_status"] != "ENROLLED":
        fail("ERR_STUDENT_NOT_ENROLLED", "The student is not enrolled.")
    record = new_record({
        "student_id": student["id"],
        "school_id": school["id"],
        "screened_by_nurse_id": None,
        "screening_type": values["screening_type"],
        "scheduled_for": parse_dt(values["scheduled_for"]),
        "cycle_number": 1,
        "result_value": None,
        "outcome": None,
        "rescreen_due_at": None,
        "referral_due_at": None,
        "referral_completed_at": None,
        "referral_outcome": None,
        "status": "SCHEDULED",
    })
    insert("screenings", record)
    return created(ser.screening_json(record))


@bp.get("/health-office/screenings/<screening_id>")
def get_screening(screening_id):
    user_id, role = authorize(ALL_READ_ROLES_WITH_GUARDIAN)
    screening = db.screenings.get(screening_id)
    guardian_owns(screening, user_id, role)
    screening = must_exist("screenings", screening_id, "Screening")
    return ok(ser.screening_json(screening))


@bp.get("/health-office/screenings")
def list_screenings():
    authorize(ALL_READ_ROLES)
    limit, offset = parse_pagination(request.args)
    result = rows("screenings")
    for key in ("student_id", "school_id", "screened_by_nurse_id",
                "screening_type", "status"):
        value = request.args.get(key)
        if value:
            result = [r for r in result if r.get(key) == value]
    return listing([ser.screening_json(r) for r in sorted_rows(result)], limit, offset)


@bp.post("/health-office/screenings/<screening_id>/record-result")
def record_screening_result(screening_id):
    authorize(["SchoolNurse"])
    screening = must_exist("screenings", screening_id, "Screening")
    body = get_body(request)
    nurse = resolve("nurses", body.get("screened_by_nurse_id"), "Nurse")
    values = validate(body, [
        Field("result_value", "number"),
        Field("screened_by_nurse_id", "string"),
    ])
    if screening["status"] != "SCHEDULED":
        fail("ERR_SCREENING_INVALID_STATE",
             "Only a SCHEDULED screening may take a result.")
    if not calc.nurse_on_active_coverage(nurse["id"], screening["school_id"],
                                         check_time_of_day=False):
        fail("ERR_NURSE_NOT_ON_COVERAGE",
             "The recording nurse holds no active coverage block at this building.")
    clock = db.now()
    outcome = calc.classify_screening(screening["screening_type"], values["result_value"])
    screening["result_value"] = values["result_value"]
    screening["screened_by_nurse_id"] = nurse["id"]
    screening["outcome"] = outcome
    if outcome == "PASS":
        screening["status"] = "COMPLETED"
    elif outcome == "REFER":
        screening["status"] = "REFERRED"
        screening["referral_due_at"] = clock + days(calc.REFERRAL_DAYS)
    else:
        screening["status"] = "RESCREEN_DUE"
        screening["rescreen_due_at"] = clock + days(calc.RESCREEN_DAYS)
    touch(screening)
    return ok(ser.screening_json(screening))


@bp.post("/health-office/screenings/<screening_id>/follow-up")
def screening_follow_up(screening_id):
    user_id, role = authorize(["SchoolNurse"])
    screening = must_exist("screenings", screening_id, "Screening")
    body = get_body(request)
    values = validate(body, [
        Field("action", "enum", enum={"SCHEDULE_RESCREEN", "CLOSE_REFERRAL"}),
        Field("scheduled_for", "datetime", required=False),
        Field("referral_outcome", "enum", required=False, enum=REFERRAL_OUTCOMES),
    ])
    action = values["action"]
    if action == "SCHEDULE_RESCREEN" and not supplied(values, "scheduled_for"):
        fail("ERR_MISSING_REQUIRED_FIELD", "scheduled_for is required for a rescreen.")
    if action == "CLOSE_REFERRAL" and not supplied(values, "referral_outcome"):
        fail("ERR_MISSING_REQUIRED_FIELD",
             "referral_outcome is required to close a referral.")
    if action == "SCHEDULE_RESCREEN":
        if screening["status"] != "RESCREEN_DUE":
            fail("ERR_SCREENING_INVALID_STATE",
                 "Only a screening awaiting a rescreen may be rebooked.")
        if screening["cycle_number"] >= calc.MAX_SCREENING_CYCLES:
            fail("ERR_RESCREEN_LIMIT_REACHED", "The rescreen round limit is reached.")
        screening["cycle_number"] += 1
        screening["scheduled_for"] = parse_dt(values["scheduled_for"])
        screening["outcome"] = None
        screening["result_value"] = None
        screening["status"] = "SCHEDULED"
        touch(screening)
    else:
        if screening["status"] != "REFERRED":
            fail("ERR_SCREENING_INVALID_STATE",
                 "Only a REFERRED screening may have its referral closed.")
        if user_id == screening.get("screened_by_nurse_id"):
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "The recording nurse may not close their own referral.")
        screening["referral_outcome"] = values["referral_outcome"]
        screening["referral_completed_at"] = db.now()
        screening["status"] = "CLOSED"
        touch(screening)
    return ok(ser.screening_json(screening))


# ---------------------------------------------------------------------------
# DisclosureRequest
# ---------------------------------------------------------------------------

def _recompute_redaction(row):
    student = db.students.get(row["student_id"])
    level = calc.redaction_level(row, student) if student is not None else "NONE"
    row["redaction_level"] = level
    return level


@bp.post("/health-office/disclosure-requests")
def create_disclosure():
    authorize(["RecordsOfficer"])
    body = get_body(request)
    student = resolve("students", body.get("student_id"), "Student")
    values = validate(body, [
        Field("student_id", "string"),
        Field("requester_type", "enum", enum=REQUESTER_TYPES),
        Field("requester_reference", "string"),
        Field("scope", "array", members=SCOPE_MEMBERS, non_empty=True),
        Field("purpose_code", "enum", enum=PURPOSE_CODES),
    ])
    record = new_record({
        "student_id": student["id"],
        "requester_type": values["requester_type"],
        "requester_reference": values["requester_reference"],
        "scope": list(values["scope"]),
        "purpose_code": values["purpose_code"],
        "consent_granted_at": None,
        "expires_at": None,
        "released_at": None,
        "decided_by_user_id": None,
        "released_by_user_id": None,
        "redaction_level": "NONE",
        "release_package_item_count": 0,
        "status": "DRAFT",
    })
    _recompute_redaction(record)
    insert("disclosure_requests", record)
    return created(ser.disclosure_json(record))


@bp.get("/health-office/disclosure-requests/<request_id>")
def get_disclosure(request_id):
    user_id, role = authorize(DISCLOSURE_READ_ROLES + ["Guardian"])
    row = db.disclosure_requests.get(request_id)
    guardian_owns(row, user_id, role)
    row = must_exist("disclosure_requests", request_id, "DisclosureRequest")
    return ok(ser.disclosure_json(row))


@bp.get("/health-office/disclosure-requests")
def list_disclosures():
    authorize(DISCLOSURE_READ_ROLES)
    limit, offset = parse_pagination(request.args)
    result = rows("disclosure_requests")
    for key in ("student_id", "status", "requester_type"):
        value = request.args.get(key)
        if value:
            result = [r for r in result if r.get(key) == value]
    return listing([ser.disclosure_json(r) for r in sorted_rows(result)], limit, offset)


@bp.post("/health-office/disclosure-requests/<request_id>/submit")
def submit_disclosure(request_id):
    authorize(["RecordsOfficer"])
    row = must_exist("disclosure_requests", request_id, "DisclosureRequest")
    if row["status"] != "DRAFT":
        fail("ERR_DISCLOSURE_INVALID_STATE", "Only a DRAFT request may be submitted.")
    row["status"] = "CONSENT_PENDING"
    _recompute_redaction(row)
    touch(row)
    return ok(ser.disclosure_json(row))


@bp.post("/health-office/disclosure-requests/<request_id>/guardian-consent")
def disclosure_guardian_consent(request_id):
    user_id, role = authorize(["Guardian"])
    row = db.disclosure_requests.get(request_id)
    guardian_owns(row, user_id, role)
    row = must_exist("disclosure_requests", request_id, "DisclosureRequest")
    body = get_body(request)
    values = validate(body, [Field("decision", "enum", enum={"GRANT", "WITHDRAW"})])
    decision = values["decision"]
    if decision == "GRANT":
        if row["status"] != "CONSENT_PENDING":
            fail("ERR_DISCLOSURE_INVALID_STATE",
                 "The request is not awaiting guardian consent.")
        clock = db.now()
        row["consent_granted_at"] = clock
        row["expires_at"] = clock + days(calc.CONSENT_VALIDITY_DAYS)
        row["status"] = "AWAITING_DECISION"
    else:
        if row["status"] not in ("CONSENT_PENDING", "AWAITING_DECISION", "APPROVED"):
            fail("ERR_DISCLOSURE_INVALID_STATE", "The request may not be revoked now.")
        row["status"] = "REVOKED"
        row["consent_granted_at"] = None
        row["expires_at"] = None
        row["release_package_item_count"] = 0
    touch(row)
    return ok(ser.disclosure_json(row))


@bp.post("/health-office/disclosure-requests/<request_id>/decide")
def decide_disclosure(request_id):
    user_id, role = authorize(["SchoolPhysician"])
    row = must_exist("disclosure_requests", request_id, "DisclosureRequest")
    body = get_body(request)
    values = validate(body, [
        Field("decision", "enum", enum={"APPROVE", "DENY"}),
        Field("redaction_override", "enum", required=False,
              enum={"NONE", "PARTIAL", "FULL"}),
    ])
    decision = values["decision"]
    if row["status"] != "AWAITING_DECISION":
        fail("ERR_DISCLOSURE_INVALID_STATE", "The request is not awaiting a decision.")
    if decision == "APPROVE":
        level = _recompute_redaction(row)
        if level == "FULL":
            fail("ERR_PRIVACY_HOLD_BLOCKS_RELEASE",
                 "A fully redacted request cannot be approved.")
        expires_at = row.get("expires_at")
        if expires_at is None or not db.now() < expires_at:
            fail("ERR_DISCLOSURE_CONSENT_EXPIRED", "The release consent has expired.")
        if supplied(values, "redaction_override") \
                and values["redaction_override"] == "PARTIAL" and level == "NONE":
            row["redaction_level"] = "PARTIAL"
        row["decided_by_user_id"] = user_id
        row["status"] = "APPROVED"
    else:
        row["decided_by_user_id"] = user_id
        row["status"] = "DENIED"
        row["release_package_item_count"] = 0
    touch(row)
    return ok(ser.disclosure_json(row))


@bp.post("/health-office/disclosure-requests/<request_id>/release")
def release_disclosure(request_id):
    user_id, role = authorize(["RecordsOfficer"])
    row = must_exist("disclosure_requests", request_id, "DisclosureRequest")
    if row["status"] != "APPROVED":
        fail("ERR_DISCLOSURE_INVALID_STATE", "Only an APPROVED request may be released.")
    if user_id == row.get("decided_by_user_id"):
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The releasing operator must differ from the deciding operator.")
    student = db.students.get(row["student_id"])
    stored_level = row["redaction_level"]
    level = calc.redaction_level(row, student) if student is not None else "NONE"
    if stored_level == "PARTIAL" and level == "NONE":
        level = "PARTIAL"          # a tightening override never loosens later
    row["redaction_level"] = level
    if student is not None and student.get("privacy_hold") \
            and row["requester_type"] != "GUARDIAN":
        fail("ERR_PRIVACY_HOLD_BLOCKS_RELEASE", "A privacy hold blocks this release.")
    if level == "FULL":
        fail("ERR_PRIVACY_HOLD_BLOCKS_RELEASE", "A fully redacted package cannot be released.")
    expires_at = row.get("expires_at")
    if expires_at is None or not db.now() < expires_at:
        fail("ERR_DISCLOSURE_CONSENT_EXPIRED", "The release consent has expired.")
    row["release_package_item_count"] = calc.package_item_count(row, student, level)
    row["released_by_user_id"] = user_id
    row["released_at"] = db.now()
    row["status"] = "RELEASED"
    touch(row)
    return ok(ser.disclosure_json(row))

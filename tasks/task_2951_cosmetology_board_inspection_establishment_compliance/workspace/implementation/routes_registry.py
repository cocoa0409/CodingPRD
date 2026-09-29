"""Reference registries, enrolment, training records and licensing actions."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import auth
import derive
import envelope
import store
from errors import fail
from helpers import find, view_practitioner
from validate import (body_of, county_code, d2, fk, opt_enum, opt_instant, opt_str, present,
                      req_date, req_dec, req_enum, req_int, req_str)

registry_bp = Blueprint("registry", __name__)


# ---------------------------------------------------------- violation codes
@registry_bp.post("/violation-codes")
def create_violation_code():
    auth.authenticate(("BoardAdmin",))
    body = body_of(request)
    code = req_str(body, "code")
    category = req_enum(body, "category", derive.VIOLATION_CATEGORIES)
    severity = req_enum(body, "severity", derive.SEVERITIES)
    base_points = req_dec(body, "base_points", gt=0)
    fine_cents_base = req_int(body, "fine_cents_base", minimum=0)
    for existing in store.violation_codes.values():
        if existing["code"] == code:
            fail("ERR_INVALID_REQUEST", "Violation code '%s' is already published." % code)
    row = store.make_row(with_common=False)
    row.update({
        "code": code,
        "category": category,
        "severity": severity,
        "base_points": d2(base_points),
        "fine_cents_base": fine_cents_base,
    })
    store.violation_codes[row["id"]] = row
    return envelope.ok(derive.ser_violation_code(row), 201)


# ------------------------------------------------------------------ schools
@registry_bp.post("/schools")
def create_school():
    auth.authenticate(("BoardAdmin",))
    body = body_of(request)
    name = req_str(body, "name", max_len=200)
    code = county_code(body)
    required = req_dec(body, "required_clock_hours", gt=0)
    accreditation = opt_enum(body, "accreditation_status", derive.ACCREDITATION_STATUSES,
                             default="ACCREDITED")
    approved = body.get("apprenticeship_program_approved", False)
    if approved is None:
        approved = False
    if not isinstance(approved, bool):
        fail("ERR_INVALID_REQUEST", "Field 'apprenticeship_program_approved' must be a boolean.")
    row = store.make_row()
    row.update({
        "name": name,
        "county_code": code,
        "required_clock_hours": d2(required),
        "accreditation_status": accreditation,
        "apprenticeship_program_approved": approved,
    })
    store.schools[row["id"]] = row
    return envelope.ok(derive.ser_school(row), 201)


# ------------------------------------------------------------ practitioners
@registry_bp.post("/practitioners")
def create_practitioner():
    ctx = auth.authenticate(("BoardAdmin", "SchoolRegistrar"))
    body = body_of(request)
    school_id = fk(body, "school_id")
    school = find("School", school_id) if school_id is not None else None
    if ctx.is_registrar and school_id != ctx.user_id:
        auth.deny()
    full_name = req_str(body, "full_name", max_len=200)
    license_type = req_enum(body, "license_type", derive.LICENSE_TYPES)
    row = store.make_row()
    row.update({
        "full_name": full_name,
        "license_type": license_type,
        "school_id": school_id,
        "license_status": "STUDENT",
        "license_expires_on": None,
        "credited_hours_school": Decimal("0.00"),
        "credited_hours_apprentice": Decimal("0.00"),
        "credited_hours_total": Decimal("0.00"),
        "required_clock_hours_effective": (d2(school["required_clock_hours"]) if school
                                          else derive.APPRENTICE_STANDALONE_REQUIRED_HOURS),
        "exam_eligible": False,
        "sanction_points": Decimal("0.00"),
        "suspension_cause_points": None,
    })
    store.practitioners[row["id"]] = row
    return envelope.ok(derive.ser_practitioner(row), 201)


# --------------------------------------------------------- training records
def _check_sponsor(subject, credit_type, school, sponsor):
    """PRD 3.2 sponsor/school eligibility (step 15)."""
    if credit_type == "SCHOOL_CLOCK_HOUR":
        if school["accreditation_status"] == "WITHDRAWN":
            fail("ERR_SPONSOR_NOT_ELIGIBLE", "The named school's accreditation is withdrawn.")
        return
    if sponsor["id"] == subject["id"]:
        fail("ERR_SPONSOR_NOT_ELIGIBLE", "A candidate may not sponsor their own hours.")
    if sponsor["license_type"] not in derive.SPONSOR_LICENSE_TYPES:
        fail("ERR_SPONSOR_NOT_ELIGIBLE", "The sponsor's licence type may not supervise hours.")
    if sponsor["license_status"] != "ACTIVE":
        fail("ERR_SPONSOR_NOT_ELIGIBLE", "The sponsor's licence is not active.")
    if subject["license_type"] == "APPRENTICE":
        backing_id = sponsor["school_id"] if sponsor["school_id"] else subject["school_id"]
        backing = store.schools.get(backing_id) if backing_id else None
        if backing is None or not backing["apprenticeship_program_approved"]:
            fail("ERR_SPONSOR_NOT_ELIGIBLE",
                 "No school approved to sponsor apprenticeship hours backs this record.")


@registry_bp.post("/training-records")
def create_training_record():
    ctx = auth.authenticate(("BoardAdmin", "SchoolRegistrar"))
    body = body_of(request)

    prac_id = fk(body, "practitioner_id")
    subject = find("Practitioner", prac_id) if prac_id is not None else None
    school_id = fk(body, "school_id")
    school = find("School", school_id) if school_id is not None else None
    sponsor_id = fk(body, "sponsor_practitioner_id")
    sponsor = find("Practitioner", sponsor_id) if sponsor_id is not None else None

    if ctx.is_registrar:
        if subject is not None and subject["school_id"] != ctx.user_id:
            auth.deny()
        if school_id is not None and school_id != ctx.user_id:
            auth.deny()

    if subject is None:
        fail("ERR_INVALID_REQUEST", "Field 'practitioner_id' is required.")
    credit_type = req_enum(body, "credit_type", derive.CREDIT_TYPES)
    hours = req_dec(body, "hours", gt=0, le=24)
    performed_on = req_date(body, "performed_on")
    discipline = req_enum(body, "discipline", derive.DISCIPLINES)

    if credit_type == "SCHOOL_CLOCK_HOUR":
        if school_id is None:
            fail("ERR_INVALID_REQUEST", "Field 'school_id' is required for a school-clock record.")
        if sponsor_id is not None:
            fail("ERR_INVALID_REQUEST",
                 "Field 'sponsor_practitioner_id' must be null on a school-clock record.")
    else:
        if sponsor_id is None:
            fail("ERR_INVALID_REQUEST",
                 "Field 'sponsor_practitioner_id' is required for an apprentice record.")
        if school_id is not None:
            fail("ERR_INVALID_REQUEST", "Field 'school_id' must be null on an apprentice record.")

    _check_sponsor(subject, credit_type, school, sponsor)

    row = store.make_row(with_common=False)
    row.update({
        "practitioner_id": subject["id"],
        "credit_type": credit_type,
        "hours": d2(hours),
        "performed_on": performed_on,
        "discipline": discipline,
        "school_id": school_id,
        "sponsor_practitioner_id": sponsor_id,
    })
    store.training_records[row["id"]] = row
    derive.refresh_practitioner(subject, force=True)
    return envelope.ok(derive.ser_training_record(row), 201)


# --------------------------------------------------------- licensing actions
@registry_bp.post("/practitioners/<pid>/license-actions")
def license_action(pid):
    auth.authenticate(("BoardAdmin",))
    prac = find("Practitioner", pid)
    body = body_of(request)
    action = req_enum(body, "action", derive.LICENSE_ACTIONS)
    effective_at = opt_instant(body, "effective_at", default=store.now_utc())
    reason = opt_str(body, "reason")

    if prac["license_status"] not in derive.LICENSE_ACTION_LEGAL_FROM[action]:
        fail("ERR_LICENSE_ACTION_NOT_PERMITTED",
             "Action %s is not permitted from status %s." % (action, prac["license_status"]))

    previous = prac["license_status"]

    if action == "GRANT_EXAM_ELIGIBILITY":
        derive.compute_practitioner(prac)
        if prac["credited_hours_total"] < prac["required_clock_hours_effective"]:
            fail("ERR_EXAM_ELIGIBILITY_REQUIRED",
                 "Credited hours have not reached the effective clock-hour requirement.")
        disciplines = set(t["discipline"] for t in derive.training_records_of(prac["id"]))
        if "SANITATION" not in disciplines or "DISINFECTION" not in disciplines:
            fail("ERR_TRAINING_HOURS_INSUFFICIENT",
                 "Both SANITATION and DISINFECTION hours are required.")
        if prac["school_id"] is not None:
            school = store.schools.get(prac["school_id"])
            if school is None or school["accreditation_status"] != "ACCREDITED":
                fail("ERR_TRAINING_HOURS_INSUFFICIENT",
                     "The candidate's school is not currently accredited.")
        prac["license_status"] = "EXAM_ELIGIBLE"

    elif action == "ISSUE_LICENSE":
        derive.compute_practitioner(prac)
        if not prac["exam_eligible"]:
            fail("ERR_EXAM_ELIGIBILITY_REQUIRED", "The candidate is not exam eligible.")
        prac["license_status"] = "ACTIVE"
        prac["license_expires_on"] = (effective_at + timedelta(days=derive.LICENSE_TERM_DAYS)).date()

    elif action == "PLACE_ON_PROBATION":
        prac["license_status"] = "PROBATION"

    elif action == "SUSPEND":
        prac["license_status"] = "SUSPENDED"
        prac["suspension_cause_points"] = d2(derive.practitioner_sanction_points(prac["id"]))
        derive.practitioner_personnel_cascade(prac["id"], store.now_utc())

    elif action == "REINSTATE":
        prac["license_status"] = "ACTIVE"
        snapshot = prac["suspension_cause_points"]
        if snapshot is not None:
            derive.post_ledger(
                "SANCTION_POINTS", "REINSTATEMENT_SANCTION_REVERSAL",
                delta_points=-d2(snapshot), practitioner_id=prac["id"])
            prac["suspension_cause_points"] = None
        if previous == "LAPSED":
            prac["license_expires_on"] = (
                effective_at + timedelta(days=derive.LICENSE_TERM_DAYS)).date()
            derive.repost_practitioner_stations(prac["id"])

    elif action == "REVOKE":
        prac["license_status"] = "REVOKED"
        derive.practitioner_personnel_cascade(prac["id"], store.now_utc())

    derive.refresh_practitioner(prac, force=True)
    return envelope.ok(derive.ser_practitioner(prac))

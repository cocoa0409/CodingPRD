"""Operational controls, payers, the nurse roster, competencies and patients."""
from flask import Blueprint

import auth
import cascade
import derive
import envelope
import lookup
import serialize
import store
import validate
from errors import fail
from store import db, new_row
from timeutil import fmt_instant

bp = Blueprint("reference", __name__)

PLAN_TYPES = ("MEDICAID_WAIVER", "MEDICAID_MCO", "COMMERCIAL")
BILLING_RULESETS = ("STANDARD_15MIN", "STRICT_15MIN")
LICENSE_TYPES = ("RN", "LPN")
NURSE_STATUSES = ("ACTIVE", "SUSPENDED", "INACTIVE")
COMPETENCY_STATUSES = ("VALID", "EXPIRED", "REVOKED")
PATIENT_STATUSES = ("ACTIVE", "HOSPITALIZED", "DISCHARGED")
CONTINUITY_BASES = ("STRICT", "BROAD")
AUTH_EXPIRABLE = ("ACTIVE", "REDUCTION_NOTICED", "REDUCED")


# --------------------------------------------------------------------------- #
# 1. logical clock
# --------------------------------------------------------------------------- #
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth.require("AgencyAdmin")
    data = validate.body()
    moment = validate.req_instant(data, "to_iso8601")
    db.clock = moment
    return envelope.ok({"current_utc": fmt_instant(moment)})


# --------------------------------------------------------------------------- #
# 2. daily checkpoint
# --------------------------------------------------------------------------- #
@bp.route("/_ops/run-daily-checkpoint", methods=["POST"])
def run_daily_checkpoint():
    auth.require("AgencyAdmin")
    expired_authorizations = 0
    for row in store.ordered(db.authorizations):
        if row["status"] in AUTH_EXPIRABLE and row["effective_end"] <= db.clock:
            cascade.authorization_expiry_cascade(row)
            expired_authorizations += 1
    expired_competencies = 0
    today = db.clock.date()
    for row in store.ordered(db.competencies):
        if row["status"] == "VALID" and row["expires_on"] <= today:
            row["status"] = "EXPIRED"
            cascade.touch(row)
            expired_competencies += 1
    overdue_cases = 0
    for row in store.ordered(db.cases):
        if derive.supervisory_status(row) == "OVERDUE":
            overdue_cases += 1
    cancelled_shifts = 0
    for row in store.ordered(db.shifts):
        if row["staffing_status"] in ("OPEN", "ESCALATED") and row["start_at"] < db.clock:
            cascade.cancel_shift(row, "SCHEDULER")
            cancelled_shifts += 1
    return cascade.respond_data({
        "expired_authorization_count": expired_authorizations,
        "expired_competency_count": expired_competencies,
        "overdue_case_count": overdue_cases,
        "cancelled_shift_count": cancelled_shifts,
    })


# --------------------------------------------------------------------------- #
# 3-4. payers
# --------------------------------------------------------------------------- #
@bp.route("/payers", methods=["POST"])
def create_payer():
    auth.require("AgencyAdmin")
    data = validate.body()
    row = new_row(
        name=validate.req_str(data, "name", maxlen=120),
        plan_type=validate.req_enum(data, "plan_type", PLAN_TYPES),
        weekly_hour_cap=validate.req_int(data, "weekly_hour_cap", lo=1, hi=168),
        evv_required=validate.opt_bool(data, "evv_required", True),
        billing_edit_ruleset=validate.opt_enum(
            data, "billing_edit_ruleset", BILLING_RULESETS, "STANDARD_15MIN"),
        appeal_window_days=validate.opt_int(data, "appeal_window_days", 30, lo=1, hi=90),
        reduction_notice_days=validate.opt_int(data, "reduction_notice_days", 10, lo=1, hi=60),
    )
    db.payers[row["id"]] = row
    return cascade.respond(serialize.payer, row, 201)


@bp.route("/payers/<payer_id>", methods=["GET"])
def read_payer(payer_id):
    auth.require("AgencyAdmin", "PayerReviewer", "CaseManager")
    return envelope.ok(serialize.payer(lookup.get_payer(payer_id)))


# --------------------------------------------------------------------------- #
# 5-8. nurses
# --------------------------------------------------------------------------- #
@bp.route("/nurses", methods=["POST"])
def create_nurse():
    auth.require("AgencyAdmin")
    data = validate.body()
    full_name = validate.req_str(data, "full_name", maxlen=120)
    license_type = validate.req_enum(data, "license_type", LICENSE_TYPES)
    license_number = validate.req_str(data, "license_number", maxlen=32)
    license_expires_on = validate.req_date(data, "license_expires_on")
    max_weekly_hours = validate.opt_int(data, "max_weekly_hours", 40, lo=1, hi=80)
    for other in db.nurses.values():
        if other["license_number"] == license_number:
            fail("ERR_LICENSE_NUMBER_TAKEN", "Licence number %s is already held." % license_number)
    row = new_row(
        full_name=full_name,
        license_type=license_type,
        license_number=license_number,
        license_expires_on=license_expires_on,
        max_weekly_hours=max_weekly_hours,
        status="ACTIVE",
    )
    db.nurses[row["id"]] = row
    return cascade.respond(serialize.nurse, row, 201)


@bp.route("/nurses/<nurse_id>", methods=["GET"])
def read_nurse(nurse_id):
    auth.require("AgencyAdmin", "Scheduler", "ClinicalSupervisor", "Nurse")
    return envelope.ok(serialize.nurse(lookup.get_nurse(nurse_id)))


@bp.route("/nurses", methods=["GET"])
def list_nurses():
    auth.require("AgencyAdmin", "Scheduler")
    limit, offset = validate.pagination()
    status = validate.query_enum("status", NURSE_STATUSES)
    skill = validate.query_enum("skill", validate.SKILLS)
    rows = store.ordered(db.nurses)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if skill is not None:
        rows = [r for r in rows if skill in derive.verified_skills(r["id"])]
    total = len(rows)
    body = [serialize.nurse(r) for r in validate.page(rows, limit, offset)]
    return envelope.ok_list(body, limit, offset, total)


@bp.route("/nurses/<nurse_id>/status", methods=["POST"])
def set_nurse_status(nurse_id):
    auth.require("AgencyAdmin")
    nurse = lookup.get_nurse(nurse_id)
    data = validate.body()
    status = validate.req_enum(data, "status", NURSE_STATUSES)
    was_active = nurse["status"] == "ACTIVE"
    nurse["status"] = status
    cascade.touch(nurse)
    if was_active and status != "ACTIVE":
        cascade.nurse_left_active_cascade(nurse["id"])
    return cascade.respond(serialize.nurse, nurse)


# --------------------------------------------------------------------------- #
# 9-11. competencies
# --------------------------------------------------------------------------- #
@bp.route("/nurses/<nurse_id>/competencies", methods=["POST"])
def create_competency(nurse_id):
    auth.require("ClinicalSupervisor")
    uid, _role = auth.identity()
    nurse = lookup.get_nurse(nurse_id)
    data = validate.body()
    skill = validate.req_enum(data, "skill", validate.SKILLS)
    validated_on = validate.req_date(data, "validated_on")
    expires_on = validate.req_date(data, "expires_on")
    if not expires_on > validated_on:
        validate.bad("Field 'expires_on' must be strictly after 'validated_on'.")
    for other in db.competencies.values():
        if other["nurse_id"] == nurse["id"] and other["skill"] == skill \
                and other["status"] != "REVOKED":
            fail("ERR_COMPETENCY_DUPLICATE",
                 "Nurse already holds a non-revoked %s competency." % skill)
    row = new_row(
        nurse_id=nurse["id"],
        skill=skill,
        validated_by_user_id=uid,
        validated_on=validated_on,
        expires_on=expires_on,
        status="VALID",
        revoked_reason=None,
    )
    db.competencies[row["id"]] = row
    return cascade.respond(serialize.competency, row, 201)


@bp.route("/nurses/<nurse_id>/competencies", methods=["GET"])
def list_competencies(nurse_id):
    auth.require("AgencyAdmin", "Scheduler", "ClinicalSupervisor")
    nurse = lookup.get_nurse(nurse_id)
    limit, offset = validate.pagination()
    status = validate.query_enum("status", COMPETENCY_STATUSES)
    rows = [r for r in store.ordered(db.competencies) if r["nurse_id"] == nurse["id"]]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    total = len(rows)
    body = [serialize.competency(r) for r in validate.page(rows, limit, offset)]
    return envelope.ok_list(body, limit, offset, total)


@bp.route("/nurse-competencies/<competency_id>/revoke", methods=["POST"])
def revoke_competency(competency_id):
    auth.require("ClinicalSupervisor")
    competency = lookup.get_competency(competency_id)
    if competency["status"] == "REVOKED":
        fail("ERR_INVALID_STATE", "Competency is already revoked.")
    data = validate.body()
    reason = validate.req_str(data, "revoked_reason")
    competency["status"] = "REVOKED"
    competency["revoked_reason"] = reason
    cascade.touch(competency)
    cascade.competency_revocation_cascade(competency["nurse_id"], competency["skill"])
    return cascade.respond(serialize.competency, competency)


# --------------------------------------------------------------------------- #
# 12. continuity score
# --------------------------------------------------------------------------- #
@bp.route("/nurses/<nurse_id>/continuity-score", methods=["GET"])
def read_continuity_score(nurse_id):
    auth.require("Scheduler", "ClinicalSupervisor")
    nurse = lookup.get_nurse(nurse_id)
    case_id = validate.query_value("case_id")
    if case_id is None:
        validate.bad("Query parameter 'case_id' is required.")
    case = lookup.get_case(case_id)
    basis = validate.query_enum("basis", CONTINUITY_BASES) or "STRICT"
    matched, score = derive.continuity_score(nurse["id"], case, basis)
    return envelope.ok({
        "nurse_id": nurse["id"],
        "case_id": case["id"],
        "basis": basis,
        "matched_assignment_count": matched,
        "continuity_score": score,
    })


# --------------------------------------------------------------------------- #
# 13-15. patients
# --------------------------------------------------------------------------- #
@bp.route("/patients", methods=["POST"])
def create_patient():
    auth.require("CaseManager")
    data = validate.body()
    payer = lookup.get_payer(validate.req_fk(data, "payer_id"))
    row = new_row(
        payer_id=payer["id"],
        full_name=validate.req_str(data, "full_name", maxlen=120),
        date_of_birth=validate.req_date(data, "date_of_birth"),
        primary_diagnosis=validate.req_str(data, "primary_diagnosis"),
        requires_trach=validate.opt_bool(data, "requires_trach", False),
        requires_vent=validate.opt_bool(data, "requires_vent", False),
        requires_feeding_tube=validate.opt_bool(data, "requires_feeding_tube", False),
        parent_backup_available=validate.opt_bool(data, "parent_backup_available", False),
        status="ACTIVE",
    )
    db.patients[row["id"]] = row
    return cascade.respond(serialize.patient, row, 201)


@bp.route("/patients/<patient_id>", methods=["GET"])
def read_patient(patient_id):
    auth.require("CaseManager", "Scheduler", "ClinicalSupervisor", "PayerReviewer")
    return envelope.ok(serialize.patient(lookup.get_patient(patient_id)))


@bp.route("/patients", methods=["GET"])
def list_patients():
    auth.require("CaseManager", "PayerReviewer")
    limit, offset = validate.pagination()
    payer_id = validate.query_value("payer_id")
    status = validate.query_enum("status", PATIENT_STATUSES)
    rows = store.ordered(db.patients)
    if payer_id is not None:
        rows = [r for r in rows if r["payer_id"] == payer_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    total = len(rows)
    body = [serialize.patient(r) for r in validate.page(rows, limit, offset)]
    return envelope.ok_list(body, limit, offset, total)

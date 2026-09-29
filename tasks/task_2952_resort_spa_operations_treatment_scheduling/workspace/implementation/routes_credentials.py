"""Licensing, continuing education and skill certification (PRD §3.3)."""

from decimal import Decimal

from flask import Blueprint

import auth
import calc
import domain
import envelope
import errors
import store
import validation as v
from errors import ApiError
from store import db, touch

bp = Blueprint("credentials", __name__)

LICENSE_TYPES = ("LMT", "ESTHETICIAN", "NAIL_TECH")
VERIFICATION_STATUSES = ("PENDING_REVIEW", "VERIFIED", "REJECTED", "EXPIRED")
CE_VARIANTS = ("CALENDAR_WINDOW", "ROLLING_24M")
GRANT_STATUSES = ("ACTIVE", "LAPSED", "REVOKED")
SCOPE_LEVELS = ("BASIC", "ADVANCED")
DECISIONS = ("VERIFY", "REJECT", "VERIFIED", "REJECTED")

STATE_PATTERN = r"^[A-Z]{2}$"


# --------------------------------------------------------------------------
# licences
# --------------------------------------------------------------------------

@bp.route("/therapists/<therapist_id>/licenses", methods=["POST"])
def file_license(therapist_id):
    caller = auth.authenticate(auth.COMPLIANCE_OFFICER)
    body = v.json_body()
    license_number = v.field_str(body, "license_number", max_len=64)
    license_type = v.field_enum(body, "license_type", LICENSE_TYPES)
    state_code = v.field_str(body, "state_code", min_len=2, max_len=2,
                             pattern=STATE_PATTERN)
    issued_on = v.field_date(body, "issued_on")
    expires_on = v.field_date(body, "expires_on")
    period_start_on = v.field_date(body, "current_period_start_on")
    ce_required = v.field_decimal_1dp(body, "ce_hours_required", required=False,
                                      default=calc.DEFAULT_CE_HOURS_REQUIRED,
                                      minimum=0)
    if expires_on <= issued_on:
        v.bad("Field 'expires_on' must be strictly after 'issued_on'.")
    if period_start_on > expires_on:
        v.bad("Field 'current_period_start_on' must be on or before 'expires_on'.")

    therapist = domain.find_therapist(therapist_id)
    if state_code != therapist["practice_state_code"]:
        v.bad("Field 'state_code' must equal the therapist's practice_state_code.")

    entity = {}
    store.stamp_common(entity)
    entity.update({
        "therapist_id": therapist["id"],
        "license_number": license_number,
        "license_type": license_type,
        "state_code": state_code,
        "issued_on": issued_on,
        "expires_on": expires_on,
        "current_period_start_on": period_start_on,
        "ce_hours_required": Decimal(ce_required),
        "verification_status": "PENDING_REVIEW",
        "submitted_by_user_id": caller.user_id,
        "reviewed_by_user_id": None,
        "review_note": None,
        "verified_at": None,
        "credited_ce_hours": Decimal("0"),
    })
    db.licenses[entity["id"]] = entity
    return envelope.created(entity)


@bp.route("/therapists/<therapist_id>/licenses", methods=["GET"])
def list_licenses(therapist_id):
    auth.authenticate(auth.COMPLIANCE_OFFICER, auth.SPA_DIRECTOR)
    limit, offset = v.pagination()
    status = v.query_enum("verification_status", VERIFICATION_STATUSES)
    therapist = domain.find_therapist(therapist_id)

    rows = domain.licenses_of(therapist["id"])
    if status is not None:
        rows = [r for r in rows if r["verification_status"] == status]
    return envelope.listing(v.paginate(rows, limit, offset), len(rows), limit, offset)


@bp.route("/therapist-licenses/<license_id>", methods=["GET"])
def read_license(license_id):
    auth.authenticate(auth.COMPLIANCE_OFFICER, auth.SPA_DIRECTOR)
    license_row = domain.find_license(license_id)
    return envelope.ok(license_row)


@bp.route("/therapist-licenses/<license_id>/review", methods=["POST"])
def review_license(license_id):
    caller = auth.authenticate(auth.COMPLIANCE_OFFICER)
    body = v.json_body()
    decision = v.field_enum(body, "decision", DECISIONS)
    review_note = v.field_str(body, "review_note", required=False, default=None,
                              max_len=1000)
    license_row = domain.find_license(license_id)

    if license_row["verification_status"] != "PENDING_REVIEW":
        raise ApiError(errors.ERR_INVALID_LICENSE_STATE,
                       "Only a PENDING_REVIEW licence may be reviewed.")
    if caller.user_id == license_row.get("submitted_by_user_id"):
        raise ApiError(errors.ERR_SEGREGATION_OF_DUTIES,
                       "The submitting officer may not review the same licence.")

    verifying = decision in ("VERIFY", "VERIFIED")
    if not verifying:
        license_row["verification_status"] = "REJECTED"
        license_row["reviewed_by_user_id"] = caller.user_id
        license_row["review_note"] = review_note
        license_row["verified_at"] = None
        touch(license_row)
        return envelope.ok(license_row)

    if license_row["expires_on"] < db.clock.date():
        raise ApiError(errors.ERR_LICENSE_EXPIRED,
                       "The licence has already expired.")
    evaluation = calc.ce_compliance_evaluation(
        license_row, domain.ce_records_of(license_row["id"]), "CALENDAR_WINDOW",
        db.clock.date())
    if evaluation["shortfall_hours"] > 0:
        raise ApiError(errors.ERR_CE_HOURS_INSUFFICIENT,
                       "The licence is short %s continuing-education hours."
                       % evaluation["shortfall_hours"])
    if not evaluation["ethics_requirement_met"]:
        raise ApiError(errors.ERR_CE_ETHICS_REQUIREMENT_UNMET,
                       "The ethics continuing-education minimum is unmet.")

    license_row["verification_status"] = "VERIFIED"
    license_row["reviewed_by_user_id"] = caller.user_id
    license_row["review_note"] = review_note
    license_row["verified_at"] = db.clock
    license_row["credited_ce_hours"] = evaluation["credited_hours"]
    touch(license_row)
    return envelope.ok(license_row)


@bp.route("/therapist-licenses/<license_id>/resubmit", methods=["POST"])
def resubmit_license(license_id):
    caller = auth.authenticate(auth.COMPLIANCE_OFFICER)
    body = v.json_body()
    license_number = v.field_str(body, "license_number", required=False, default=None,
                                 max_len=64)
    expires_on = v.field_date(body, "expires_on", required=False, default=None)
    period_start_on = v.field_date(body, "current_period_start_on", required=False,
                                   default=None)
    ce_required = v.field_decimal_1dp(body, "ce_hours_required", required=False,
                                      default=None, minimum=0)
    license_row = domain.find_license(license_id)

    if license_row["verification_status"] not in ("REJECTED", "EXPIRED"):
        raise ApiError(errors.ERR_INVALID_LICENSE_STATE,
                       "Only a REJECTED or EXPIRED licence may be resubmitted.")

    if license_number is not None:
        license_row["license_number"] = license_number
    if expires_on is not None:
        license_row["expires_on"] = expires_on
    if period_start_on is not None:
        license_row["current_period_start_on"] = period_start_on
    if ce_required is not None:
        license_row["ce_hours_required"] = Decimal(ce_required)

    license_row["verification_status"] = "PENDING_REVIEW"
    license_row["submitted_by_user_id"] = caller.user_id
    license_row["reviewed_by_user_id"] = None
    license_row["review_note"] = None
    license_row["verified_at"] = None
    touch(license_row)
    return envelope.ok(license_row)


# --------------------------------------------------------------------------
# continuing-education records
# --------------------------------------------------------------------------

@bp.route("/therapist-licenses/<license_id>/ce-records", methods=["POST"])
def create_ce_record(license_id):
    caller = auth.authenticate(auth.COMPLIANCE_OFFICER)
    body = v.json_body()
    course_code = v.field_str(body, "course_code", max_len=64)
    category = v.field_enum(body, "category", calc.CE_CATEGORIES)
    ce_hours = v.field_decimal_1dp(body, "ce_hours", exclusive_minimum=0, maximum=8)
    completed_on = v.field_date(body, "completed_on")
    license_row = domain.find_license(license_id)

    entity = {}
    store.stamp_common(entity, versioned=False)
    entity.update({
        "license_id": license_row["id"],
        "course_code": course_code,
        "category": category,
        "ce_hours": Decimal(ce_hours),
        "completed_on": completed_on,
        "recorded_by_user_id": caller.user_id,
    })
    db.ce_records[entity["id"]] = entity
    return envelope.created(entity)


@bp.route("/therapist-licenses/<license_id>/ce-records", methods=["GET"])
def list_ce_records(license_id):
    auth.authenticate(auth.COMPLIANCE_OFFICER, auth.SPA_DIRECTOR)
    limit, offset = v.pagination()
    category = v.query_enum("category", calc.CE_CATEGORIES)
    license_row = domain.find_license(license_id)

    rows = domain.ce_records_of(license_row["id"])
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    return envelope.listing(v.paginate(rows, limit, offset), len(rows), limit, offset)


@bp.route("/therapist-licenses/<license_id>/ce-compliance", methods=["GET"])
def read_ce_compliance(license_id):
    auth.authenticate(auth.COMPLIANCE_OFFICER, auth.SPA_DIRECTOR)
    variant = v.query_enum("variant", CE_VARIANTS, default="CALENDAR_WINDOW")
    as_of = v.query_date("as_of")
    license_row = domain.find_license(license_id)

    if as_of is None:
        as_of = db.clock.date()
    evaluation = calc.ce_compliance_evaluation(
        license_row, domain.ce_records_of(license_row["id"]), variant, as_of)
    return envelope.ok(evaluation)


# --------------------------------------------------------------------------
# certification grants
# --------------------------------------------------------------------------

@bp.route("/therapists/<therapist_id>/certifications", methods=["POST"])
def grant_certification(therapist_id):
    auth.authenticate(auth.COMPLIANCE_OFFICER)
    body = v.json_body()
    skill_code = v.field_str(body, "skill_code", max_len=32, upper=True)
    scope_level = v.field_enum(body, "scope_level", SCOPE_LEVELS)
    granted_on = v.field_date(body, "granted_on")
    expires_on = v.field_date(body, "expires_on")
    if expires_on <= granted_on:
        v.bad("Field 'expires_on' must be strictly after 'granted_on'.")
    therapist = domain.find_therapist(therapist_id)

    entity = {}
    store.stamp_common(entity)
    entity.update({
        "therapist_id": therapist["id"],
        "skill_code": skill_code,
        "scope_level": scope_level,
        "granted_on": granted_on,
        "expires_on": expires_on,
        "status": "ACTIVE",
        "revoked_by_user_id": None,
    })
    db.certifications[entity["id"]] = entity
    return envelope.created(entity)


@bp.route("/therapists/<therapist_id>/certifications", methods=["GET"])
def list_certifications(therapist_id):
    auth.authenticate(auth.COMPLIANCE_OFFICER, auth.SPA_DIRECTOR, auth.SPA_COORDINATOR)
    limit, offset = v.pagination()
    status = v.query_enum("status", GRANT_STATUSES)
    therapist = domain.find_therapist(therapist_id)

    rows = domain.certifications_of(therapist["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return envelope.listing(v.paginate(rows, limit, offset), len(rows), limit, offset)


@bp.route("/certifications/<certification_id>/revoke", methods=["POST"])
def revoke_certification(certification_id):
    caller = auth.authenticate(auth.COMPLIANCE_OFFICER)
    body = v.json_body()
    v.field_str(body, "reason_note", required=False, default=None, max_len=500)
    grant = domain.find_certification(certification_id)

    grant["status"] = "REVOKED"
    grant["revoked_by_user_id"] = caller.user_id
    touch(grant)
    return envelope.ok(grant)

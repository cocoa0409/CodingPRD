"""Permits, effluent limit derivation, annual reporting and producers."""
from flask import Blueprint, g

from auth import require
from calc import derive_limits, reconcile, refresh_applicable_limit
from common import collection_response, filtered, one, resolve, touched
from errors import ApiError
from store import ZERO2, db, new_row, q2, q4, touch
from validation import enum_arg, int_arg, spec, str_arg, validate_body

bp = Blueprint("permits", __name__)

LIMIT_STATUSES = ("DRAFT_LIMITS", "INTERIM", "FINAL")
COMPLIANCE_STATUSES = ("NOT_REPORTED", "IN_COMPLIANCE", "SHORTFALL", "RESOLVED", "VIOLATION")
PERMIT_READ_ROLES = (
    "ProgramAdministrator",
    "TmdlAnalyst",
    "PermitWriter",
    "Permittee",
    "RegistryAdministrator",
)


# --------------------------------------------------------------------------
# producers
# --------------------------------------------------------------------------
@bp.route("/producers", methods=["POST"])
def create_producer():
    require("ProgramAdministrator", "RegistryAdministrator")
    body = validate_body(
        [
            spec("legal_name", "string"),
            spec("county_code", "string"),
            spec("contact_email", "string"),
        ]
    )
    row = new_row(
        "Producer",
        legal_name=body["legal_name"],
        county_code=body["county_code"],
        contact_email=body["contact_email"],
    )
    db.producers[row["id"]] = row
    return one(row, 201)


@bp.route("/producers/<producer_id>", methods=["GET"])
def get_producer(producer_id):
    require("ProgramAdministrator", "RegistryAdministrator", "PracticeVerifier", "Producer")
    return one(resolve(db.producers, "producer_id", producer_id))


# --------------------------------------------------------------------------
# permits
# --------------------------------------------------------------------------
@bp.route("/permits", methods=["POST"])
def create_permit():
    require("PermitWriter")
    body = validate_body(
        [
            spec("watershed_id", "id"),
            spec("source_assessment_id", "id"),
            spec("permit_number", "string"),
            spec("permittee_user_id", "string"),
            spec("design_flow_mgd", "number", minimum=0, min_exclusive=True, dp=4),
            spec("effective_date", "date"),
            spec("current_annual_load_lbs", "number", minimum=0, dp=2),
        ]
    )
    watershed = resolve(db.watersheds, "watershed_id", body["watershed_id"])
    source = resolve(db.source_assessments, "source_assessment_id", body["source_assessment_id"])
    assessment = db.tmdl_assessments.get(source["tmdl_assessment_id"])
    if assessment is None or assessment["watershed_id"] != watershed["id"]:
        raise ApiError("ERR_WATERSHED_MISMATCH")
    for existing in db.permits.values():
        if existing["permit_number"] == body["permit_number"]:
            raise ApiError("ERR_DUPLICATE_CODE")
    if source["source_type"] != "POINT":
        raise ApiError("ERR_SOURCE_NOT_POINT")

    row = new_row(
        "Permit",
        watershed_id=watershed["id"],
        source_assessment_id=source["id"],
        permit_number=body["permit_number"],
        permittee_user_id=body["permittee_user_id"],
        design_flow_mgd=q4(body["design_flow_mgd"]),
        effective_date=body["effective_date"],
        current_annual_load_lbs=q2(body["current_annual_load_lbs"]),
        limit_status="DRAFT_LIMITS",
        compliance_status="NOT_REPORTED",
        wla_lbs_yr=None,
        final_limit_lbs_yr=None,
        interim_limit_lbs_yr=None,
        required_reduction_pct=None,
        schedule_tier=None,
        compliance_schedule_end_date=None,
        applicable_limit_lbs_yr=None,
        reported_annual_load_lbs=None,
        reporting_period_year=None,
        credit_applied_lbs=ZERO2,
        compliance_gap_lbs=ZERO2,
        enforcement_flag=False,
    )
    db.permits[row["id"]] = row
    return one(row, 201)


@bp.route("/permits/<permit_id>", methods=["GET"])
def get_permit(permit_id):
    require(*PERMIT_READ_ROLES)
    return one(resolve(db.permits, "permit_id", permit_id))


@bp.route("/permits", methods=["GET"])
def list_permits():
    require(*PERMIT_READ_ROLES)
    filters = {
        "watershed_id": str_arg("watershed_id"),
        "source_assessment_id": str_arg("source_assessment_id"),
        "limit_status": enum_arg("limit_status", LIMIT_STATUSES),
        "compliance_status": enum_arg("compliance_status", COMPLIANCE_STATUSES),
    }
    return collection_response(filtered(db.permits, filters))


@bp.route("/permits/<permit_id>/derive-limits", methods=["POST"])
def permit_derive_limits(permit_id):
    require("PermitWriter")
    permit = resolve(db.permits, "permit_id", permit_id)
    if permit["limit_status"] != "DRAFT_LIMITS":
        raise ApiError("ERR_INVALID_STATE")
    source = db.source_assessments.get(permit["source_assessment_id"])
    if source is None or source.get("allocated_load_lbs_yr") is None:
        raise ApiError("ERR_WLA_NOT_ALLOCATED")
    watershed = db.watersheds.get(permit["watershed_id"])
    derive_limits(permit, source, watershed, touched())
    return one(permit)


@bp.route("/permits/<permit_id>/finalize-limits", methods=["POST"])
def permit_finalize_limits(permit_id):
    require("PermitWriter")
    permit = resolve(db.permits, "permit_id", permit_id)
    if permit["limit_status"] != "INTERIM":
        raise ApiError("ERR_INVALID_STATE")
    source = db.source_assessments.get(permit["source_assessment_id"])
    assessment = db.tmdl_assessments.get(source["tmdl_assessment_id"]) if source else None
    if assessment is None or assessment["status"] != "APPROVED":
        raise ApiError("ERR_TMDL_NOT_APPROVED")

    permit["limit_status"] = "FINAL"
    refresh_applicable_limit(permit)
    touch(permit, touched())
    if permit.get("reported_annual_load_lbs") is not None:
        reconcile(permit, "finalize", touched())
    return one(permit)


@bp.route("/permits/<permit_id>/annual-report", methods=["POST"])
def permit_annual_report(permit_id):
    require("Permittee")
    permit = resolve(db.permits, "permit_id", permit_id)
    body = validate_body(
        [
            spec("reported_annual_load_lbs", "number", minimum=0, dp=2),
            spec("reporting_period_year", "int"),
        ]
    )
    if permit["permittee_user_id"] != g.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if permit["limit_status"] not in ("INTERIM", "FINAL"):
        raise ApiError("ERR_LIMITS_NOT_DERIVED")

    permit["reported_annual_load_lbs"] = q2(body["reported_annual_load_lbs"])
    permit["reporting_period_year"] = body["reporting_period_year"]
    reconcile(permit, "report", touched())
    return one(permit)

"""Funders, programs and grants: building the funding landscape."""

from flask import Blueprint

import clock
import db
from common import resolve_grant, resolve_program
from errors import ApiError
from response import (
    array_envelope,
    auth_context,
    body,
    object_envelope,
    page,
    pagination_args,
    require_fields,
    require_role,
)
from services import posture

bp = Blueprint("foundation", __name__)

FUNDER_TYPES = ("FEDERAL", "STATE", "COUNTY", "PRIVATE_FOUNDATION", "DIOCESAN", "PARISH")
SERVICE_DOMAINS = ("HOUSING", "FOOD", "COUNSELING", "IMMIGRATION", "REFUGEE")
COST_BASES = ("DIRECT_ONLY", "HEADCOUNT", "TIME_AND_EFFORT", "SQUARE_FOOTAGE")
RESTRICTED_PURPOSES = (
    "HOUSING_ASSISTANCE", "FOOD_DISTRIBUTION", "CLINICAL_COUNSELING",
    "LEGAL_IMMIGRATION", "REFUGEE_RESETTLEMENT", "GENERAL_OPERATING",
)
ALL_ROLES = ("IntakeSpecialist", "ProgramManager", "FinanceOfficer", "ComplianceOfficer")


@bp.post("/funders")
def create_funder():
    auth_context()
    require_role(_role(), ("ComplianceOfficer",))
    payload = body()
    require_fields(payload, ("name", "funder_type", "max_admin_rate_pct",
                             "fiscal_year_start_month"))
    if payload["funder_type"] not in FUNDER_TYPES:
        raise ApiError("ERR_BAD_REQUEST", "funder_type is not a declared category.")
    funder = db.create("funders", {
        "name": payload["name"],
        "funder_type": payload["funder_type"],
        "allow_faith_based_activity": bool(payload.get("allow_faith_based_activity", False)),
        "requires_time_and_effort_documentation": bool(
            payload.get("requires_time_and_effort_documentation", False)),
        "max_admin_rate_pct": float(payload["max_admin_rate_pct"]),
        "fiscal_year_start_month": int(payload["fiscal_year_start_month"]),
        "status": "ACTIVE",
    })
    return object_envelope(db.public(funder)), 201


@bp.post("/programs")
def create_program():
    auth_context()
    require_role(_role(), ("ComplianceOfficer",))
    payload = body()
    require_fields(payload, ("name", "service_domain", "capacity_slots"))
    if payload["service_domain"] not in SERVICE_DOMAINS:
        raise ApiError("ERR_BAD_REQUEST", "service_domain is not a declared domain.")
    program = db.create("programs", {
        "name": payload["name"],
        "service_domain": payload["service_domain"],
        "faith_based_activity_offered": bool(payload.get("faith_based_activity_offered", False)),
        "nondiscrimination_attested": bool(payload.get("nondiscrimination_attested", False)),
        "capacity_slots": int(payload["capacity_slots"]),
        "enrolled_slots": 0,
        "active_slots": 0,
        "match_eligible": bool(payload.get("match_eligible", False)),
        "status": "ACTIVE",
    })
    return object_envelope(db.public(program)), 201


def _role():
    from flask import request
    return request.headers.get("X-User-Role")


@bp.post("/grants")
def create_grant():
    auth_context()
    require_role(_role(), ("FinanceOfficer",))
    payload = body()
    require_fields(payload, ("funder_id", "program_id", "grant_code", "total_award_cents",
                             "admin_rate_pct", "allocation_rank", "cost_allocation_basis",
                             "restricted_purpose", "period_start", "period_end"))
    funder = db.get("funders", payload["funder_id"])
    if funder is None:
        raise ApiError("ERR_GRANT_NOT_FOUND", "The funder_id does not resolve to a Funder row.")
    program = resolve_program(payload["program_id"])
    if funder.get("allow_faith_based_activity") is False \
            and program.get("faith_based_activity_offered") is True:
        raise ApiError(
            "ERR_FAITH_BASED_ACTIVITY_PROHIBITED",
            "Funder %s does not permit public funds to support an explicitly "
            "religious activity component." % funder.get("name"),
        )
    if payload["cost_allocation_basis"] not in COST_BASES:
        raise ApiError("ERR_BAD_REQUEST", "cost_allocation_basis is not a declared basis.")
    if payload["restricted_purpose"] not in RESTRICTED_PURPOSES:
        raise ApiError("ERR_BAD_REQUEST", "restricted_purpose is not a declared purpose.")
    if float(payload["admin_rate_pct"]) > float(funder.get("max_admin_rate_pct", 0)):
        raise ApiError(
            "ERR_ADMIN_RATE_EXCEEDED",
            "admin_rate_pct exceeds the governing funder's max_admin_rate_pct.",
        )
    grant = db.create("grants", {
        "funder_id": funder["id"],
        "program_id": program["id"],
        "grant_code": payload["grant_code"],
        "total_award_cents": int(payload["total_award_cents"]),
        "expended_cents": 0,
        "obligated_cents": 0,
        "admin_rate_pct": float(payload["admin_rate_pct"]),
        "allocation_rank": int(payload["allocation_rank"]),
        "max_in_kind_rate_cents": int(payload.get("max_in_kind_rate_cents", 0)),
        "matching_requirement_pct": float(payload.get("matching_requirement_pct", 0)),
        "cost_allocation_basis": payload["cost_allocation_basis"],
        "restricted_purpose": payload["restricted_purpose"],
        "period_start": clock.parse(payload["period_start"]),
        "period_end": clock.parse(payload["period_end"]),
        "burn_ratio": 0.0,
        "status": "OPEN",
        "posture_computed_at": clock.now(),
    })
    posture.initialize(grant)
    return object_envelope(db.public(grant)), 201


@bp.get("/grants")
def list_grants():
    auth_context()
    require_role(_role(), ALL_ROLES)
    limit, offset = pagination_args()
    from flask import request
    matches = [
        grant for grant in db.ordered("grants")
        if _match(grant, "funder_id", request.args.get("funder_id"))
        and _match(grant, "program_id", request.args.get("program_id"))
        and _match(grant, "status", request.args.get("status"))
    ]
    rows = [db.public(grant) for grant in page(matches, limit, offset)]
    return object_envelope_list(rows, limit, offset, len(matches))


@bp.get("/grants/<grant_id>")
def read_grant(grant_id):
    auth_context()
    require_role(_role(), ALL_ROLES)
    grant = resolve_grant(grant_id)
    data = db.public(grant)
    data["cash_burn_ratio"] = posture.cash_burn_ratio(grant)
    data["child_counts"] = {
        "outcome_reports": len([
            row for row in db.rows("outcome_reports") if row.get("grant_id") == grant["id"]
        ]),
        "in_kind_donations": len([
            row for row in db.rows("in_kind_donations") if row.get("grant_id") == grant["id"]
        ]),
    }
    return object_envelope(data)


@bp.get("/grants/<grant_id>/outcome-reports")
def list_grant_outcome_reports(grant_id):
    auth_context()
    require_role(_role(), ("ProgramManager", "ComplianceOfficer"))
    grant = resolve_grant(grant_id)
    limit, offset = pagination_args()
    from flask import request
    matches = [
        row for row in db.ordered("outcome_reports")
        if row.get("grant_id") == grant["id"]
        and _match(row, "measure_code", request.args.get("measure_code"))
        and _match(row, "status", request.args.get("status"))
    ]
    rows = [db.public(row) for row in page(matches, limit, offset)]
    return object_envelope_list(rows, limit, offset, len(matches))


@bp.get("/grants/<grant_id>/in-kind-donations")
def list_grant_in_kind(grant_id):
    auth_context()
    require_role(_role(), ("ProgramManager", "FinanceOfficer", "ComplianceOfficer"))
    grant = resolve_grant(grant_id)
    limit, offset = pagination_args()
    from flask import request
    matches = [
        row for row in db.ordered("in_kind_donations")
        if row.get("grant_id") == grant["id"]
        and _match(row, "donor_type", request.args.get("donor_type"))
        and _match(row, "status", request.args.get("status"))
    ]
    rows = [db.public(row) for row in page(matches, limit, offset)]
    return object_envelope_list(rows, limit, offset, len(matches))


@bp.post("/grants/<grant_id>/posture-recompute")
def recompute_posture(grant_id):
    auth_context()
    require_role(_role(), ("FinanceOfficer", "ComplianceOfficer"))
    grant = resolve_grant(grant_id)
    posture.recompute(grant)
    return object_envelope(db.public(grant))


def _match(row, field, value):
    if value is None:
        return True
    return row.get(field) == value


def object_envelope_list(rows, limit, offset, total):
    return array_envelope(rows, limit, offset, total)

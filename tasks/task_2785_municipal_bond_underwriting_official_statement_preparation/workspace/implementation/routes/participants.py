"""Issuers and firms (PRD 3.1)."""
from flask import Blueprint

import db
import lookup
import response
import serializers
from errors import ApiError
from middleware import ALL_ROLES, authenticate
from services import calc
from validation import parse_body, query_bool, query_value, sorted_rows, spec

bp = Blueprint("participants", __name__)

ENTITY_TYPES = ["CITY", "COUNTY", "SCHOOL_DISTRICT", "AUTHORITY", "STATE"]
FIRM_TYPES = ["UNDERWRITER", "MUNICIPAL_ADVISOR", "DUAL_REGISTERED"]

ISSUER_SPECS = [
    spec("name", "string", min_len=1, max_len=160),
    spec("state_code", "string", min_len=2, max_len=2, pattern=r"^[A-Z]{2}$"),
    spec("entity_type", "enum", values=ENTITY_TYPES),
    spec("prior_late_annual_filings", "integer", required=False, default=0, minimum=0, maximum=20),
    spec("prior_late_event_notices", "integer", required=False, default=0, minimum=0, maximum=20),
    spec("has_prior_material_event", "boolean", required=False, default=False),
    spec("is_bank_qualified_eligible", "boolean", required=False, default=False),
]

FIRM_SPECS = [
    spec("name", "string", min_len=1, max_len=160),
    spec("firm_type", "enum", values=FIRM_TYPES),
    spec("msrb_registration_id", "string", min_len=6, max_len=6, pattern=r"^[A-Z0-9]{6}$"),
    spec("is_suspended", "boolean", required=False, default=False),
]


@bp.route("/bond-offerings/issuers", methods=["POST"])
def create_issuer():
    authenticate(["IssuerOfficial", "MunicipalAdvisor", "ComplianceOfficer"])
    body = parse_body(ISSUER_SPECS)
    row = db.new_row(
        name=body["name"],
        state_code=body["state_code"],
        entity_type=body["entity_type"],
        prior_late_annual_filings=body["prior_late_annual_filings"],
        prior_late_event_notices=body["prior_late_event_notices"],
        has_prior_material_event=body["has_prior_material_event"],
        is_bank_qualified_eligible=body["is_bank_qualified_eligible"],
    )
    row["disclosure_risk_score"] = calc.issuer_disclosure_risk_score(
        row["entity_type"],
        row["prior_late_annual_filings"],
        row["prior_late_event_notices"],
        row["has_prior_material_event"],
    )
    db.db.issuers[row["id"]] = row
    return response.created(serializers.issuer(row))


@bp.route("/bond-offerings/issuers", methods=["GET"])
def list_issuers():
    authenticate(ALL_ROLES)
    rows = sorted_rows(list(db.db.issuers.values()))
    state_code = query_value("state_code")
    if state_code is not None:
        rows = [row for row in rows if row["state_code"] == state_code]
    entity_type = query_value("entity_type")
    if entity_type is not None:
        rows = [row for row in rows if row["entity_type"] == entity_type]
    return response.paginated(rows, serializers.issuer)


@bp.route("/bond-offerings/issuers/<issuer_id>", methods=["GET"])
def read_issuer(issuer_id):
    authenticate(ALL_ROLES)
    row = lookup.get_issuer(issuer_id)
    return response.ok(serializers.issuer(row))


@bp.route("/bond-offerings/firms", methods=["POST"])
def create_firm():
    authenticate(["ComplianceOfficer"])
    body = parse_body(FIRM_SPECS)
    for existing in db.db.firms.values():
        if existing["msrb_registration_id"] == body["msrb_registration_id"]:
            raise ApiError("ERR_DUPLICATE_MSRB_REGISTRATION")
    row = db.new_row(
        name=body["name"],
        firm_type=body["firm_type"],
        msrb_registration_id=body["msrb_registration_id"],
        is_suspended=body["is_suspended"],
    )
    db.db.firms[row["id"]] = row
    return response.created(serializers.firm(row))


@bp.route("/bond-offerings/firms", methods=["GET"])
def list_firms():
    authenticate(["IssuerOfficial", "MunicipalAdvisor", "Underwriter", "ComplianceOfficer"])
    rows = sorted_rows(list(db.db.firms.values()))
    firm_type = query_value("firm_type")
    if firm_type is not None:
        rows = [row for row in rows if row["firm_type"] == firm_type]
    suspended = query_bool("is_suspended")
    if suspended is not None:
        rows = [row for row in rows if row["is_suspended"] == suspended]
    return response.paginated(rows, serializers.firm)


@bp.route("/bond-offerings/firms/<firm_id>", methods=["GET"])
def read_firm(firm_id):
    authenticate(["IssuerOfficial", "MunicipalAdvisor", "Underwriter", "ComplianceOfficer"])
    row = lookup.get_firm(firm_id)
    return response.ok(serializers.firm(row))


@bp.route("/bond-offerings/firms/<firm_id>/syndicate-memberships", methods=["GET"])
def list_firm_memberships(firm_id):
    authenticate(["Underwriter", "MunicipalAdvisor", "ComplianceOfficer"])
    lookup.get_firm(firm_id)
    rows = sorted_rows([row for row in db.db.members.values() if row["firm_id"] == firm_id])
    status = query_value("status")
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    return response.paginated(rows, serializers.member)

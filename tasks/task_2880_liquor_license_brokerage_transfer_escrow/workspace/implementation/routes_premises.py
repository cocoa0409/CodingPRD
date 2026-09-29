"""Candidate premises, zoning verification and landlord consent (PRD 3.2)."""

from flask import Blueprint

import calc
from authz import (BROKER, BUYER, ESCROW_OFFICER, PLATFORM_ADMIN, REGULATOR,
                   authenticate, buyer_or_404, county_or_404, premises_or_404)
from envelope import apply_filters, created, ok, ok_list, pagination_args, paginate
from store import bump, db, make_record, public, public_list, sorted_by_created
from validation import F, json_body, validate

bp = Blueprint("premises", __name__)

CUP_STATUSES = ("NOT_REQUIRED", "REQUIRED_NOT_FILED", "PENDING", "GRANTED", "DENIED")
CONSENT_STATUSES = ("NOT_REQUIRED", "PENDING", "GRANTED", "REFUSED")


@bp.route("/premises", methods=["POST"])
def create_premises():
    authenticate((BROKER, BUYER))
    data = validate(json_body(), [
        F("buyer_id", "string"),
        F("county_id", "string"),
        F("address_line", "string"),
        F("zoning_code", "string"),
        F("distance_to_nearest_school_feet", "integer", minimum=0),
        F("distance_to_nearest_church_feet", "integer", minimum=0),
        F("census_tract_undue_concentration", "boolean", required=False, default=False),
    ])
    buyer = buyer_or_404(data["buyer_id"])
    county = county_or_404(data["county_id"])
    premises = make_record({
        "buyer_id": buyer["id"],
        "county_id": county["id"],
        "address_line": data["address_line"],
        "zoning_code": data["zoning_code"],
        "distance_to_nearest_school_feet": data["distance_to_nearest_school_feet"],
        "distance_to_nearest_church_feet": data["distance_to_nearest_church_feet"],
        "census_tract_undue_concentration": data["census_tract_undue_concentration"],
        "conditional_use_permit_status": "REQUIRED_NOT_FILED",
        "landlord_consent_status": "PENDING",
        "consent_document_ref": None,
        "suitability_status": None,
        "suitability_reason_code": None,
    })
    calc.apply_suitability(premises, county)
    db.premises[premises["id"]] = premises
    return created(public(premises))


@bp.route("/premises/<premises_id>", methods=["GET"])
def get_premises(premises_id):
    authenticate((PLATFORM_ADMIN, BROKER, BUYER, REGULATOR, ESCROW_OFFICER))
    return ok(public(premises_or_404(premises_id)))


@bp.route("/premises", methods=["GET"])
def list_premises():
    authenticate((PLATFORM_ADMIN, BROKER, BUYER, REGULATOR, ESCROW_OFFICER))
    limit, offset = pagination_args()
    rows = apply_filters(db.premises.values(), {
        "buyer_id": "buyer_id",
        "county_id": "county_id",
        "suitability_status": "suitability_status",
    })
    rows = sorted_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


@bp.route("/premises/<premises_id>/zoning-verification", methods=["POST"])
def zoning_verification(premises_id):
    authenticate((REGULATOR,))
    data = validate(json_body(), [
        F("conditional_use_permit_status", "enum", values=CUP_STATUSES),
        F("zoning_code", "string", required=False, default=None),
        F("distance_to_nearest_school_feet", "integer", required=False, default=None, minimum=0),
        F("distance_to_nearest_church_feet", "integer", required=False, default=None, minimum=0),
        F("census_tract_undue_concentration", "boolean", required=False, default=None),
    ])
    premises = premises_or_404(premises_id)
    county = county_or_404(premises["county_id"])
    premises["conditional_use_permit_status"] = data["conditional_use_permit_status"]
    for field in ("zoning_code", "distance_to_nearest_school_feet",
                  "distance_to_nearest_church_feet", "census_tract_undue_concentration"):
        if data[field] is not None:
            premises[field] = data[field]
    calc.apply_suitability(premises, county)
    bump(premises)
    return ok(public(premises))


@bp.route("/premises/<premises_id>/landlord-consent", methods=["POST"])
def landlord_consent(premises_id):
    authenticate((BROKER, BUYER))
    data = validate(json_body(), [
        F("landlord_consent_status", "enum", values=CONSENT_STATUSES),
        F("consent_document_ref", "string", required=False, default=None),
    ])
    premises = premises_or_404(premises_id)
    county = county_or_404(premises["county_id"])
    premises["landlord_consent_status"] = data["landlord_consent_status"]
    if data["consent_document_ref"] is not None:
        premises["consent_document_ref"] = data["consent_document_ref"]
    calc.apply_suitability(premises, county)
    bump(premises)
    return ok(public(premises))

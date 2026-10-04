"""The single door: client registration, reads and intake-assessment opening."""

from flask import Blueprint

import clock
import db
from common import resolve_client
from errors import ApiError
from response import (
    auth_context,
    body,
    object_envelope,
    require_fields,
    require_role,
)
from services import capacity, confidentiality, intake

bp = Blueprint("clients", __name__)

IMMIGRATION_STATUSES = ("CITIZEN", "LPR", "REFUGEE", "ASYLEE", "UNDOCUMENTED", "PENDING_ASYLUM")
CONFIDENTIALITY_TIERS = ("STANDARD", "PROTECTED", "SEALED")
SERVICE_DOMAINS = ("HOUSING", "FOOD", "COUNSELING", "IMMIGRATION", "REFUGEE")


@bp.post("/clients")
def create_client():
    auth_context()
    require_role(_role(), ("IntakeSpecialist",))
    payload = body()
    require_fields(payload, ("full_name", "date_of_birth", "household_size",
                             "immigration_status", "county_code"))
    if payload["immigration_status"] not in IMMIGRATION_STATUSES:
        raise ApiError("ERR_BAD_REQUEST", "immigration_status is not a declared category.")
    tier = payload.get("confidentiality_tier") or "STANDARD"
    if tier not in CONFIDENTIALITY_TIERS:
        raise ApiError("ERR_BAD_REQUEST", "confidentiality_tier is not a declared tier.")
    scope = payload.get("consent_scope") or []
    for domain in scope:
        if domain not in SERVICE_DOMAINS:
            raise ApiError("ERR_BAD_REQUEST", "consent_scope carries an undeclared domain.")
    expires = payload.get("consent_expires_on")
    client = db.create("clients", {
        "full_name": payload["full_name"],
        "date_of_birth": payload["date_of_birth"],
        "household_size": int(payload["household_size"]),
        "immigration_status": payload["immigration_status"],
        "county_code": payload["county_code"],
        "confidentiality_tier": tier,
        "consent_scope": list(scope),
        "consent_expires_on": clock.parse(expires) if expires else None,
        "open_enrollment_count": 0,
        "shareable_domains": [],
    })
    return object_envelope(db.public(client)), 201


@bp.get("/clients/<client_id>")
def read_client(client_id):
    user_id, role = auth_context()
    require_role(role, ("IntakeSpecialist", "ComplianceOfficer", "Client"))
    if role == "Client" and user_id != client_id:
        raise ApiError(
            "ERR_FORBIDDEN_ROLE",
            "A client may read only their own record.",
        )
    client = resolve_client(client_id)
    confidentiality.assert_client_readable(client)
    capacity.recompute_client(client)
    data = db.public(client)
    data["shareable_domains"] = confidentiality.shareable_domains(client)
    client["shareable_domains"] = data["shareable_domains"]
    return object_envelope(data)


@bp.post("/clients/<client_id>/intake-assessments")
def open_assessment(client_id):
    user_id, role = auth_context()
    require_role(role, ("IntakeSpecialist",))
    client = resolve_client(client_id)
    payload = body()
    require_fields(payload, ("assessment_date", "presenting_needs", "requested_domains"))
    if not payload["presenting_needs"] or not payload["requested_domains"]:
        raise ApiError(
            "ERR_BAD_REQUEST",
            "presenting_needs and requested_domains must each carry at least one element.",
        )
    assessment = db.create("intake_assessments", {
        "client_id": client["id"],
        "assessment_date": clock.parse(payload["assessment_date"]),
        "presenting_needs": list(payload["presenting_needs"]),
        "requested_domains": list(payload["requested_domains"]),
        "assessed_by_user_id": user_id,
        "routing_outcome": "PENDING",
        "return_reason_code": None,
        "status": "DRAFT",
    })
    return object_envelope(db.public(assessment)), 201


def _role():
    from flask import request
    return request.headers.get("X-User-Role")

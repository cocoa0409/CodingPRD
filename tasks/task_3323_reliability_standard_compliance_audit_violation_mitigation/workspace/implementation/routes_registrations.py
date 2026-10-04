"""RegisteredEntity endpoints: create/list/get/patch."""
from __future__ import annotations

from flask import Blueprint, request

from db import db
from errors import err_invalid_request, err_not_found
from helpers import (
    FUNCTION_CODES, new_common, parse_pagination, serialize, sort_and_page, touch,
)
from middleware import require_roles
from response import success_list, success_object
from services import recompute_applicable

bp = Blueprint("registrations", __name__)

READ_ROLES = (
    "RegistrationCoordinator", "ComplianceAuditor", "RegionalEntityReviewer",
    "FederalReviewer", "EntityComplianceOfficer", "CIPAssetManager",
)


def _validate_functions(value):
    if not isinstance(value, list) or not value:
        raise err_invalid_request("registration_functions must be a non-empty array")
    for code in value:
        if not isinstance(code, str) or code not in FUNCTION_CODES:
            raise err_invalid_request(f"unrecognized function code: {code!r}")


@bp.post("/registrations")
def create_registration():
    require_roles("RegistrationCoordinator")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("request body must be a JSON object")
    legal_name = body.get("legal_name")
    if not isinstance(legal_name, str) or not legal_name:
        raise err_invalid_request("legal_name is required")
    functions = body.get("registration_functions")
    _validate_functions(functions)
    enrollment = body.get("enrollment_self_logging", False)
    if not isinstance(enrollment, bool):
        raise err_invalid_request("enrollment_self_logging must be a boolean")

    row = new_common()
    row.update({
        "legal_name": legal_name,
        "registration_functions": list(functions),
        "enrollment_self_logging": enrollment,
        "compliance_status": "ACTIVE",
        "open_violation_count": 0,
        "unresolved_appeal_count": 0,
    })
    recompute_applicable(row)
    db.registered_entities[row["id"]] = row
    return success_object(serialize(row), status=201)


@bp.get("/registrations")
def list_registrations():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    rows = list(db.registered_entities.values())
    status = request.args.get("compliance_status")
    if status is not None:
        rows = [r for r in rows if r["compliance_status"] == status]
    page, total = sort_and_page(rows, limit, offset)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.get("/registrations/<entityId>")
def get_registration(entityId):
    require_roles(*READ_ROLES)
    row = db.registered_entities.get(entityId)
    if row is None:
        raise err_not_found("RegisteredEntity not found")
    return success_object(serialize(row))


@bp.patch("/registrations/<entityId>")
def patch_registration(entityId):
    require_roles("RegistrationCoordinator")
    row = db.registered_entities.get(entityId)
    if row is None:
        raise err_not_found("RegisteredEntity not found")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("request body must be a JSON object")
    if "registration_functions" in body:
        _validate_functions(body["registration_functions"])
        row["registration_functions"] = list(body["registration_functions"])
    if "enrollment_self_logging" in body:
        if not isinstance(body["enrollment_self_logging"], bool):
            raise err_invalid_request("enrollment_self_logging must be a boolean")
        row["enrollment_self_logging"] = body["enrollment_self_logging"]
    # PATCH always recomputes applicability, even if only enrollment changed
    recompute_applicable(row)
    touch(row)
    return success_object(serialize(row))

"""SelfReport endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from db import db
from errors import (
    err_entity_restricted, err_forbidden, err_invalid_request, err_invalid_state,
    err_not_found, err_standard_not_applicable,
)
from helpers import (
    clock_now, entity_has_standard, new_common, parse_dt, parse_pagination,
    serialize, sort_and_page, touch,
)
from middleware import require_roles
from response import success_list, success_object

bp = Blueprint("self_reports", __name__)

READ_ROLES = (
    "ComplianceAuditor", "RegionalEntityReviewer", "FederalReviewer",
    "EntityComplianceOfficer",
)


@bp.post("/self-reports")
def create_self_report():
    user_id, _ = require_roles("EntityComplianceOfficer")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("request body must be a JSON object")

    entity_id = body.get("entity_id")
    if not isinstance(entity_id, str):
        raise err_invalid_request("entity_id is required")
    entity = db.registered_entities.get(entity_id)
    if entity is None:
        raise err_not_found("RegisteredEntity not found")

    # posture gate (priority 4)
    if entity["compliance_status"] == "RESTRICTED":
        raise err_entity_restricted()

    standard_id = body.get("standard_id")
    if not isinstance(standard_id, str):
        raise err_invalid_request("standard_id is required")
    description = body.get("description")
    if not isinstance(description, str) or not description:
        raise err_invalid_request("description is required")
    occurred_at = parse_dt(body.get("occurred_at"), "occurred_at")

    # occurred_at must not lie in the future of the logical clock
    if occurred_at > clock_now():
        from errors import err_invalid_interval
        raise err_invalid_interval("occurred_at must not be in the future")

    # ownership (priority 13)
    if entity_id != user_id:
        raise err_forbidden()

    # standard applicability (priority 14)
    if not entity_has_standard(entity, standard_id):
        raise err_standard_not_applicable()

    row = new_common()
    row.update({
        "entity_id": entity_id,
        "standard_id": standard_id,
        "description": description,
        "occurred_at": occurred_at,
        "status": "RECEIVED",
    })
    db.self_reports[row["id"]] = row
    return success_object(serialize(row), status=201)


@bp.get("/self-reports")
def list_self_reports():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    rows = list(db.self_reports.values())
    entity_id = request.args.get("entity_id")
    if entity_id is not None:
        rows = [r for r in rows if r["entity_id"] == entity_id]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = sort_and_page(rows, limit, offset)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.get("/self-reports/<selfReportId>")
def get_self_report(selfReportId):
    require_roles(*READ_ROLES)
    row = db.self_reports.get(selfReportId)
    if row is None:
        raise err_not_found("SelfReport not found")
    return success_object(serialize(row))


def _transition(selfReportId, expected_from, to):
    require_roles("ComplianceAuditor")
    row = db.self_reports.get(selfReportId)
    if row is None:
        raise err_not_found("SelfReport not found")
    if row["status"] != expected_from:
        raise err_invalid_state(f"self-report is not {expected_from}")
    row["status"] = to
    touch(row)
    return success_object(serialize(row))


@bp.post("/self-reports/<selfReportId>/triage")
def triage_self_report(selfReportId):
    return _transition(selfReportId, "RECEIVED", "TRIAGED")


@bp.post("/self-reports/<selfReportId>/confirm")
def confirm_self_report(selfReportId):
    return _transition(selfReportId, "TRIAGED", "CONFIRMED")


@bp.post("/self-reports/<selfReportId>/dismiss")
def dismiss_self_report(selfReportId):
    return _transition(selfReportId, "TRIAGED", "DISMISSED")

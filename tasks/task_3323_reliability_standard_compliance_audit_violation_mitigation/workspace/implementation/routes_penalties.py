"""Penalty endpoints."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (
    err_forbidden, err_invalid_request, err_not_found,
    err_penalty_already_resolved, err_penalty_not_confirmed, err_sod,
)
from helpers import (
    clock_now, new_common, parse_pagination, serialize, sort_and_page, touch,
)
from middleware import require_roles
from response import success_list, success_object
from services import compute_penalty, restriction_check

bp = Blueprint("penalties", __name__)

READ_ROLES = (
    "ComplianceAuditor", "RegionalEntityReviewer", "FederalReviewer",
    "EntityComplianceOfficer",
)


@bp.post("/penalties")
def create_penalty():
    require_roles("ComplianceAuditor")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("request body must be a JSON object")
    violation_id = body.get("violation_id")
    if not isinstance(violation_id, str):
        raise err_invalid_request("violation_id is required")
    violation = db.violations.get(violation_id)
    if violation is None:
        raise err_not_found("Violation not found")

    existing = None
    for p in db.penalties.values():
        if p["violation_id"] == violation_id:
            existing = p
            break

    if existing is None:
        base, factor, amount = compute_penalty(violation)
        now = clock_now()
        row = new_common()
        row.update({
            "violation_id": violation_id,
            "base_amount": base,
            "adjustment_factor": factor,
            "amount": violation.get("proposed_penalty") if violation.get("proposed_penalty") is not None else amount,
            "issued_at": now,
            "due_date": now + timedelta(days=30),
            "status": "ASSESSED",
        })
        db.penalties[row["id"]] = row
        return success_object(serialize(row), status=201)
    return success_object(serialize(existing), status=201)


@bp.get("/penalties")
def list_penalties():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    rows = list(db.penalties.values())
    violation_id = request.args.get("violation_id")
    if violation_id is not None:
        rows = [r for r in rows if r["violation_id"] == violation_id]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = sort_and_page(rows, limit, offset)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.get("/penalties/<penaltyId>")
def get_penalty(penaltyId):
    require_roles(*READ_ROLES)
    row = db.penalties.get(penaltyId)
    if row is None:
        raise err_not_found("Penalty not found")
    return success_object(serialize(row))


@bp.post("/penalties/<penaltyId>/confirm")
def confirm_penalty(penaltyId):
    user_id, _ = require_roles("ComplianceAuditor")
    row = db.penalties.get(penaltyId)
    if row is None:
        raise err_not_found("Penalty not found")
    if row["status"] != "ASSESSED":
        raise err_penalty_already_resolved()
    violation = db.violations.get(row["violation_id"])
    if violation is not None and violation.get("created_by") == user_id:
        raise err_sod("the violation creator may not confirm its penalty")
    row["status"] = "CONFIRMED"
    touch(row)
    # restriction checkpoint
    if violation is not None:
        entity = db.registered_entities.get(violation["entity_id"])
        if entity is not None:
            restriction_check(entity)
    return success_object(serialize(row))


@bp.post("/penalties/<penaltyId>/settle")
def settle_penalty(penaltyId):
    user_id, _ = require_roles("EntityComplianceOfficer")
    row = db.penalties.get(penaltyId)
    if row is None:
        raise err_not_found("Penalty not found")
    violation = db.violations.get(row["violation_id"])
    if row["status"] != "CONFIRMED":
        raise err_penalty_not_confirmed()
    # ownership: caller must be the entity owning the violation
    if violation is not None and violation["entity_id"] != user_id:
        raise err_forbidden()
    row["status"] = "SETTLED"
    touch(row)
    if violation is not None:
        entity = db.registered_entities.get(violation["entity_id"])
        if entity is not None:
            restriction_check(entity)
    return success_object(serialize(row))


@bp.post("/penalties/<penaltyId>/waive")
def waive_penalty(penaltyId):
    require_roles("FederalReviewer")
    row = db.penalties.get(penaltyId)
    if row is None:
        raise err_not_found("Penalty not found")
    if row["status"] != "CONFIRMED":
        raise err_penalty_not_confirmed()
    row["status"] = "WAIVED"
    touch(row)
    violation = db.violations.get(row["violation_id"])
    if violation is not None:
        entity = db.registered_entities.get(violation["entity_id"])
        if entity is not None:
            restriction_check(entity)
    return success_object(serialize(row))

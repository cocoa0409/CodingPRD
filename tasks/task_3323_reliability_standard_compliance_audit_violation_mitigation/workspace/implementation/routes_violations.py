"""Violation endpoints: create (direct), list, get."""
from __future__ import annotations

from flask import Blueprint, request

from db import db
from errors import (
    err_invalid_interval, err_invalid_request, err_not_found,
    err_standard_not_applicable, err_violation_source_invalid,
)
from helpers import (
    entity_has_standard, new_common, parse_dt, parse_pagination, serialize,
    sort_and_page, touch,
)
from middleware import require_roles
from response import success_list, success_object
from services import compute_penalty, recompute_open_violation_count

bp = Blueprint("violations", __name__)

READ_ROLES = (
    "ComplianceAuditor", "RegionalEntityReviewer", "FederalReviewer",
    "EntityComplianceOfficer",
)

SOURCE_TYPES = {"AUDIT", "SPOT_CHECK", "SELF_REPORT", "SELF_LOG"}
VRF_VALUES = {"MINIMAL", "MODERATE", "SERIOUS"}
SEVERITY_VALUES = {"LOWER", "MODERATE", "HIGH", "SEVERE"}


def create_violation_record(
    entity_id, standard_id, source_type, violation_start, violation_end,
    violation_risk_factor, severity_level, created_by,
    source_engagement_id=None, source_self_report_id=None,
):
    """Shared violation-creation path (direct endpoint + self-log escalation).

    Returns (violation_row, entered_open: bool). When the violation is
    self-logging qualified it is created atomically DISMISSED and never enters
    open_violation_count.
    """
    entity = db.registered_entities[entity_id]
    qualified = (
        source_type == "SELF_LOG"
        and violation_risk_factor == "MINIMAL"
        and severity_level == "LOWER"
    )

    row = new_common()
    row.update({
        "entity_id": entity_id,
        "standard_id": standard_id,
        "source_type": source_type,
        "source_engagement_id": source_engagement_id,
        "source_self_report_id": source_self_report_id,
        "violation_start": violation_start,
        "violation_end": violation_end,
        "violation_risk_factor": violation_risk_factor,
        "severity_level": severity_level,
        "status": "OPEN",
        "final_penalty": None,
        "is_self_logging_qualified": qualified,
        "opened_at": row["created_at"],  # transition-to-OPEN time (appeal window anchor)
        "created_by": created_by,
    })
    db.violations[row["id"]] = row

    if qualified:
        # atomically OPEN -> DISMISSED; never counted open; no proposed penalty
        row["proposed_penalty"] = None
        row["status"] = "DISMISSED"
        return row, False

    base, factor, amount = compute_penalty(row)
    row["proposed_penalty"] = amount
    recompute_open_violation_count(entity)
    touch(entity)
    return row, True


@bp.post("/violations")
def create_violation():
    user_id, _ = require_roles("ComplianceAuditor")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("request body must be a JSON object")

    entity_id = body.get("entity_id")
    if not isinstance(entity_id, str):
        raise err_invalid_request("entity_id is required")
    entity = db.registered_entities.get(entity_id)
    if entity is None:
        raise err_not_found("RegisteredEntity not found")

    standard_id = body.get("standard_id")
    if not isinstance(standard_id, str):
        raise err_invalid_request("standard_id is required")
    source_type = body.get("source_type")
    if source_type not in SOURCE_TYPES:
        raise err_invalid_request("invalid source_type")
    if source_type == "SELF_LOG":
        # SELF_LOG violations arise only via the self-log review path
        raise err_violation_source_invalid("SELF_LOG violations are created only via self-log review escalation")

    violation_start = parse_dt(body.get("violation_start"), "violation_start")
    violation_end = parse_dt(body.get("violation_end"), "violation_end")
    vrf = body.get("violation_risk_factor")
    if vrf not in VRF_VALUES:
        raise err_invalid_request("invalid violation_risk_factor")
    severity = body.get("severity_level")
    if severity not in SEVERITY_VALUES:
        raise err_invalid_request("invalid severity_level")

    if violation_end <= violation_start:
        raise err_invalid_interval("violation_end must be strictly after violation_start")

    # standard applicability
    if not entity_has_standard(entity, standard_id):
        raise err_standard_not_applicable()

    # source integrity
    source_engagement_id = body.get("source_engagement_id")
    source_self_report_id = body.get("source_self_report_id")
    if source_type in ("AUDIT", "SPOT_CHECK"):
        if not source_engagement_id or not isinstance(source_engagement_id, str):
            raise err_violation_source_invalid("source_engagement_id is required for AUDIT/SPOT_CHECK")
        eng = db.engagements.get(source_engagement_id)
        if eng is None:
            raise err_not_found("Engagement not found")
        if eng["engagement_type"] != source_type or eng["status"] != "COMPLETED":
            raise err_violation_source_invalid("engagement must be COMPLETED and of matching type")
    elif source_type == "SELF_REPORT":
        if not source_self_report_id or not isinstance(source_self_report_id, str):
            raise err_violation_source_invalid("source_self_report_id is required for SELF_REPORT")
        sr = db.self_reports.get(source_self_report_id)
        if sr is None:
            raise err_not_found("SelfReport not found")
        if sr["status"] != "CONFIRMED":
            raise err_violation_source_invalid("self-report must be CONFIRMED")

    row, _ = create_violation_record(
        entity_id=entity_id,
        standard_id=standard_id,
        source_type=source_type,
        violation_start=violation_start,
        violation_end=violation_end,
        violation_risk_factor=vrf,
        severity_level=severity,
        created_by=user_id,
        source_engagement_id=source_engagement_id,
        source_self_report_id=source_self_report_id,
    )
    return success_object(serialize(row), status=201)


@bp.get("/violations")
def list_violations():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    rows = list(db.violations.values())
    entity_id = request.args.get("entity_id")
    if entity_id is not None:
        rows = [r for r in rows if r["entity_id"] == entity_id]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    seid = request.args.get("source_engagement_id")
    if seid is not None:
        rows = [r for r in rows if r.get("source_engagement_id") == seid]
    srid = request.args.get("source_self_report_id")
    if srid is not None:
        rows = [r for r in rows if r.get("source_self_report_id") == srid]
    page, total = sort_and_page(rows, limit, offset)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.get("/violations/<violationId>")
def get_violation(violationId):
    require_roles(*READ_ROLES)
    row = db.violations.get(violationId)
    if row is None:
        raise err_not_found("Violation not found")
    return success_object(serialize(row))

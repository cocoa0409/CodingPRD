"""Mitigation plan, milestone, and complete-mitigation endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from db import db
from errors import (
    err_entity_restricted, err_forbidden, err_invalid_interval,
    err_invalid_request, err_milestones_incomplete, err_mitigation_plan_exists,
    err_not_found, err_plan_state, err_sod, err_stale_version, err_violation_state,
)
from helpers import (
    clock_now, new_common, parse_dt, parse_pagination, serialize, sort_and_page,
    touch,
)
from middleware import require_roles
from response import success_list, success_object
from services import close_violation

bp = Blueprint("mitigation", __name__)

READ_ROLES = (
    "ComplianceAuditor", "RegionalEntityReviewer", "FederalReviewer",
    "EntityComplianceOfficer",
)


def _plan_for_violation(violation_id):
    for p in db.mitigation_plans.values():
        if p["violation_id"] == violation_id:
            return p
    return None


@bp.post("/violations/<violationId>/mitigation-plans")
def create_mitigation_plan(violationId):
    user_id, _ = require_roles("EntityComplianceOfficer")
    violation = db.violations.get(violationId)
    if violation is None:
        raise err_not_found("Violation not found")
    entity = db.registered_entities.get(violation["entity_id"])

    # posture gate (priority 4)
    if entity is not None and entity["compliance_status"] == "RESTRICTED":
        raise err_entity_restricted()

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("request body must be a JSON object")
    description = body.get("description")
    if not isinstance(description, str) or not description:
        raise err_invalid_request("description is required")
    expected = body.get("expected_violation_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err_invalid_request("expected_violation_version is required and must be an integer")

    # OCC (priority 5)
    if expected != violation["version"]:
        raise err_stale_version()

    # state precondition (priority 24)
    if violation["status"] != "OPEN":
        raise err_violation_state("violation must be OPEN to submit a mitigation plan")

    # ownership (priority 13)
    if violation["entity_id"] != user_id:
        raise err_forbidden()

    # one plan per violation (priority 16)
    if _plan_for_violation(violationId) is not None:
        raise err_mitigation_plan_exists()

    now = clock_now()
    row = new_common()
    row.update({
        "violation_id": violationId,
        "description": description,
        "submitted_at": now,
        "status": "SUBMITTED",  # DRAFT -> SUBMITTED immediately
        "submitted_by": user_id,
    })
    db.mitigation_plans[row["id"]] = row

    violation["status"] = "MITIGATION_SUBMITTED"
    touch(violation)
    return success_object(serialize(row), status=201)


@bp.get("/mitigation-plans")
def list_plans():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    rows = list(db.mitigation_plans.values())
    violation_id = request.args.get("violation_id")
    if violation_id is not None:
        rows = [r for r in rows if r["violation_id"] == violation_id]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = sort_and_page(rows, limit, offset)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.get("/mitigation-plans/<planId>")
def get_plan(planId):
    require_roles(*READ_ROLES)
    row = db.mitigation_plans.get(planId)
    if row is None:
        raise err_not_found("MitigationPlan not found")
    return success_object(serialize(row))


@bp.post("/mitigation-plans/<planId>/approve")
def approve_plan(planId):
    user_id, _ = require_roles("ComplianceAuditor")
    row = db.mitigation_plans.get(planId)
    if row is None:
        raise err_not_found("MitigationPlan not found")
    if row["status"] != "SUBMITTED":
        raise err_plan_state("plan must be SUBMITTED to approve")
    if row.get("submitted_by") == user_id:
        raise err_sod("the plan submitter may not approve it")
    row["status"] = "APPROVED"
    touch(row)
    violation = db.violations[row["violation_id"]]
    if violation["status"] == "MITIGATION_SUBMITTED":
        violation["status"] = "MITIGATION_IN_PROGRESS"
        touch(violation)
    return success_object(serialize(row))


@bp.post("/mitigation-plans/<planId>/reject")
def reject_plan(planId):
    require_roles("ComplianceAuditor")
    row = db.mitigation_plans.get(planId)
    if row is None:
        raise err_not_found("MitigationPlan not found")
    if row["status"] not in ("SUBMITTED", "APPROVED"):
        raise err_plan_state("plan must be SUBMITTED or APPROVED to reject")
    row["status"] = "REJECTED"
    touch(row)
    # violation stays where it is (MITIGATION_SUBMITTED or MITIGATION_IN_PROGRESS)
    return success_object(serialize(row))


@bp.post("/mitigation-plans/<planId>/resubmit")
def resubmit_plan(planId):
    require_roles("EntityComplianceOfficer")
    row = db.mitigation_plans.get(planId)
    if row is None:
        raise err_not_found("MitigationPlan not found")
    if row["status"] != "REJECTED":
        raise err_plan_state("plan must be REJECTED to resubmit")
    body = request.get_json(silent=True)
    if isinstance(body, dict) and "description" in body:
        if not isinstance(body["description"], str) or not body["description"]:
            raise err_invalid_request("description must be a non-empty string")
        row["description"] = body["description"]
    row["status"] = "SUBMITTED"
    row["submitted_at"] = clock_now()
    touch(row)
    return success_object(serialize(row))


@bp.post("/mitigation-plans/<planId>/verify")
def verify_plan(planId):
    user_id, _ = require_roles("ComplianceAuditor")
    row = db.mitigation_plans.get(planId)
    if row is None:
        raise err_not_found("MitigationPlan not found")
    violation = db.violations.get(row["violation_id"])
    if row["status"] != "APPROVED":
        raise err_plan_state("plan must be APPROVED to verify")
    if violation is None or violation["status"] != "MITIGATION_COMPLETE":
        raise err_violation_state("violation must be MITIGATION_COMPLETE to verify")
    if row.get("submitted_by") == user_id:
        raise err_sod("the plan submitter may not verify it")
    row["status"] = "VERIFIED"
    touch(row)
    close_violation(violation)
    return success_object(serialize(row))


# ---------------------------------------------------------------------------
# Milestones
# ---------------------------------------------------------------------------

@bp.post("/mitigation-plans/<planId>/milestones")
def create_milestone(planId):
    require_roles("EntityComplianceOfficer")
    plan = db.mitigation_plans.get(planId)
    if plan is None:
        raise err_not_found("MitigationPlan not found")
    if plan["status"] != "APPROVED":
        raise err_plan_state("milestones may be added only while the plan is APPROVED")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("request body must be a JSON object")
    title = body.get("title")
    if not isinstance(title, str) or not title:
        raise err_invalid_request("title is required")
    due_date = parse_dt(body.get("due_date"), "due_date")
    if due_date <= clock_now():
        raise err_invalid_interval("due_date must be strictly in the future")

    row = new_common()
    row.update({
        "plan_id": planId,
        "title": title,
        "due_date": due_date,
        "completed_at": None,
        "status": "PENDING",
    })
    db.milestones[row["id"]] = row
    return success_object(serialize(row), status=201)


@bp.get("/mitigation-plans/<planId>/milestones")
def list_milestones(planId):
    require_roles(*READ_ROLES)
    plan = db.mitigation_plans.get(planId)
    if plan is None:
        raise err_not_found("MitigationPlan not found")
    limit, offset = parse_pagination(request.args)
    rows = [m for m in db.milestones.values() if m["plan_id"] == planId]
    page, total = sort_and_page(rows, limit, offset)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.get("/milestones/<milestoneId>")
def get_milestone(milestoneId):
    require_roles(*READ_ROLES)
    row = db.milestones.get(milestoneId)
    if row is None:
        raise err_not_found("Milestone not found")
    return success_object(serialize(row))


@bp.post("/milestones/<milestoneId>/complete")
def complete_milestone(milestoneId):
    require_roles("EntityComplianceOfficer")
    row = db.milestones.get(milestoneId)
    if row is None:
        raise err_not_found("Milestone not found")
    plan = db.mitigation_plans.get(row["plan_id"])
    if plan is None or plan["status"] != "APPROVED":
        raise err_plan_state("milestone completion requires the plan to be APPROVED")
    if row["status"] not in ("PENDING", "MISSED"):
        from errors import err_invalid_state
        raise err_invalid_state("milestone is not PENDING or MISSED")
    row["status"] = "COMPLETED"
    row["completed_at"] = clock_now()
    touch(row)
    return success_object(serialize(row))


# ---------------------------------------------------------------------------
# complete-mitigation
# ---------------------------------------------------------------------------

@bp.post("/violations/<violationId>/complete-mitigation")
def complete_mitigation(violationId):
    user_id, _ = require_roles("EntityComplianceOfficer")
    violation = db.violations.get(violationId)
    if violation is None:
        raise err_not_found("Violation not found")
    if violation["status"] != "MITIGATION_IN_PROGRESS":
        raise err_violation_state("violation must be MITIGATION_IN_PROGRESS")
    if violation["entity_id"] != user_id:
        raise err_forbidden()
    plan = _plan_for_violation(violationId)
    if plan is not None:
        outstanding = [
            m for m in db.milestones.values()
            if m["plan_id"] == plan["id"] and m["status"] != "COMPLETED"
        ]
        if outstanding:
            raise err_milestones_incomplete()
    violation["status"] = "MITIGATION_COMPLETE"
    touch(violation)
    return success_object(serialize(violation))

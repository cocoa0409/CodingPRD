"""Appeal endpoints: file, grant/deny (two-level), federal review request."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (
    err_appeal_window_expired, err_duplicate_active_appeal, err_entity_restricted,
    err_forbidden, err_invalid_request, err_invalid_state, err_not_found,
    err_stale_version, err_unauthorized, err_violation_state,
)
from helpers import (
    APPEAL_WINDOW_DAYS, FEDERAL_REVIEW_WINDOW_DAYS, clock_now, new_common,
    parse_pagination, serialize, sort_and_page, touch,
)
from middleware import require_roles
from response import success_list, success_object
from services import close_violation, recompute_unresolved_appeal_count

bp = Blueprint("appeals", __name__)

READ_ROLES = (
    "ComplianceAuditor", "RegionalEntityReviewer", "FederalReviewer",
    "EntityComplianceOfficer",
)

APPEALABLE_STATUSES = {"OPEN", "MITIGATION_SUBMITTED", "MITIGATION_IN_PROGRESS"}
ACTIVE_APPEAL_STATUSES = {"APPEAL_PENDING_REVIEW", "FEDERAL_REVIEW_REQUESTED"}


@bp.post("/violations/<violationId>/appeals")
def file_appeal(violationId):
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
    grounds = body.get("grounds")
    if not isinstance(grounds, str) or not grounds:
        raise err_invalid_request("grounds is required")
    expected = body.get("expected_violation_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err_invalid_request("expected_violation_version is required and must be an integer")

    # OCC (priority 5)
    if expected != violation["version"]:
        raise err_stale_version()

    # state precondition (priority 24)
    if violation["status"] not in APPEALABLE_STATUSES:
        raise err_violation_state("violation is not in an appealable state")

    # appeal window (priority 11)
    opened_at = violation.get("opened_at") or violation["created_at"]
    if clock_now() > opened_at + timedelta(days=APPEAL_WINDOW_DAYS):
        raise err_appeal_window_expired()

    # ownership (priority 13)
    if violation["entity_id"] != user_id:
        raise err_forbidden()

    # no second active appeal (priority 22)
    for a in db.appeals.values():
        if a["violation_id"] == violationId and a["status"] in ACTIVE_APPEAL_STATUSES:
            raise err_duplicate_active_appeal()

    row = new_common()
    row.update({
        "violation_id": violationId,
        "grounds": grounds,
        "submitted_at": clock_now(),
        "status": "APPEAL_PENDING_REVIEW",
        "denied_at": None,
    })
    db.appeals[row["id"]] = row

    violation["status"] = "APPEALED"
    touch(violation)

    if entity is not None:
        entity["unresolved_appeal_count"] = entity.get("unresolved_appeal_count", 0) + 1
        touch(entity)

    return success_object(serialize(row), status=201)


@bp.get("/appeals")
def list_appeals():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    rows = list(db.appeals.values())
    violation_id = request.args.get("violation_id")
    if violation_id is not None:
        rows = [r for r in rows if r["violation_id"] == violation_id]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = sort_and_page(rows, limit, offset)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.get("/appeals/<appealId>")
def get_appeal(appealId):
    require_roles(*READ_ROLES)
    row = db.appeals.get(appealId)
    if row is None:
        raise err_not_found("Appeal not found")
    return success_object(serialize(row))


def _plan_posture_for_violation(violation_id):
    """Return the status a denied violation returns to, based on its plan."""
    for p in db.mitigation_plans.values():
        if p["violation_id"] == violation_id:
            if p["status"] == "APPROVED":
                return "MITIGATION_IN_PROGRESS"
            if p["status"] in ("SUBMITTED", "REJECTED"):
                return "MITIGATION_SUBMITTED"
            return "OPEN"
    return "OPEN"


def _adjudicate(appealId, decision):
    user_id, role = require_roles("RegionalEntityReviewer", "FederalReviewer")
    appeal = db.appeals.get(appealId)
    if appeal is None:
        raise err_not_found("Appeal not found")

    # appeal-level scoping is an authorization rule (§2.1)
    if appeal["status"] == "APPEAL_PENDING_REVIEW":
        if role != "RegionalEntityReviewer":
            raise err_unauthorized("only RegionalEntityReviewer may decide a pending appeal")
    elif appeal["status"] == "FEDERAL_REVIEW_REQUESTED":
        if role != "FederalReviewer":
            raise err_unauthorized("only FederalReviewer may decide a federal-review appeal")
    else:
        raise err_invalid_state("appeal is not in a decidable state")

    violation = db.violations[appeal["violation_id"]]
    entity = db.registered_entities.get(violation["entity_id"])

    if decision == "APPEAL_GRANTED":
        appeal["status"] = "APPEAL_GRANTED"
        touch(appeal)
        # violation APPEALED -> CLOSED with full cascade
        close_violation(violation)
        if entity is not None:
            entity["unresolved_appeal_count"] = max(0, entity.get("unresolved_appeal_count", 0) - 1)
            touch(entity)
    else:  # APPEAL_DENIED
        appeal["status"] = "APPEAL_DENIED"
        appeal["denied_at"] = clock_now()
        touch(appeal)
        # violation returns to its pre-appeal posture per plan state
        target = _plan_posture_for_violation(violation["id"])
        violation["status"] = target
        touch(violation)
        if entity is not None:
            entity["unresolved_appeal_count"] = max(0, entity.get("unresolved_appeal_count", 0) - 1)
            touch(entity)

    return success_object(serialize(appeal))


@bp.post("/appeals/<appealId>/grant")
def grant_appeal(appealId):
    return _adjudicate(appealId, "APPEAL_GRANTED")


@bp.post("/appeals/<appealId>/deny")
def deny_appeal(appealId):
    return _adjudicate(appealId, "APPEAL_DENIED")


@bp.post("/appeals/<appealId>/request-federal-review")
def request_federal_review(appealId):
    user_id, _ = require_roles("EntityComplianceOfficer")
    appeal = db.appeals.get(appealId)
    if appeal is None:
        raise err_not_found("Appeal not found")
    violation = db.violations.get(appeal["violation_id"])
    entity = db.registered_entities.get(violation["entity_id"]) if violation else None

    # state precondition
    if appeal["status"] != "APPEAL_DENIED":
        raise err_invalid_state("appeal is not APPEAL_DENIED")

    # federal review window
    denied_at = appeal.get("denied_at") or appeal["updated_at"]
    if clock_now() > denied_at + timedelta(days=FEDERAL_REVIEW_WINDOW_DAYS):
        raise err_appeal_window_expired()

    # ownership
    if violation is not None and violation["entity_id"] != user_id:
        raise err_forbidden()

    appeal["status"] = "FEDERAL_REVIEW_REQUESTED"
    touch(appeal)
    if entity is not None:
        entity["unresolved_appeal_count"] = entity.get("unresolved_appeal_count", 0) + 1
        touch(entity)
    return success_object(serialize(appeal))

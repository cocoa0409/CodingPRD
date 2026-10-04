"""Self-logging program: SelfLogEntry + ReviewPeriod endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from datetime import timedelta

from db import db
from errors import (
    err_empty_review_period, err_entity_restricted, err_entries_unreviewed,
    err_forbidden, err_invalid_request, err_invalid_state, err_not_found,
    err_self_log_not_enrolled, err_standard_not_applicable,
)
from helpers import (
    clock_now, entity_has_standard, new_common, parse_pagination, serialize,
    sort_and_page, touch,
)
from middleware import require_roles
from response import success_list, success_object
from routes_violations import VRF_VALUES, SEVERITY_VALUES, create_violation_record

bp = Blueprint("selflog", __name__)

READ_ROLES = (
    "ComplianceAuditor", "RegionalEntityReviewer", "FederalReviewer",
    "EntityComplianceOfficer",
)


@bp.post("/self-log-entries")
def create_self_log_entry():
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

    # enrollment (priority 7)
    if not entity.get("enrollment_self_logging", False):
        raise err_self_log_not_enrolled()

    standard_id = body.get("standard_id")
    if not isinstance(standard_id, str):
        raise err_invalid_request("standard_id is required")
    exception_note = body.get("exception_note")
    if not isinstance(exception_note, str) or not exception_note:
        raise err_invalid_request("exception_note is required")
    period_id = body.get("period_id")

    period = None
    if period_id is not None:
        if not isinstance(period_id, str):
            raise err_invalid_request("period_id must be a string")
        period = db.review_periods.get(period_id)
        if period is None:
            raise err_not_found("ReviewPeriod not found")
    else:
        # attach to the nearest unclosed period by open_at (latest opened)
        unclosed = [p for p in db.review_periods.values() if p["status"] != "CLOSED"]
        if unclosed:
            unclosed.sort(key=lambda p: (p["open_at"], p["id"]))
            period = unclosed[-1]

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
        "exception_note": exception_note,
        "logged_at": clock_now(),
        "period_id": period["id"] if period is not None else None,
        "status": "LOGGED",
    })
    db.self_log_entries[row["id"]] = row
    if period is not None:
        period["entry_count"] = period.get("entry_count", 0) + 1
        touch(period)
    return success_object(serialize(row), status=201)


@bp.get("/self-log-entries")
def list_self_log_entries():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    rows = list(db.self_log_entries.values())
    entity_id = request.args.get("entity_id")
    if entity_id is not None:
        rows = [r for r in rows if r["entity_id"] == entity_id]
    period_id = request.args.get("period_id")
    if period_id is not None:
        rows = [r for r in rows if r.get("period_id") == period_id]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = sort_and_page(rows, limit, offset)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.get("/self-log-entries/<entryId>")
def get_self_log_entry(entryId):
    require_roles(*READ_ROLES)
    row = db.self_log_entries.get(entryId)
    if row is None:
        raise err_not_found("SelfLogEntry not found")
    return success_object(serialize(row))


@bp.get("/review-periods/<periodId>/entries")
def list_period_entries(periodId):
    require_roles(*READ_ROLES)
    period = db.review_periods.get(periodId)
    if period is None:
        raise err_not_found("ReviewPeriod not found")
    limit, offset = parse_pagination(request.args)
    rows = [e for e in db.self_log_entries.values() if e.get("period_id") == periodId]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = sort_and_page(rows, limit, offset)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.post("/self-log-entries/<entryId>/review")
def review_self_log_entry(entryId):
    user_id, _ = require_roles("ComplianceAuditor")
    entry = db.self_log_entries.get(entryId)
    if entry is None:
        raise err_not_found("SelfLogEntry not found")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("request body must be a JSON object")
    outcome = body.get("outcome")
    if outcome not in ("REVIEWED_OK", "ESCALATED"):
        raise err_invalid_request("outcome must be REVIEWED_OK or ESCALATED")

    if entry["status"] != "LOGGED":
        raise err_invalid_state("entry is not LOGGED")
    period = db.review_periods.get(entry.get("period_id"))
    if period is None or period["status"] != "REVIEWING":
        raise err_invalid_state("the entry's period is not REVIEWING")

    entry["status"] = outcome
    touch(entry)

    if outcome == "REVIEWED_OK":
        period["reviewed_ok_count"] = period.get("reviewed_ok_count", 0) + 1
        touch(period)
    else:  # ESCALATED
        period["escalated_count"] = period.get("escalated_count", 0) + 1
        touch(period)
        vrf = body.get("violation_risk_factor")
        if vrf not in VRF_VALUES:
            raise err_invalid_request("violation_risk_factor is required and must be MINIMAL, MODERATE, or SERIOUS")
        severity = body.get("severity_level")
        if severity not in SEVERITY_VALUES:
            raise err_invalid_request("severity_level is required and must be LOWER, MODERATE, HIGH, or SEVERE")
        now = clock_now()
        start = entry["logged_at"]
        end = now if now > start else start + timedelta(seconds=1)
        create_violation_record(
            entity_id=entry["entity_id"],
            standard_id=entry["standard_id"],
            source_type="SELF_LOG",
            violation_start=start,
            violation_end=end,
            violation_risk_factor=vrf,
            severity_level=severity,
            created_by=user_id,
        )
    return success_object(serialize(entry))


# ---------------------------------------------------------------------------
# Review periods
# ---------------------------------------------------------------------------

@bp.post("/review-periods")
def create_review_period():
    require_roles("ComplianceAuditor")
    row = new_common()
    row.update({
        "open_at": clock_now(),
        "closed_at": None,
        "status": "OPEN",
        "entry_count": 0,
        "reviewed_ok_count": 0,
        "escalated_count": 0,
    })
    db.review_periods[row["id"]] = row
    return success_object(serialize(row), status=201)


@bp.get("/review-periods")
def list_review_periods():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    rows = list(db.review_periods.values())
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = sort_and_page(rows, limit, offset)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.get("/review-periods/<periodId>")
def get_review_period(periodId):
    require_roles(*READ_ROLES)
    row = db.review_periods.get(periodId)
    if row is None:
        raise err_not_found("ReviewPeriod not found")
    return success_object(serialize(row))


@bp.post("/review-periods/<periodId>/start-review")
def start_review(periodId):
    require_roles("ComplianceAuditor")
    row = db.review_periods.get(periodId)
    if row is None:
        raise err_not_found("ReviewPeriod not found")
    if row["status"] != "OPEN":
        raise err_invalid_state("period is not OPEN")
    if row.get("entry_count", 0) <= 0:
        raise err_empty_review_period()
    row["status"] = "REVIEWING"
    touch(row)
    return success_object(serialize(row))


@bp.post("/review-periods/<periodId>/close")
def close_review(periodId):
    require_roles("ComplianceAuditor")
    row = db.review_periods.get(periodId)
    if row is None:
        raise err_not_found("ReviewPeriod not found")
    if row["status"] != "REVIEWING":
        raise err_invalid_state("period is not REVIEWING")
    unreviewed = [
        e for e in db.self_log_entries.values()
        if e.get("period_id") == periodId and e["status"] == "LOGGED"
    ]
    if unreviewed:
        raise err_entries_unreviewed()
    row["status"] = "CLOSED"
    row["closed_at"] = clock_now()
    touch(row)
    return success_object(serialize(row))

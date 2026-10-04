"""Abuse case, action, and appeal routes."""
from __future__ import annotations

import db
from errors import (action_not_permitted, appeal_already_pending,
                    appeal_forbidden, invalid_request, invalid_state,
                    not_found, segregation_of_duties, stale_version)
from middleware import require_roles, pagination_params, paginate
from response import success
from services import domain
from services.domain import (ACTION_RANK, AUTO_ACTION_THRESHOLD, SEVERITY_RANK,
                             drop_queued_requests, terminate_agreements)
from services.util import (body, require_enum, require_number, require_str,
                           simple_view, sort_by_created, stamp_new, touch)

from flask import Blueprint, request

bp = Blueprint("abuse", __name__)

READ_ROLES = ("PlatformAdmin", "TrustAnalyst", "TrustLead", "OrganizationAdmin")


@bp.post("/abuse-cases")
def create_abuse_case():
    user_id, _ = require_roles("PlatformAdmin", "TrustAnalyst")
    data = body()
    org_id = require_str(data, "organization_id")
    source = require_enum(data, "source", {"AUTOMATED", "MANUAL"})
    severity = require_enum(data, "severity", {"LOW", "MEDIUM", "HIGH", "CRITICAL"})
    confidence = data.get("classifier_confidence")
    if source == "AUTOMATED":
        if confidence is None:
            raise invalid_request("classifier_confidence is required for AUTOMATED cases")
        confidence = require_number(data, "classifier_confidence", lo=0.0, hi=1.0)
    else:
        confidence = None  # manual: ignored even if supplied

    org = db.organizations.get(org_id)
    if org is None:
        raise not_found("organization not found")

    case = {
        "organization_id": org_id,
        "source": source,
        "classifier_confidence": confidence,
        "status": "OPEN",
        "severity": severity,
        "assigned_analyst_id": None,
    }
    stamp_new(case, common=True)
    db.abuse_cases[case["id"]] = case

    # Auto-escalation: AUTOMATED with confidence >= 0.95 -> system THROTTLE action
    if source == "AUTOMATED" and confidence is not None and confidence >= AUTO_ACTION_THRESHOLD:
        action = {
            "abuse_case_id": case["id"],
            "action_type": "THROTTLE",
            "issued_by": "system",
            "revoked_at": None,
        }
        stamp_new(action, common=False)
        db.abuse_actions[action["id"]] = action
        case["status"] = "ACTIONED"
        touch(case)
        # THROTTLE leaves org ACTIVE; rate-limit reduction is computed dynamically
    return success(simple_view(case), status=201)


def _get_case_or_404(case_id: str) -> dict:
    case = db.abuse_cases.get(case_id)
    if case is None:
        raise not_found("abuse case not found")
    return case


@bp.get("/abuse-cases/<case_id>")
def get_abuse_case(case_id):
    require_roles(*READ_ROLES)
    case = _get_case_or_404(case_id)
    return success(simple_view(case))


@bp.post("/abuse-cases/<case_id>/claim")
def claim_abuse_case(case_id):
    user_id, _ = require_roles("TrustAnalyst")
    case = _get_case_or_404(case_id)
    if case["status"] != "OPEN":
        raise invalid_state("case is not OPEN")
    if case["assigned_analyst_id"] is not None:
        raise invalid_state("case already assigned")
    case["assigned_analyst_id"] = user_id
    case["status"] = "UNDER_REVIEW"
    touch(case)
    return success(simple_view(case))


@bp.post("/abuse-cases/<case_id>/actions")
def issue_action(case_id):
    user_id, role = require_roles("TrustAnalyst", "TrustLead")
    case = _get_case_or_404(case_id)
    data = body()
    action_type = require_enum(data, "action_type",
                               {"WARN", "THROTTLE", "RESTRICT", "SUSPEND", "TERMINATE"})
    expected_version = data.get("expected_abuse_case_version")
    if expected_version is None:
        raise invalid_request("expected_abuse_case_version is required")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise invalid_request("expected_abuse_case_version must be an integer")

    if case["status"] != "UNDER_REVIEW":
        raise invalid_state("case is not UNDER_REVIEW")

    # OCC check (priority 6)
    if expected_version != case["version"]:
        raise stale_version()

    # Issuer identity and rank (priority 18)
    if role == "TrustAnalyst" and case["assigned_analyst_id"] != user_id:
        raise action_not_permitted("caller is not the assigned analyst")
    if action_type == "TERMINATE" and role != "TrustLead":
        raise action_not_permitted("TERMINATE is reserved to TrustLead")
    # Rank admissibility: WARN..SUSPEND require rank(action) <= rank(severity);
    # TERMINATE requires a CRITICAL case per PRD §3.7.
    if action_type == "TERMINATE":
        if case["severity"] != "CRITICAL":
            raise action_not_permitted("action rank exceeds case severity rank")
    elif ACTION_RANK[action_type] > SEVERITY_RANK[case["severity"]]:
        raise action_not_permitted("action rank exceeds case severity rank")

    org = db.organizations.get(case["organization_id"])
    if org is None:
        raise not_found("organization not found")

    # State-machine admissibility of the organizational transition (§3.7):
    # RESTRICT is ACTIVE → RESTRICTED, SUSPEND is RESTRICTED → SUSPENDED,
    # TERMINATE is ACTIVE → TERMINATED. Other source states are inadmissible.
    if action_type == "RESTRICT" and org["status"] != "ACTIVE":
        raise invalid_state("RESTRICT requires the organization to be ACTIVE")
    if action_type == "SUSPEND" and org["status"] != "RESTRICTED":
        raise invalid_state("SUSPEND requires the organization to be RESTRICTED")
    if action_type == "TERMINATE" and org["status"] != "ACTIVE":
        raise invalid_state("TERMINATE requires the organization to be ACTIVE")

    action = {
        "abuse_case_id": case["id"],
        "action_type": action_type,
        "issued_by": user_id,
        "revoked_at": None,
    }
    stamp_new(action, common=False)
    db.abuse_actions[action["id"]] = action
    case["status"] = "ACTIONED"
    touch(case)

    # Organizational cascade per action rank
    if action_type == "RESTRICT":
        org["status"] = "RESTRICTED"
        drop_queued_requests(org["id"])
        touch(org)
    elif action_type == "SUSPEND":
        org["status"] = "SUSPENDED"
        terminate_agreements(org["id"], {"ACTIVE"})
        drop_queued_requests(org["id"])
        touch(org)
    elif action_type == "TERMINATE":
        org["status"] = "TERMINATED"
        terminate_agreements(org["id"], {"DRAFT", "ACTIVE"})
        drop_queued_requests(org["id"])
        touch(org)
    # WARN / THROTTLE: org status unchanged
    return success(simple_view(action), status=201)


@bp.get("/abuse-cases/<case_id>/actions")
def list_case_actions(case_id):
    require_roles(*READ_ROLES)
    _get_case_or_404(case_id)
    limit, offset = pagination_params()
    items = [a for a in db.abuse_actions.values() if a["abuse_case_id"] == case_id]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success([simple_view(a) for a in page], response_type="array", pagination=meta)


@bp.get("/abuse-cases/<case_id>/appeals")
def list_case_appeals(case_id):
    require_roles(*READ_ROLES)
    _get_case_or_404(case_id)
    limit, offset = pagination_params()
    items = [a for a in db.appeals.values() if a["abuse_case_id"] == case_id]
    status_f = request.args.get("status")
    if status_f is not None:
        items = [a for a in items if a["status"] == status_f]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success([simple_view(a) for a in page], response_type="array", pagination=meta)


@bp.post("/appeals")
def create_appeal():
    user_id, _ = require_roles("OrganizationAdmin")
    data = body()
    case_id = require_str(data, "abuse_case_id")
    case = db.abuse_cases.get(case_id)
    if case is None:
        raise not_found("abuse case not found")
    if case["status"] != "ACTIONED":
        raise invalid_state("appeals may only be filed against an ACTIONED case")
    if user_id != case["organization_id"]:
        raise appeal_forbidden()
    for a in db.appeals.values():
        if a["abuse_case_id"] == case_id and a["status"] == "PENDING":
            raise appeal_already_pending()
    appeal = {
        "abuse_case_id": case_id,
        "submitted_by": user_id,
        "status": "PENDING",
        "resolved_by": None,
    }
    stamp_new(appeal, common=True)
    db.appeals[appeal["id"]] = appeal
    return success(simple_view(appeal), status=201)


@bp.post("/appeals/<appeal_id>/grant")
def grant_appeal(appeal_id):
    user_id, _ = require_roles("TrustLead")
    appeal = db.appeals.get(appeal_id)
    if appeal is None:
        raise not_found("appeal not found")
    if appeal["status"] != "PENDING":
        raise invalid_state("appeal is not PENDING")
    case = db.abuse_cases.get(appeal["abuse_case_id"])
    if case is None:
        raise not_found("abuse case not found")
    # find the appealed action: most recent unrevoked action on the case
    case_actions = [a for a in db.abuse_actions.values()
                    if a["abuse_case_id"] == case["id"] and a["revoked_at"] is None]
    case_actions.sort(key=lambda a: a["created_at"])
    appealed_action = case_actions[-1] if case_actions else None
    if appealed_action is not None and appealed_action["issued_by"] == user_id:
        raise segregation_of_duties("resolver must differ from the appealed action issuer")

    now_iso = db.fmt_clock(db.now())
    appeal["status"] = "GRANTED"
    appeal["resolved_by"] = user_id
    touch(appeal)
    if appealed_action is not None:
        appealed_action["revoked_at"] = now_iso
    case["status"] = "REINSTATED"
    touch(case)
    org = db.organizations.get(case["organization_id"])
    if org is not None and org["status"] in ("RESTRICTED", "SUSPENDED"):
        org["status"] = "ACTIVE"
        touch(org)
    return success(simple_view(appeal))

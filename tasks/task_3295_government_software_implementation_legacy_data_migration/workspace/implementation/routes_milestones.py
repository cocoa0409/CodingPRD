"""Routes: milestones and acceptance criteria."""
from flask import Blueprint, request

import db
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_DUPLICATE_KEY, ERR_SEGREGATION_OF_DUTIES, ERR_ACCEPTANCE_CRITERIA_OPEN,
    ERR_CONTRACT_VALUE_EXCEEDED, ERR_MILESTONE_REJECTION_LIMIT,
)
from middleware import require_roles
from response import success_object, success_list, parse_pagination, paginate
from routes_contracts import get_contract_or_404, get_phase_or_404
from services_common import strip_internal, append_audit, recompute_readiness
from util import (
    new_id, now_ts, touch, require_fields, require_int, get_clock_date,
)

bp = Blueprint("milestones", __name__)

RETAINAGE_PCT = 10


def get_milestone_or_404(mid):
    m = db.get("milestones", mid)
    if m is None:
        raise_error(ERR_NOT_FOUND, "milestone not found")
    return m


def _billable_sum(contract_id, statuses=("ACCEPTED", "INVOICED", "PAID")):
    return sum(m["billable_amount_cents"]
               for m in db.filter_items("milestones", contract_id=contract_id)
               if m["status"] in statuses)


@bp.route("/programs/phases/<phase_id>/milestones", methods=["POST"])
def create_milestone(phase_id):
    require_roles("ImplementationManager", "VendorProjectManager")
    phase = get_phase_or_404(phase_id)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["code", "description", "billable_amount_cents"])
    amount = require_int(payload, "billable_amount_cents")
    variant = payload.get("billing_variant", "PAYMENT_ON_ACCEPTANCE")
    if variant not in ("PAYMENT_ON_ACCEPTANCE", "RETAINAGE_HELD"):
        raise_error(ERR_INVALID_REQUEST, "invalid billing_variant")
    contract_id = phase["contract_id"]
    for m in db.filter_items("milestones", contract_id=contract_id):
        if m["code"] == payload["code"]:
            raise_error(ERR_DUPLICATE_KEY, "milestone code already exists for contract")
    contract = get_contract_or_404(contract_id)
    if _billable_sum(contract_id) + amount > contract["contract_value_cents"]:
        raise_error(ERR_CONTRACT_VALUE_EXCEEDED, "billable sum exceeds contract value")
    now = now_ts()
    milestone = {
        "id": new_id(),
        "contract_id": contract_id,
        "phase_id": phase["id"],
        "code": payload["code"],
        "description": payload["description"],
        "billable_amount_cents": amount,
        "billing_variant": variant,
        "status": "PLANNED",
        "rejection_count": 0,
        "accepted_at": None,
        "last_submitted_by": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.put("milestones", milestone)
    return success_object(strip_internal(milestone), 201)


@bp.route("/programs/phases/<phase_id>/milestones", methods=["GET"])
def list_phase_milestones(phase_id):
    require_roles("ImplementationManager", "AgencyProjectManager", "VendorProjectManager",
                  "FinanceOfficer", "PlatformAdmin")
    phase = get_phase_or_404(phase_id)
    limit, offset = parse_pagination(request.args)
    items = db.filter_items("milestones", phase_id=phase["id"])
    contract_id = request.args.get("contract_id")
    if contract_id is not None:
        items = [m for m in items if m["contract_id"] == contract_id]
    status = request.args.get("status")
    if status is not None:
        items = [m for m in items if m["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([strip_internal(m) for m in page], limit, offset, total)


@bp.route("/programs/contracts/<contract_id>/milestones", methods=["GET"])
def list_contract_milestones(contract_id):
    require_roles("ImplementationManager", "AgencyProjectManager", "VendorProjectManager",
                  "FinanceOfficer", "PlatformAdmin")
    c = get_contract_or_404(contract_id)
    limit, offset = parse_pagination(request.args)
    items = db.filter_items("milestones", contract_id=c["id"])
    status = request.args.get("status")
    if status is not None:
        items = [m for m in items if m["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([strip_internal(m) for m in page], limit, offset, total)


@bp.route("/programs/milestones/<mid>", methods=["GET"])
def get_milestone(mid):
    require_roles("ImplementationManager", "AgencyProjectManager", "VendorProjectManager",
                  "FinanceOfficer", "PlatformAdmin")
    return success_object(strip_internal(get_milestone_or_404(mid)), 200)


# ---------------- criteria ----------------

def get_criterion_or_404(cid):
    c = db.get("criteria", cid)
    if c is None:
        raise_error(ERR_NOT_FOUND, "criterion not found")
    return c


@bp.route("/programs/milestones/<mid>/criteria", methods=["POST"])
def create_criterion(mid):
    require_roles("ImplementationManager", "AgencyProjectManager")
    m = get_milestone_or_404(mid)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["code", "narrative"])
    for c in db.filter_items("criteria", milestone_id=m["id"]):
        if c["code"] == payload["code"]:
            raise_error(ERR_DUPLICATE_KEY, "criterion code already exists for milestone")
    now = now_ts()
    crit = {
        "id": new_id(),
        "milestone_id": m["id"],
        "code": payload["code"],
        "narrative": payload["narrative"],
        "result": "PENDING",
        "waiver_reason": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.put("criteria", crit)
    return success_object(strip_internal(crit), 201)


@bp.route("/programs/milestones/<mid>/criteria", methods=["GET"])
def list_criteria(mid):
    require_roles("ImplementationManager", "AgencyProjectManager", "VendorProjectManager", "PlatformAdmin")
    m = get_milestone_or_404(mid)
    limit, offset = parse_pagination(request.args)
    items = db.filter_items("criteria", milestone_id=m["id"])
    page, total = paginate(items, limit, offset)
    return success_list([strip_internal(c) for c in page], limit, offset, total)


@bp.route("/programs/criteria/<cid>/result", methods=["POST"])
def record_criterion_result(cid):
    require_roles("AgencyProjectManager")
    crit = get_criterion_or_404(cid)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["result"])
    result = payload["result"]
    if result not in ("SATISFIED", "FAILED", "WAIVED"):
        raise_error(ERR_INVALID_REQUEST, "invalid result")
    if result == "WAIVED":
        reason = payload.get("waiver_reason")
        if not isinstance(reason, str) or not reason.strip():
            raise_error(ERR_INVALID_REQUEST, "waiver_reason required when result is WAIVED")
        crit["waiver_reason"] = reason
    else:
        crit["waiver_reason"] = None
    crit["result"] = result
    touch(crit)
    return success_object(strip_internal(crit), 200)


# ---------------- milestone lifecycle ----------------

@bp.route("/programs/milestones/<mid>/submit", methods=["POST"])
def submit_milestone(mid):
    user_id, role = require_roles("VendorProjectManager")
    m = get_milestone_or_404(mid)
    if m["status"] != "PLANNED":
        raise_error(ERR_INVALID_STATE, "milestone not PLANNED")
    phase = get_phase_or_404(m["phase_id"])
    if phase["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "parent phase not ACTIVE")
    contract = get_contract_or_404(m["contract_id"])
    if contract["status"] != "IMPLEMENTATION":
        raise_error(ERR_INVALID_STATE, "contract not IMPLEMENTATION")
    m["status"] = "READY_FOR_REVIEW"
    m["last_submitted_by"] = user_id
    touch(m)
    return success_object(strip_internal(m), 200)


@bp.route("/programs/milestones/<mid>/accept", methods=["POST"])
def accept_milestone(mid):
    user_id, role = require_roles("AgencyProjectManager")
    m = get_milestone_or_404(mid)
    if m["status"] != "READY_FOR_REVIEW":
        raise_error(ERR_INVALID_STATE, "milestone not READY_FOR_REVIEW")
    # criteria check
    for crit in db.filter_items("criteria", milestone_id=m["id"]):
        if crit["result"] not in ("SATISFIED", "WAIVED"):
            raise_error(ERR_ACCEPTANCE_CRITERIA_OPEN, "open acceptance criteria")
        if crit["result"] == "WAIVED" and not crit.get("waiver_reason"):
            raise_error(ERR_ACCEPTANCE_CRITERIA_OPEN, "waived criterion lacks waiver_reason")
    if m.get("last_submitted_by") == user_id:
        raise_error(ERR_SEGREGATION_OF_DUTIES, "acceptor must differ from submitter")
    m["status"] = "ACCEPTED"
    m["accepted_at"] = now_ts()
    # milestone payment calculation
    if m["billing_variant"] == "RETAINAGE_HELD":
        retained = (m["billable_amount_cents"] * RETAINAGE_PCT) // 100
        m["retained_cents"] = retained
        m["payable_cents"] = m["billable_amount_cents"] - retained
    else:
        m["retained_cents"] = 0
        m["payable_cents"] = m["billable_amount_cents"]
    touch(m)
    # cascade hop 1: phase completion
    phase = get_phase_or_404(m["phase_id"])
    siblings = db.filter_items("milestones", phase_id=phase["id"])
    if phase["status"] == "ACTIVE" and all(
            s["status"] in ("ACCEPTED", "INVOICED", "PAID") for s in siblings):
        phase["status"] = "COMPLETED"
        touch(phase)
        # cascade hop 2: activate next phase
        for p in db.filter_items("phases", contract_id=m["contract_id"]):
            if p["sequence_no"] == phase["sequence_no"] + 1 and p["status"] == "PLANNED":
                p["status"] = "ACTIVE"
                touch(p)
    recompute_readiness(m["contract_id"])
    append_audit(m["contract_id"], role, user_id, "POST /programs/milestones/{id}/accept",
                 "Milestone", m["id"], "READY_FOR_REVIEW -> ACCEPTED")
    return success_object(strip_internal(m), 200)


@bp.route("/programs/milestones/<mid>/reject", methods=["POST"])
def reject_milestone(mid):
    user_id, role = require_roles("AgencyProjectManager")
    m = get_milestone_or_404(mid)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["rejection_note"])
    if not isinstance(payload["rejection_note"], str) or not payload["rejection_note"].strip():
        raise_error(ERR_INVALID_REQUEST, "rejection_note must be non-empty")
    if m["status"] != "READY_FOR_REVIEW":
        raise_error(ERR_INVALID_STATE, "milestone not READY_FOR_REVIEW")
    m["status"] = "REJECTED"
    m["rejection_count"] += 1
    touch(m)
    return success_object(strip_internal(m), 200)


@bp.route("/programs/milestones/<mid>/resubmit", methods=["POST"])
def resubmit_milestone(mid):
    user_id, role = require_roles("VendorProjectManager")
    m = get_milestone_or_404(mid)
    if m["status"] != "REJECTED":
        raise_error(ERR_INVALID_STATE, "milestone not REJECTED")
    if m["rejection_count"] >= 3:
        raise_error(ERR_MILESTONE_REJECTION_LIMIT, "rejection limit reached")
    m["status"] = "READY_FOR_REVIEW"
    m["last_submitted_by"] = user_id
    touch(m)
    return success_object(strip_internal(m), 200)


@bp.route("/programs/milestones/<mid>/invoice", methods=["POST"])
def invoice_milestone(mid):
    user_id, role = require_roles("VendorProjectManager")
    m = get_milestone_or_404(mid)
    if m["status"] != "ACCEPTED":
        raise_error(ERR_INVALID_STATE, "milestone not ACCEPTED")
    accepted_date = m["accepted_at"][:10] if m.get("accepted_at") else None
    if accepted_date and get_clock_date().isoformat() < accepted_date:
        raise_error(ERR_INVALID_STATE, "cannot invoice before acceptance date")
    contract = get_contract_or_404(m["contract_id"])
    if _billable_sum(m["contract_id"]) > contract["contract_value_cents"]:
        raise_error(ERR_CONTRACT_VALUE_EXCEEDED, "billable sum exceeds contract value")
    m["status"] = "INVOICED"
    touch(m)
    return success_object(strip_internal(m), 200)


@bp.route("/programs/milestones/<mid>/mark-paid", methods=["POST"])
def mark_paid_milestone(mid):
    user_id, role = require_roles("FinanceOfficer")
    m = get_milestone_or_404(mid)
    if m["status"] != "INVOICED":
        raise_error(ERR_INVALID_STATE, "milestone not INVOICED")
    # retainage release: if a go-live event for the contract is EXECUTED,
    # the retained portion becomes payable with this payment.
    if m["billing_variant"] == "RETAINAGE_HELD":
        executed = any(ev["status"] == "EXECUTED"
                       for ev in db.filter_items("go_live_events", contract_id=m["contract_id"]))
        if executed:
            m["payable_cents"] = m["billable_amount_cents"]
            m["retained_released"] = True
    m["status"] = "PAID"
    touch(m)
    append_audit(m["contract_id"], role, user_id, "POST /programs/milestones/{id}/mark-paid",
                 "Milestone", m["id"], "INVOICED -> PAID")
    return success_object(strip_internal(m), 200)

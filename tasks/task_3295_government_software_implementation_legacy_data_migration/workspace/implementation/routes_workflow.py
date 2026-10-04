"""Routes: workflow processes and configuration decisions."""
from flask import Blueprint, request

import db
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND, ERR_INVALID_REQUEST,
    ERR_INVALID_STATE, ERR_DUPLICATE_KEY, ERR_PROCESS_NOT_MAPPED,
)
from middleware import require_roles
from response import success_object, success_list, parse_pagination, paginate
from routes_contracts import get_contract_or_404
from services_common import strip_internal, append_audit, recompute_readiness
from util import new_id, now_ts, touch, require_fields

bp = Blueprint("workflow", __name__)


def get_process_or_404(pid):
    p = db.get("workflow_processes", pid)
    if p is None:
        raise_error(ERR_NOT_FOUND, "workflow process not found")
    return p


def get_decision_or_404(did):
    d = db.get("decisions", did)
    if d is None:
        raise_error(ERR_NOT_FOUND, "decision not found")
    return d


@bp.route("/programs/contracts/<contract_id>/workflow-processes", methods=["POST"])
def create_process(contract_id):
    require_roles("BusinessAnalyst")
    c = get_contract_or_404(contract_id)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["name", "as_is_summary", "to_be_summary"])
    now = now_ts()
    proc = {
        "id": new_id(),
        "contract_id": c["id"],
        "name": payload["name"],
        "as_is_summary": payload["as_is_summary"],
        "to_be_summary": payload["to_be_summary"],
        "map_revision": 1,
        "status": "DRAFT",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.put("workflow_processes", proc)
    return success_object(strip_internal(proc), 201)


@bp.route("/programs/contracts/<contract_id>/workflow-processes", methods=["GET"])
def list_processes(contract_id):
    require_roles("BusinessAnalyst", "AgencyProjectManager", "ImplementationManager", "PlatformAdmin")
    c = get_contract_or_404(contract_id)
    limit, offset = parse_pagination(request.args)
    items = db.filter_items("workflow_processes", contract_id=c["id"])
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([strip_internal(p) for p in page], limit, offset, total)


@bp.route("/programs/workflow-processes/<pid>", methods=["GET"])
def get_process(pid):
    require_roles("BusinessAnalyst", "AgencyProjectManager", "ImplementationManager", "PlatformAdmin")
    return success_object(strip_internal(get_process_or_404(pid)), 200)


@bp.route("/programs/workflow-processes/<pid>/map", methods=["POST"])
def map_process(pid):
    require_roles("BusinessAnalyst")
    p = get_process_or_404(pid)
    if p["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "process not DRAFT")
    if not p.get("as_is_summary") or not str(p["as_is_summary"]).strip():
        raise_error(ERR_INVALID_REQUEST, "as_is_summary must be non-empty")
    if not p.get("to_be_summary") or not str(p["to_be_summary"]).strip():
        raise_error(ERR_INVALID_REQUEST, "to_be_summary must be non-empty")
    p["status"] = "MAPPED"
    touch(p)
    return success_object(strip_internal(p), 200)


@bp.route("/programs/workflow-processes/<pid>/submit-review", methods=["POST"])
def submit_review(pid):
    require_roles("BusinessAnalyst")
    p = get_process_or_404(pid)
    if p["status"] != "MAPPED":
        raise_error(ERR_INVALID_STATE, "process not MAPPED")
    p["status"] = "IN_REVIEW"
    touch(p)
    return success_object(strip_internal(p), 200)


@bp.route("/programs/workflow-processes/<pid>/approve", methods=["POST"])
def approve_process(pid):
    user_id, role = require_roles("AgencyProjectManager")
    p = get_process_or_404(pid)
    if p["status"] != "IN_REVIEW":
        raise_error(ERR_INVALID_STATE, "process not IN_REVIEW")
    for d in db.filter_items("decisions", workflow_process_id=p["id"]):
        if d["status"] not in ("RATIFIED", "SUPERSEDED"):
            raise_error(ERR_INVALID_STATE, "linked decisions must be RATIFIED or SUPERSEDED")
    p["status"] = "APPROVED"
    touch(p)
    recompute_readiness(p["contract_id"])
    return success_object(strip_internal(p), 200)


@bp.route("/programs/workflow-processes/<pid>/send-rework", methods=["POST"])
def send_rework(pid):
    require_roles("AgencyProjectManager")
    p = get_process_or_404(pid)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["rework_note"])
    if p["status"] != "IN_REVIEW":
        raise_error(ERR_INVALID_STATE, "process not IN_REVIEW")
    p["status"] = "REWORK"
    touch(p)
    return success_object(strip_internal(p), 200)


@bp.route("/programs/workflow-processes/<pid>/remap", methods=["POST"])
def remap_process(pid):
    require_roles("BusinessAnalyst")
    p = get_process_or_404(pid)
    if p["status"] != "REWORK":
        raise_error(ERR_INVALID_STATE, "process not REWORK")
    p["status"] = "MAPPED"
    p["map_revision"] += 1
    touch(p)
    return success_object(strip_internal(p), 200)


@bp.route("/programs/workflow-processes/<pid>/retire", methods=["POST"])
def retire_process(pid):
    require_roles("AgencyProjectManager")
    p = get_process_or_404(pid)
    if p["status"] != "APPROVED":
        raise_error(ERR_INVALID_STATE, "process not APPROVED")
    c = get_contract_or_404(p["contract_id"])
    if c["status"] != "CLOSED":
        raise_error(ERR_INVALID_STATE, "contract not CLOSED")
    p["status"] = "RETIRED"
    touch(p)
    return success_object(strip_internal(p), 200)


# ---------------- configuration decisions ----------------

@bp.route("/programs/workflow-processes/<pid>/decisions", methods=["POST"])
def create_decision(pid):
    user_id, role = require_roles("BusinessAnalyst", "ImplementationManager")
    p = get_process_or_404(pid)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["decision_key", "chosen_value", "rationale"])
    supersedes = payload.get("supersedes_decision_id")
    if supersedes is not None:
        ref = db.get("decisions", supersedes)
        if ref is None:
            raise_error(ERR_REFERENCE_NOT_FOUND, "supersedes_decision_id does not exist")
    if p["status"] not in ("MAPPED", "APPROVED"):
        raise_error(ERR_PROCESS_NOT_MAPPED, "process must be MAPPED or APPROVED")
    for d in db.filter_items("decisions", contract_id=p["contract_id"]):
        if d["decision_key"] == payload["decision_key"]:
            raise_error(ERR_DUPLICATE_KEY, "decision_key already exists for contract")
    now = now_ts()
    decision = {
        "id": new_id(),
        "contract_id": p["contract_id"],
        "workflow_process_id": p["id"],
        "decision_key": payload["decision_key"],
        "chosen_value": payload["chosen_value"],
        "rationale": payload["rationale"],
        "recorded_by_role": role,
        "status": "PROPOSED",
        "supersedes_decision_id": supersedes,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.put("decisions", decision)
    return success_object(strip_internal(decision), 201)


@bp.route("/programs/workflow-processes/<pid>/decisions", methods=["GET"])
def list_process_decisions(pid):
    require_roles("BusinessAnalyst", "ImplementationManager", "AgencyProjectManager", "PlatformAdmin")
    p = get_process_or_404(pid)
    limit, offset = parse_pagination(request.args)
    items = db.filter_items("decisions", workflow_process_id=p["id"])
    contract_id = request.args.get("contract_id")
    if contract_id is not None:
        items = [d for d in items if d["contract_id"] == contract_id]
    status = request.args.get("status")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([strip_internal(d) for d in page], limit, offset, total)


@bp.route("/programs/contracts/<contract_id>/decisions", methods=["GET"])
def list_contract_decisions(contract_id):
    require_roles("BusinessAnalyst", "ImplementationManager", "AgencyProjectManager", "PlatformAdmin")
    c = get_contract_or_404(contract_id)
    limit, offset = parse_pagination(request.args)
    items = db.filter_items("decisions", contract_id=c["id"])
    status = request.args.get("status")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([strip_internal(d) for d in page], limit, offset, total)


@bp.route("/programs/decisions/<did>", methods=["GET"])
def get_decision(did):
    require_roles("BusinessAnalyst", "ImplementationManager", "AgencyProjectManager", "PlatformAdmin")
    return success_object(strip_internal(get_decision_or_404(did)), 200)


@bp.route("/programs/decisions/<did>/supersessions", methods=["GET"])
def list_supersessions(did):
    require_roles("BusinessAnalyst", "ImplementationManager", "AgencyProjectManager", "PlatformAdmin")
    d = get_decision_or_404(did)
    limit, offset = parse_pagination(request.args)
    items = [x for x in db.all_items("decisions") if x.get("supersedes_decision_id") == d["id"]]
    page, total = paginate(items, limit, offset)
    return success_list([strip_internal(x) for x in page], limit, offset, total)


@bp.route("/programs/decisions/<did>/ratify", methods=["POST"])
def ratify_decision(did):
    user_id, role = require_roles("AgencyProjectManager")
    d = get_decision_or_404(did)
    if d["status"] != "PROPOSED":
        raise_error(ERR_INVALID_STATE, "decision not PROPOSED")
    d["status"] = "RATIFIED"
    touch(d)
    sup = d.get("supersedes_decision_id")
    if sup:
        ref = db.get("decisions", sup)
        if ref is not None:
            ref["status"] = "SUPERSEDED"
            touch(ref)
    append_audit(d["contract_id"], role, user_id, "POST /programs/decisions/{id}/ratify",
                 "ConfigurationDecision", d["id"], "PROPOSED -> RATIFIED")
    return success_object(strip_internal(d), 200)


@bp.route("/programs/decisions/<did>/reject", methods=["POST"])
def reject_decision(did):
    require_roles("AgencyProjectManager")
    d = get_decision_or_404(did)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["rejection_note"])
    if d["status"] != "PROPOSED":
        raise_error(ERR_INVALID_STATE, "decision not PROPOSED")
    d["status"] = "REJECTED"
    touch(d)
    return success_object(strip_internal(d), 200)

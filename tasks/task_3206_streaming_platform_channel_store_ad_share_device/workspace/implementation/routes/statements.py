"""Revenue statements and disputes routes."""

from datetime import timedelta

from flask import Blueprint, request

import errors as E
from db import store
from middleware import (
    get_json_body,
    parse_iso8601,
    parse_pagination,
    require_enum,
    require_period,
    require_roles,
    require_str,
    to_iso_z,
)
from response import created, list_response, ok
from services.common import dispute_view, statement_view
from services.statement import assign_tier_and_fee, compute_amounts

bp = Blueprint("statements", __name__)

SUBJECT_TYPES = {"CHANNEL_REMOVAL", "STATEMENT"}


def get_statement_or_404(sid):
    s = store.statements.get(sid)
    if s is None:
        E.not_found("RevenueStatement not found")
    return s


def get_dispute_or_404(did):
    d = store.disputes.get(did)
    if d is None:
        E.not_found("Dispute not found")
    return d


def _sync_balance(publisher):
    from routes.core import recompute_outstanding_balance
    recompute_outstanding_balance(publisher)


@bp.post("/statements/generate")
def generate_statements():
    require_roles("PlatformAdmin")
    body = get_json_body()
    period = require_period(body, "period")
    generated = 0
    for pub in sorted(store.publishers.values(), key=lambda x: x["_seq"]):
        existing = None
        for s in store.statements.values():
            if s["publisher_id"] == pub["id"] and s["period"] == period:
                existing = s
                break
        if existing is not None and existing["status"] != "OPEN":
            # Only OPEN statements are recomputed; others are skipped.
            continue
        amounts = compute_amounts(pub, period)
        if existing is None:
            s = store.new_entity()
            s.update({
                "publisher_id": pub["id"],
                "period": period,
                "applied_tier": None,
                "applied_fee_bps": None,
                "status": "OPEN",
            })
            s.update(amounts)
            store.statements[s["id"]] = s
        else:
            existing.update(amounts)
            store.touch(existing)
        generated += 1
    return ok({"generated_count": generated})


@bp.get("/statements")
def list_statements():
    require_roles("PlatformAdmin", "AdOps", "Publisher")
    limit, offset = parse_pagination()
    pid = request.args.get("publisher_id")
    period = request.args.get("period")
    status = request.args.get("status")
    items = sorted(store.statements.values(), key=lambda x: x["_seq"])
    if pid is not None:
        items = [s for s in items if s["publisher_id"] == pid]
    if period is not None:
        items = [s for s in items if s["period"] == period]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return list_response([statement_view(s) for s in items], limit, offset, len(items))


@bp.get("/statements/<sid>")
def get_statement(sid):
    require_roles("PlatformAdmin", "AdOps", "Publisher")
    return ok(statement_view(get_statement_or_404(sid)))


@bp.post("/statements/<sid>/finalize")
def finalize_statement(sid):
    require_roles("PlatformAdmin")
    s = get_statement_or_404(sid)
    if s["status"] != "OPEN":
        E.invalid_state("Statement must be OPEN to finalize")
    pub = store.publishers.get(s["publisher_id"])
    if pub is None:
        E.not_found("Publisher not found")
    tier, fee = assign_tier_and_fee(pub, s["period"])
    amounts = compute_amounts(pub, s["period"], fee_bps=fee)
    s.update(amounts)
    s["applied_tier"] = tier
    s["applied_fee_bps"] = fee
    s["status"] = "FINALIZED"
    store.touch(s)
    if pub["revenue_tier"] != tier:
        pub["revenue_tier"] = tier
    _sync_balance(pub)
    store.touch(pub)
    return ok(statement_view(s))


@bp.post("/statements/<sid>/settle")
def settle_statement(sid):
    require_roles("PlatformAdmin")
    s = get_statement_or_404(sid)
    if s["status"] != "FINALIZED":
        E.invalid_state("Statement must be FINALIZED to settle")
    s["status"] = "SETTLED"
    store.touch(s)
    pub = store.publishers.get(s["publisher_id"])
    if pub is not None:
        _sync_balance(pub)
        store.touch(pub)
    return ok(statement_view(s))


@bp.post("/statements/<sid>/disputes")
def raise_statement_dispute(sid):
    user_id, role = require_roles("Publisher")
    s = get_statement_or_404(sid)
    if s["publisher_id"] != user_id:
        E.forbidden("Publisher caller does not own this statement")
    body = get_json_body()
    reason = require_str(body, "reason")
    if s["status"] != "FINALIZED":
        E.invalid_state("Statement must be FINALIZED to dispute")
    s["status"] = "DISPUTED"
    store.touch(s)
    d = store.new_entity()
    d.update({
        "publisher_id": user_id,
        "subject_type": "STATEMENT",
        "channel_id": None,
        "statement_id": s["id"],
        "reason": reason,
        "status": "FILED",
        "decision": None,
        "decided_at": None,
    })
    store.disputes[d["id"]] = d
    return created(dispute_view(d))


# ---- disputes ----

@bp.post("/disputes")
def create_dispute():
    user_id, role = require_roles("Publisher")
    body = get_json_body()
    publisher_id = require_str(body, "publisher_id")
    subject_type = require_enum(body, "subject_type", SUBJECT_TYPES)
    reason = require_str(body, "reason")
    if publisher_id != user_id:
        E.forbidden("Publisher caller may only raise disputes for itself")
    if publisher_id not in store.publishers:
        E.not_found("Publisher not found")
    channel_id = None
    statement_id = None
    if subject_type == "CHANNEL_REMOVAL":
        channel_id = body.get("channel_id")
        if channel_id is None or not isinstance(channel_id, str) or channel_id == "":
            E.invalid_request("channel_id is required for CHANNEL_REMOVAL disputes")
        ch = store.channels.get(channel_id)
        if ch is None:
            E.not_found("Channel not found")
        if ch["status"] != "REMOVED":
            E.invalid_state("Channel must be REMOVED to dispute its removal")
    d = store.new_entity()
    d.update({
        "publisher_id": publisher_id,
        "subject_type": subject_type,
        "channel_id": channel_id,
        "statement_id": statement_id,
        "reason": reason,
        "status": "FILED",
        "decision": None,
        "decided_at": None,
    })
    store.disputes[d["id"]] = d
    return created(dispute_view(d))


@bp.get("/disputes")
def list_disputes():
    require_roles("PlatformAdmin", "AdOps", "Publisher")
    limit, offset = parse_pagination()
    pid = request.args.get("publisher_id")
    cid = request.args.get("channel_id")
    sid = request.args.get("statement_id")
    status = request.args.get("status")
    items = sorted(store.disputes.values(), key=lambda x: x["_seq"])
    if pid is not None:
        items = [d for d in items if d["publisher_id"] == pid]
    if cid is not None:
        items = [d for d in items if d.get("channel_id") == cid]
    if sid is not None:
        items = [d for d in items if d.get("statement_id") == sid]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    return list_response([dispute_view(d) for d in items], limit, offset, len(items))


@bp.get("/disputes/<did>")
def get_dispute(did):
    require_roles("PlatformAdmin", "AdOps", "Publisher")
    return ok(dispute_view(get_dispute_or_404(did)))


@bp.post("/disputes/<did>/triage")
def triage_dispute(did):
    require_roles("PlatformAdmin")
    d = get_dispute_or_404(did)
    if d["status"] != "FILED":
        E.invalid_state("Dispute must be FILED to triage")
    d["status"] = "TRIAGE"
    store.touch(d)
    return ok(dispute_view(d))


@bp.post("/disputes/<did>/request-evidence")
def request_evidence(did):
    require_roles("PlatformAdmin")
    d = get_dispute_or_404(did)
    if d["status"] not in ("TRIAGE", "APPEALED"):
        E.invalid_state("Dispute must be TRIAGE or APPEALED to request evidence")
    d["status"] = "EVIDENCE"
    store.touch(d)
    return ok(dispute_view(d))


@bp.post("/disputes/<did>/decide")
def decide_dispute(did):
    require_roles("PlatformAdmin")
    d = get_dispute_or_404(did)
    body = get_json_body()
    decision = require_enum(body, "decision", {"UPHELD", "OVERTURNED"})
    if d["status"] != "EVIDENCE":
        E.invalid_state("Dispute must be in EVIDENCE to decide")
    d["decision"] = decision
    d["decided_at"] = to_iso_z(store.clock)
    d["status"] = "DECIDED"
    store.touch(d)
    if d["subject_type"] == "CHANNEL_REMOVAL" and decision == "OVERTURNED":
        ch = store.channels.get(d.get("channel_id"))
        if ch is not None and ch["status"] == "REMOVED":
            ch["status"] = "PUBLISHED"
            ch["policy_hold"] = False
            store.touch(ch)
    return ok(dispute_view(d))


@bp.post("/disputes/<did>/appeal")
def appeal_dispute(did):
    user_id, role = require_roles("Publisher")
    d = get_dispute_or_404(did)
    if d["publisher_id"] != user_id:
        E.forbidden("Publisher caller does not own this dispute")
    body = get_json_body()
    if "reason" in body and body["reason"] is not None and not isinstance(body["reason"], str):
        E.invalid_request("reason must be a string")
    if d["status"] != "DECIDED":
        E.invalid_state("Dispute must be DECIDED to appeal")
    decided = parse_iso8601(d["decided_at"], "decided_at")
    if store.clock > decided + timedelta(days=7):
        E.raise_err(E.ERR_APPEAL_WINDOW_EXPIRED,
                    "Appeal attempted more than 7 days after decided_at")
    d["status"] = "APPEALED"
    store.touch(d)
    return ok(dispute_view(d))


@bp.post("/disputes/<did>/close")
def close_dispute(did):
    require_roles("PlatformAdmin")
    d = get_dispute_or_404(did)
    if d["status"] != "DECIDED":
        E.invalid_state("Dispute must be DECIDED to close")
    d["status"] = "CLOSED"
    store.touch(d)
    if d["subject_type"] == "STATEMENT" and d.get("statement_id"):
        s = store.statements.get(d["statement_id"])
        if s is not None and s["status"] == "DISPUTED":
            s["status"] = "FINALIZED"
            store.touch(s)
    return ok(dispute_view(d))

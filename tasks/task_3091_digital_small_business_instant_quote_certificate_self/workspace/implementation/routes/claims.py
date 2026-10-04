"""Claim routes: intake, evidence, triage/approve/deny/payout/close."""
from datetime import timedelta

from flask import Blueprint, request

import db
import errors
import middleware as mw
import response as resp
from services import policy_ops as pops
from services import serialize as ser
from services import audit as aud

bp = Blueprint("claims", __name__)

FAST_TRACK_CAP = 100000
COMPLEX_FLOOR_EXCLUSIVE = 500000


def _body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise errors.validation("Request body must be a JSON object")
    return data


def triage_tier(amount, evidence_count):
    if amount > COMPLEX_FLOOR_EXCLUSIVE or evidence_count == 0:
        return "COMPLEX"
    if amount <= FAST_TRACK_CAP and evidence_count >= 1:
        return "FAST_TRACK"
    return "STANDARD"


def _get_claim_scoped(actor, cid):
    c = db.claims.get(cid)
    if c is None:
        raise errors.not_found("Claim not found")
    if actor.role == "Policyholder" and actor.user_id != c.get("reported_by"):
        raise errors.not_found("Claim not found")
    return c


@bp.post("/ins/claims")
def create_claim():
    actor = mw.get_actor()
    mw.require_role(actor, "Policyholder")
    body = _body()
    errors.reject_unknown_keys(body, (
        "policy_id", "loss_occurred_at", "description", "claim_amount_cents",
    ))
    policy_id = body.get("policy_id")
    loss_occurred_at = body.get("loss_occurred_at")
    description = body.get("description")
    amount = body.get("claim_amount_cents")

    if not isinstance(policy_id, str):
        raise errors.validation("policy_id is required")
    if not isinstance(description, str):
        raise errors.validation("description is required")
    if not isinstance(amount, int) or isinstance(amount, bool):
        raise errors.validation("claim_amount_cents must be an integer")

    p = db.policies.get(policy_id)
    if p is None:
        raise errors.not_found("Policy not found")
    # referential: claim.policy belongs to reporting account
    if p["business_account_id"] != actor.user_id:
        raise errors.not_found("Policy not found")

    if amount < 100:
        raise errors.claim_amount_floor()

    now = db.clock_now()
    try:
        loss = db.parse_iso(loss_occurred_at)
    except (ValueError, TypeError):
        raise errors.validation("loss_occurred_at must be an ISO8601 string")
    term_start = db.parse_iso(p["term_start"])
    term_end = db.parse_iso(p["term_end"])
    upper = min(term_end, now)
    if loss < term_start or loss > upper:
        raise errors.claim_window()
    if loss < now - timedelta(days=30):
        raise errors.claim_window()

    tier = triage_tier(amount, 0)
    status = "SUBMITTED"
    # FAST_TRACK auto-approval only possible with evidence; at intake
    # evidence_count is 0, so tier is COMPLEX or STANDARD — unless evidence
    # were pre-attached, which is impossible via this API. Kept for fidelity.
    if tier == "FAST_TRACK":
        status = "APPROVED"

    rec = {
        "id": db.new_id(),
        "policy_id": policy_id,
        "reported_by": actor.user_id,
        "loss_occurred_at": db.fmt_iso(loss),
        "description": description,
        "claim_amount_cents": amount,
        "triage_tier": tier,
        "evidence_count": 0,
        "adjuster_owner": None,
        "status": status,
        "created_at": db.fmt_iso(now),
        "updated_at": db.fmt_iso(now),
        "version": 1,
        "_seq": db.next_seq(),
        "_intake_at": db.fmt_iso(now),
    }
    db.claims[rec["id"]] = rec
    pops.recompute_open_claims(p)
    aud.record(actor.role, actor.user_id, "Claim", rec["id"], "intake",
               after=ser.public(rec))
    return resp.ok_object(ser.public(rec), status=201)


@bp.get("/ins/claims/<cid>")
def get_claim(cid):
    actor = mw.get_actor()
    mw.require_role(actor, "PlatformAdmin", "Policyholder", "ClaimsAdjuster", "FinanceOfficer")
    c = _get_claim_scoped(actor, cid)
    return resp.ok_object(ser.public(c))


@bp.get("/ins/policies/<pid>/claims")
def policy_claims(pid):
    actor = mw.get_actor()
    mw.require_role(actor, "PlatformAdmin", "Policyholder", "ClaimsAdjuster", "FinanceOfficer")
    p = db.policies.get(pid)
    if p is None:
        raise errors.not_found("Policy not found")
    if actor.role == "Policyholder" and actor.user_id != p["business_account_id"]:
        raise errors.not_found("Policy not found")
    items = [c for c in db.claims.values() if c["policy_id"] == pid]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = ser.sorted_by_created(items)
    limit, offset = resp.parse_pagination(request.args)
    return resp.ok_array(ser.public_list(items), limit, offset)


@bp.post("/ins/claims/<cid>/evidence")
def attach_evidence(cid):
    actor = mw.get_actor()
    mw.require_role(actor, "Policyholder")
    c = _get_claim_scoped(actor, cid)
    body = _body()
    errors.reject_unknown_keys(body, ("photo_ref", "exif_taken_at", "file_size_bytes"))
    photo_ref = body.get("photo_ref")
    exif_taken_at = body.get("exif_taken_at")
    file_size = body.get("file_size_bytes")

    if not isinstance(photo_ref, str) or not photo_ref:
        raise errors.validation("photo_ref is required")
    if not isinstance(file_size, int) or isinstance(file_size, bool):
        raise errors.validation("file_size_bytes must be an integer")

    # §2.7 priority: temporal-window rules precede shape constraints, so the
    # future-exif check runs before the evidence size range check.
    try:
        exif = db.parse_iso(exif_taken_at)
    except (ValueError, TypeError):
        raise errors.validation("exif_taken_at must be an ISO8601 string")
    now = db.clock_now()
    # PRD §3.7: exif_taken_at must not be later than the claim's intake instant.
    intake = db.parse_iso(c["_intake_at"]) if isinstance(c.get("_intake_at"), str) else c.get("_intake_at")
    if intake is not None and exif > intake:
        raise errors.evidence_future()
    if file_size < 1024 or file_size > 10485760:
        raise errors.evidence_size()

    rec = {
        "id": db.new_id(),
        "claim_id": cid,
        "photo_ref": photo_ref,
        "exif_taken_at": db.fmt_iso(exif),
        "file_size_bytes": file_size,
        "created_at": db.fmt_iso(now),
        "_seq": db.next_seq(),
    }
    db.claim_evidence[rec["id"]] = rec

    c["evidence_count"] = sum(1 for e in db.claim_evidence.values() if e["claim_id"] == cid)
    if c["status"] == "SUBMITTED":
        c["triage_tier"] = triage_tier(c["claim_amount_cents"], c["evidence_count"])
    c["updated_at"] = db.fmt_iso(now)
    c["version"] += 1
    aud.record(actor.role, actor.user_id, "ClaimEvidence", rec["id"], "attach",
               after=ser.public(rec))
    return resp.ok_object(ser.public(rec), status=201)


@bp.get("/ins/claims/<cid>/evidence")
def list_evidence(cid):
    actor = mw.get_actor()
    mw.require_role(actor, "PlatformAdmin", "Policyholder", "ClaimsAdjuster")
    _get_claim_scoped(actor, cid)
    items = [e for e in db.claim_evidence.values() if e["claim_id"] == cid]
    items = ser.sorted_by_created(items)
    limit, offset = resp.parse_pagination(request.args)
    return resp.ok_array(ser.public_list(items), limit, offset)


@bp.post("/ins/claims/<cid>/triage")
def triage_claim(cid):
    actor = mw.get_actor()
    mw.require_role(actor, "ClaimsAdjuster")
    c = _get_claim_scoped(actor, cid)
    if c["status"] != "SUBMITTED":
        raise errors.invalid_state("Claim is not SUBMITTED")
    now = db.clock_now()
    before = ser.public(c)
    c["status"] = "IN_REVIEW"
    c["adjuster_owner"] = actor.user_id
    c["updated_at"] = db.fmt_iso(now)
    c["version"] += 1
    aud.record(actor.role, actor.user_id, "Claim", c["id"], "triage",
               before=before, after=ser.public(c))
    return resp.ok_object(ser.public(c))


@bp.post("/ins/claims/<cid>/approve")
def approve_claim(cid):
    actor = mw.get_actor()
    mw.require_role(actor, "ClaimsAdjuster")
    c = _get_claim_scoped(actor, cid)
    if c["status"] != "IN_REVIEW":
        raise errors.invalid_state("Claim is not IN_REVIEW")
    if c["adjuster_owner"] != actor.user_id:
        raise errors.not_review_owner()
    now = db.clock_now()
    before = ser.public(c)
    c["status"] = "APPROVED"
    c["updated_at"] = db.fmt_iso(now)
    c["version"] += 1
    aud.record(actor.role, actor.user_id, "Claim", c["id"], "approve",
               before=before, after=ser.public(c))
    return resp.ok_object(ser.public(c))


@bp.post("/ins/claims/<cid>/deny")
def deny_claim(cid):
    actor = mw.get_actor()
    mw.require_role(actor, "ClaimsAdjuster")
    c = _get_claim_scoped(actor, cid)
    if c["status"] != "IN_REVIEW":
        raise errors.invalid_state("Claim is not IN_REVIEW")
    if c["adjuster_owner"] != actor.user_id:
        raise errors.not_review_owner()
    now = db.clock_now()
    before = ser.public(c)
    c["status"] = "DENIED"
    c["updated_at"] = db.fmt_iso(now)
    c["version"] += 1
    p = db.policies.get(c["policy_id"])
    if p:
        pops.recompute_open_claims(p)
    aud.record(actor.role, actor.user_id, "Claim", c["id"], "deny",
               before=before, after=ser.public(c))
    return resp.ok_object(ser.public(c))


@bp.post("/ins/claims/<cid>/payout")
def payout_claim(cid):
    actor = mw.get_actor()
    mw.require_role(actor, "FinanceOfficer")
    c = _get_claim_scoped(actor, cid)
    if c["status"] != "APPROVED":
        raise errors.invalid_state("Claim is not APPROVED")
    if c["adjuster_owner"] is not None and c["adjuster_owner"] == actor.user_id:
        raise errors.segregation_of_duties()
    now = db.clock_now()
    before = ser.public(c)
    c["status"] = "PAID"
    c["updated_at"] = db.fmt_iso(now)
    c["version"] += 1
    p = db.policies.get(c["policy_id"])
    if p:
        pops.recompute_open_claims(p)
    aud.record(actor.role, actor.user_id, "Claim", c["id"], "payout",
               before=before, after=ser.public(c))
    return resp.ok_object(ser.public(c))


@bp.post("/ins/claims/<cid>/close")
def close_claim(cid):
    actor = mw.get_actor()
    mw.require_role(actor, "ClaimsAdjuster")
    c = _get_claim_scoped(actor, cid)
    if c["status"] != "DENIED":
        raise errors.invalid_state("Claim is not DENIED")
    now = db.clock_now()
    before = ser.public(c)
    c["status"] = "CLOSED"
    c["updated_at"] = db.fmt_iso(now)
    c["version"] += 1
    aud.record(actor.role, actor.user_id, "Claim", c["id"], "close",
               before=before, after=ser.public(c))
    return resp.ok_object(ser.public(c))

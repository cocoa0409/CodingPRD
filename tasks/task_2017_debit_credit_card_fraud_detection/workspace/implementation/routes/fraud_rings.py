"""FraudRing and RingMembership endpoints."""

from flask import Blueprint, request

import db
import errors
import middleware
import response
from services import domain

bp = Blueprint("fraud_rings", __name__)


@bp.route("/fraudops/fraud-rings/detect", methods=["POST"])
def detect_ring():
    middleware.require_role("FraudOpsManager")
    body = request.get_json(silent=True) or {}
    signal_type = body.get("signal_type")
    merchant_id = body.get("merchant_id")
    window_start = body.get("window_start")
    window_end = body.get("window_end")

    if signal_type != "COMMON_MERCHANT":
        raise errors.err_invalid_request("signal_type must be COMMON_MERCHANT")
    if not isinstance(merchant_id, str) or not merchant_id:
        raise errors.err_invalid_request("merchant_id is required")
    if not isinstance(window_start, str) or not isinstance(window_end, str):
        raise errors.err_invalid_request("window_start and window_end are required")
    try:
        ws = db._parse_iso(window_start)
        we = db._parse_iso(window_end)
    except Exception:
        raise errors.err_invalid_request("window_start/window_end must be ISO 8601")
    if ws >= we:
        raise errors.err_invalid_window()

    # aggregate: account_id -> count of APPROVE txns at merchant in window
    counts: dict[str, int] = {}
    for t in db.auth_transactions.values():
        if t["merchant_id"] != merchant_id:
            continue
        if t["decision"] != "APPROVE":
            continue
        ts = db._parse_iso(t["scored_at"])
        if not (ws <= ts < we):
            continue
        counts[t["account_id"]] = counts.get(t["account_id"], 0) + 1

    qualifying = {aid: n for aid, n in counts.items() if n >= 2}
    if len(qualifying) < 3:
        raise errors.err_ring_threshold_not_met()

    ring = middleware.stamp_new(
        {
            "signal_type": signal_type,
            "merchant_id": merchant_id,
            "window_start": window_start,
            "window_end": window_end,
            "ring_status": "SUSPECTED",
            "member_count": len(qualifying),
        }
    )
    db.fraud_rings[ring["id"]] = ring
    db.ring_raised_watch[ring["id"]] = []

    # deterministic order by account created_at
    ordered_accounts = sorted(
        qualifying.keys(),
        key=lambda aid: (db.accounts[aid]["created_at"], aid),
    )
    for aid in ordered_accounts:
        m = middleware.stamp_new(
            {
                "ring_id": ring["id"],
                "account_id": aid,
                "evidence_txn_count": qualifying[aid],
            }
        )
        db.ring_memberships[m["id"]] = m

    return response.success(domain.ser_ring(ring), status_code=201)


@bp.route("/fraudops/fraud-rings", methods=["GET"])
def list_rings():
    middleware.require_role("FraudAnalyst", "FraudOpsManager")
    args = request.args
    items = sorted(db.fraud_rings.values(), key=lambda r: (r["created_at"], r["id"]))
    v = args.get("ring_status")
    if v:
        items = [r for r in items if r["ring_status"] == v]
    limit, offset = domain.parse_pagination_args(args)
    sliced, pg = domain.paginate(items, limit, offset)
    return response.success([domain.ser_ring(r) for r in sliced], pagination=pg)


@bp.route("/fraudops/fraud-rings/<rid>", methods=["GET"])
def get_ring(rid):
    middleware.require_role("FraudAnalyst", "FraudOpsManager")
    r = db.fraud_rings.get(rid)
    if not r:
        raise errors.err_not_found("FraudRing not found")
    return response.success(domain.ser_ring(r))


@bp.route("/fraudops/fraud-rings/<rid>/confirm", methods=["POST"])
def confirm_ring(rid):
    middleware.require_role("FraudOpsManager")
    r = db.fraud_rings.get(rid)
    if not r:
        raise errors.err_not_found("FraudRing not found")
    if r["ring_status"] != "SUSPECTED":
        raise errors.err_invalid_state("Ring is not SUSPECTED")

    r["ring_status"] = "CONFIRMED"
    middleware.touch(r)

    member_accounts = [
        m["account_id"] for m in db.ring_memberships.values() if m["ring_id"] == rid
    ]

    raised: list[str] = []
    for aid in member_accounts:
        for c in db.cards.values():
            if c["account_id"] == aid and c["fraud_flag"] == "CLEAN":
                c["fraud_flag"] = "WATCH"
                middleware.touch(c)
                raised.append(c["id"])
    db.ring_raised_watch[rid] = raised

    for aid in member_accounts:
        acct = db.accounts.get(aid)
        if not acct:
            continue
        old_tier = acct["risk_tier"]
        domain._recompute_account(aid)
        if acct["risk_tier"] == "HIGH" and old_tier != "HIGH":
            domain._escalate_open_alerts(aid)

    return response.success(domain.ser_ring(r))


@bp.route("/fraudops/fraud-rings/<rid>/dismiss", methods=["POST"])
def dismiss_ring(rid):
    middleware.require_role("FraudOpsManager")
    r = db.fraud_rings.get(rid)
    if not r:
        raise errors.err_not_found("FraudRing not found")
    if r["ring_status"] not in ("SUSPECTED", "CONFIRMED"):
        raise errors.err_invalid_state("Ring cannot be dismissed from its current state")

    was_confirmed = r["ring_status"] == "CONFIRMED"
    r["ring_status"] = "DISMISSED"
    middleware.touch(r)

    if was_confirmed:
        # Compensation: cards raised to WATCH by this ring's confirmation return to CLEAN
        for cid in db.ring_raised_watch.get(rid, []):
            card = db.cards.get(cid)
            if not card:
                continue
            if card["fraud_flag"] == "WATCH":
                card["fraud_flag"] = "CLEAN"
                middleware.touch(card)
        db.ring_raised_watch[rid] = []

        member_accounts = [
            m["account_id"] for m in db.ring_memberships.values() if m["ring_id"] == rid
        ]
        for aid in member_accounts:
            domain._recompute_account(aid)

    return response.success(domain.ser_ring(r))


@bp.route("/fraudops/ring-memberships", methods=["GET"])
def list_memberships():
    middleware.require_role("FraudAnalyst", "FraudOpsManager")
    args = request.args
    items = sorted(db.ring_memberships.values(), key=lambda m: (m["created_at"], m["id"]))
    for key in ("ring_id", "account_id"):
        v = args.get(key)
        if v:
            items = [m for m in items if m.get(key) == v]
    limit, offset = domain.parse_pagination_args(args)
    sliced, pg = domain.paginate(items, limit, offset)
    return response.success([domain.ser_membership(m) for m in sliced], pagination=pg)


@bp.route("/fraudops/ring-memberships/<mid>", methods=["GET"])
def get_membership(mid):
    middleware.require_role("FraudAnalyst", "FraudOpsManager")
    m = db.ring_memberships.get(mid)
    if not m:
        raise errors.err_not_found("RingMembership not found")
    return response.success(domain.ser_membership(m))

"""ReissueDecision endpoints."""

from flask import Blueprint, request

import db
import errors
import middleware
import response
from services import domain

bp = Blueprint("reissue_decisions", __name__)

VALID_DECISIONS = {"APPROVE", "DECLINE"}


@bp.route("/fraudops/reissue-decisions", methods=["GET"])
def list_decisions():
    middleware.require_role("FraudAnalyst", "FraudOpsManager")
    args = request.args
    # lazy auto-approval
    domain._apply_reissue_auto_approve_all()
    items = sorted(db.reissue_decisions.values(), key=lambda d: (d["created_at"], d["id"]))
    for key in ("event_id", "card_id", "decision", "replacement_card_id"):
        v = args.get(key)
        if v:
            items = [d for d in items if d.get(key) == v]
    limit, offset = domain.parse_pagination_args(args)
    sliced, pg = domain.paginate(items, limit, offset)
    return response.success([domain.ser_reissue(d) for d in sliced], pagination=pg)


@bp.route("/fraudops/reissue-decisions/<did>", methods=["GET"])
def get_decision(did):
    middleware.require_role("FraudAnalyst", "FraudOpsManager")
    d = db.reissue_decisions.get(did)
    if not d:
        raise errors.err_not_found("ReissueDecision not found")
    domain._apply_reissue_auto_approve(d)
    return response.success(domain.ser_reissue(d))


@bp.route("/fraudops/reissue-decisions/<did>/decide", methods=["POST"])
def decide(did):
    user_id, role = middleware.require_role("FraudAnalyst", "FraudOpsManager")
    d = db.reissue_decisions.get(did)
    if not d:
        raise errors.err_not_found("ReissueDecision not found")
    domain._apply_reissue_auto_approve(d)

    body = request.get_json(silent=True) or {}
    decision = body.get("decision")
    rationale = body.get("rationale")
    if decision not in VALID_DECISIONS:
        raise errors.err_invalid_request("decision must be APPROVE or DECLINE")

    if d["decision"] != "PENDING":
        raise errors.err_invalid_state("ReissueDecision is not PENDING")

    if decision == "DECLINE":
        if not isinstance(rationale, str) or not rationale:
            raise errors.err_invalid_request("rationale is required on DECLINE")
        if d["exposure_cents"] > 50000 and role != "FraudOpsManager":
            raise errors.err_decision_exposure_requires_manager()

    # Apply
    d["decided_by_user_id"] = user_id
    d["decided_at"] = db.get_clock_iso()

    if decision == "APPROVE":
        d["decision"] = "APPROVED"
        domain._mint_replacement(d)
    else:
        d["decision"] = "DECLINED"
        d["rationale"] = rationale
        # Downgrade flag COMPROMISED -> WATCH
        card = db.cards.get(d["card_id"])
        if card and card["fraud_flag"] == "COMPROMISED":
            card["fraud_flag"] = "WATCH"
            middleware.touch(card)
            domain._recompute_account(card["account_id"])

    middleware.touch(d)
    domain._event_auto_close(d["event_id"])
    return response.success(domain.ser_reissue(d))

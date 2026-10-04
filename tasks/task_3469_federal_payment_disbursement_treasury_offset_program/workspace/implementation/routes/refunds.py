"""RefundClaim endpoints (PRD §3.6): filing, review, decision with the
segregation-of-duties rule and the restitution cascade, and the single-appeal
loop."""
from datetime import timedelta

from flask import Blueprint, request

from constants import (
    APPEAL_WINDOW_DAYS,
    CLAIM_WINDOW_DAYS,
    REFUND_REASONS,
    ROLE_REFUND_OFFICER,
    ROLE_TREASURY_OPERATOR,
)
from db import STORE, clock_now, new_entity, touch
from errors import (
    err_appeal_limit_reached,
    err_appeal_window_expired,
    err_claim_window_expired,
    err_invalid_state,
    err_not_found,
    err_offset_not_applied,
    err_offset_not_found,
    err_refund_exceeds_offset,
    err_segregation,
)
from middleware import (
    authenticate,
    get_body,
    list_page,
    require_roles,
    spec_field,
    validate_body,
)
from response import ok, ok_list
from serializers import serialize_claim
from services.ledger import debit_clawback
from util import gen_id

bp = Blueprint("refunds", __name__)

_DECISION_ALIASES = ("APPROVE", "DENY", "approve", "deny")


@bp.post("/refund-claims")
def create_claim():
    ctx = authenticate()
    require_roles(ctx, ROLE_TREASURY_OPERATOR)
    data = validate_body(get_body(), [
        spec_field("offset_id", "str", required=True),
        spec_field("claimed_amount_cents", "int", required=True, gt=0),
        spec_field("reason", "enum", required=True, enum=REFUND_REASONS),
    ])
    offset = STORE["offsets"].get(data["offset_id"])
    if offset is None:
        raise err_offset_not_found()
    if offset["status"] != "APPLIED":
        raise err_offset_not_applied()
    # Temporal gate (tier 9): filed within 180 days of application.
    if clock_now() > offset["applied_at"] + timedelta(days=CLAIM_WINDOW_DAYS):
        raise err_claim_window_expired()
    # Amount bound (tier 11).
    if data["claimed_amount_cents"] > offset["offset_amount_cents"]:
        raise err_refund_exceeds_offset()

    ent = new_entity()
    ent["id"] = gen_id()
    ent.update({
        "offset_id": data["offset_id"],
        "claimed_amount_cents": data["claimed_amount_cents"],
        "reason": data["reason"],
        "status": "FILED",
        "appeal_count": 0,
        "decided_by_user_id": None,
        "decided_at": None,
        "refund_amount_cents": None,
        "clawback_cents": None,
        "treasury_absorbed_cents": None,
    })
    STORE["claims"][ent["id"]] = ent
    return ok(serialize_claim(ent), 201)


@bp.get("/refund-claims/<string:refundClaimId>")
def get_claim(refundClaimId):
    authenticate()
    claim = STORE["claims"].get(refundClaimId)
    if claim is None:
        raise err_not_found("Refund claim not found")
    return ok(serialize_claim(claim))


@bp.get("/refund-claims")
def list_claims():
    authenticate()
    items = list(STORE["claims"].values())
    offset_id = request.args.get("offset_id")
    status = request.args.get("status")
    if offset_id is not None:
        items = [c for c in items if c["offset_id"] == offset_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, limit, offset_n, total = list_page(items)
    return ok_list([serialize_claim(c) for c in page], limit, offset_n, total)


@bp.post("/refund-claims/<string:refundClaimId>/review")
def review_claim(refundClaimId):
    """FILED or APPEALED -> UNDER_REVIEW."""
    ctx = authenticate()
    require_roles(ctx, ROLE_REFUND_OFFICER)
    validate_body(get_body(), [])
    claim = STORE["claims"].get(refundClaimId)
    if claim is None:
        raise err_not_found("Refund claim not found")
    if claim["status"] not in ("FILED", "APPEALED"):
        raise err_invalid_state("Only a FILED or APPEALED claim can enter review")
    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    return ok(serialize_claim(claim))


@bp.post("/refund-claims/<string:refundClaimId>/decide")
def decide_claim(refundClaimId):
    """UNDER_REVIEW -> PAID (restitution cascade) or DENIED.

    Segregation of duties (tier 3) is checked as soon as the claim is
    loadable — before schema and state — per PRD §2.8: the decider must
    differ from the operator who executed the claimed offset's payment."""
    ctx = authenticate()
    require_roles(ctx, ROLE_REFUND_OFFICER)
    claim = STORE["claims"].get(refundClaimId)
    if claim is not None:
        offset = STORE["offsets"].get(claim["offset_id"])
        payment = STORE["payments"].get(offset["payment_id"]) if offset else None
        if payment is not None and payment["executed_by_user_id"] == ctx.user_id:
            raise err_segregation()
    data = validate_body(get_body(), [
        spec_field("decision", "enum", required=True, enum=_DECISION_ALIASES),
    ])
    decision = data["decision"].upper()
    if claim is None:
        raise err_not_found("Refund claim not found")
    if claim["status"] != "UNDER_REVIEW":
        raise err_invalid_state("Only an UNDER_REVIEW claim can be decided")

    now = clock_now()
    claim["decided_by_user_id"] = ctx.user_id
    claim["decided_at"] = now

    if decision == "APPROVE":
        offset = STORE["offsets"][claim["offset_id"]]
        debt = STORE["debts"].get(offset["debt_id"])
        creditor = STORE["creditors"].get(debt["creditor_agency_id"]) if debt else None

        # Restitution cascade (SCAFFOLD calculations.refund_restitution).
        offset["status"] = "REFUNDED"
        touch(offset)
        claim["refund_amount_cents"] = claim["claimed_amount_cents"]
        clawback = min(claim["claimed_amount_cents"], offset["net_remittance_cents"])
        claim["clawback_cents"] = clawback
        claim["treasury_absorbed_cents"] = claim["claimed_amount_cents"] - clawback
        if creditor is not None:
            debit_clawback(creditor, clawback)

        # The debt returns to the creditor for re-validation; the balance is
        # deliberately NOT restored (refund semantics differ from reversal).
        if debt is not None:
            if debt["status"] != "RETURNED":
                debt["status"] = "RETURNED"
            debt["returned_count"] += 1
            touch(debt)
            # The debt has left offset eligibility: any still-PROPOSED offsets
            # naming it drop to DROPPED (PRD §3.6).
            for o in STORE["offsets"].values():
                if o["debt_id"] == debt["id"] and o["status"] == "PROPOSED":
                    o["status"] = "DROPPED"
                    touch(o)
        claim["status"] = "PAID"
    else:
        claim["status"] = "DENIED"
    touch(claim)
    return ok(serialize_claim(claim))


@bp.post("/refund-claims/<string:refundClaimId>/appeal")
def appeal_claim(refundClaimId):
    """DENIED -> APPEALED: at most one appeal, within 30 days of the decision."""
    ctx = authenticate()
    require_roles(ctx, ROLE_TREASURY_OPERATOR)
    validate_body(get_body(), [])
    claim = STORE["claims"].get(refundClaimId)
    if claim is None:
        raise err_not_found("Refund claim not found")
    if claim["status"] != "DENIED":
        raise err_invalid_state("Only a DENIED claim can be appealed")
    if claim["appeal_count"] >= 1:
        raise err_appeal_limit_reached()
    if clock_now() > claim["decided_at"] + timedelta(days=APPEAL_WINDOW_DAYS):
        raise err_appeal_window_expired()
    claim["appeal_count"] += 1
    claim["status"] = "APPEALED"
    touch(claim)
    return ok(serialize_claim(claim))

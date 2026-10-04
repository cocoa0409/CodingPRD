"""Quality-guarantee claims and the double-refund policy."""
from datetime import timedelta

from flask import Blueprint

import calc
import svc
from core import (
    ApiError,
    body,
    db,
    dump,
    endpoint,
    f_date,
    f_enum,
    f_int,
    f_str,
    new_row,
    paginate,
    q_enum,
    q_str,
    respond_object,
    sort_created,
    touch,
)

bp = Blueprint("claims", __name__)


def _need_claim_with_transition(claim_id, allowed, error_id="ERR_INVALID_STATE"):
    claim = svc.need_claim(claim_id)
    if claim["status"] not in allowed:
        raise ApiError(error_id)
    return claim


def _adjust_store_liability(claim, delta_liability, delta_paid=0):
    store = db.stores[claim["store_id"]]
    store["refund_liability_cents"] += delta_liability
    store["refund_paid_cents"] += delta_paid
    touch(store)


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------
@bp.post("/v1/claims")
@endpoint("CustomerServiceAgent")
def create_claim():
    payload = body()
    product_id = f_str(payload, "product_id")
    store_id = f_str(payload, "store_id")
    quantity = f_int(payload, "quantity", minimum=1)
    unit_price_cents = f_int(payload, "unit_price_cents", minimum=0)
    purchase_date = f_date(payload, "purchase_date")
    reason = f_enum(payload, "reason", calc.CLAIM_REASONS)
    # tier 4 -- body FK existence, left to right
    svc.need_product(product_id)
    store = svc.need_store(store_id)
    # tier 7 -- temporal: the 45-day filing window
    if purchase_date < db.clock.date() - timedelta(days=calc.CLAIM_WINDOW_DAYS):
        raise ApiError("ERR_CLAIM_WINDOW_EXPIRED")
    claim = new_row(
        "QualityClaim",
        product_id=product_id,
        store_id=store["id"],
        quantity=quantity,
        unit_price_cents=unit_price_cents,
        purchase_date=purchase_date.isoformat(),
        reason=reason,
        refund_amount_cents=None,
        status="FILED",
    )
    db.claims[claim["id"]] = claim
    return respond_object(dump(claim), 201)


@bp.get("/v1/claims")
@endpoint("CustomerServiceAgent", "StoreManager", "OperationsAdmin")
def list_claims():
    product_id = q_str("product_id")
    store_id = q_str("store_id")
    status = q_enum("status", calc.CLAIM_STATUSES)
    rows = sort_created(list(db.claims.values()))
    if product_id is not None:
        rows = [r for r in rows if r["product_id"] == product_id]
    if store_id is not None:
        rows = [r for r in rows if r["store_id"] == store_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows)


@bp.get("/v1/claims/<claim_id>")
@endpoint("CustomerServiceAgent", "StoreManager", "OperationsAdmin")
def read_claim(claim_id):
    return respond_object(dump(svc.need_claim(claim_id)))


@bp.post("/v1/claims/<claim_id>/review")
@endpoint("CustomerServiceAgent")
def review_claim(claim_id):
    claim = _need_claim_with_transition(claim_id, ("FILED", "DISPUTED"))
    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    return respond_object(dump(claim))


@bp.post("/v1/claims/<claim_id>/approve")
@endpoint("CustomerServiceAgent")
def approve_claim(claim_id):
    claim = _need_claim_with_transition(claim_id, ("UNDER_REVIEW",))
    claim["refund_amount_cents"] = calc.refund_amount(
        claim["reason"], claim["unit_price_cents"], claim["quantity"]
    )
    claim["status"] = "APPROVED"
    touch(claim)
    _adjust_store_liability(claim, claim["refund_amount_cents"])
    return respond_object(dump(claim))


@bp.post("/v1/claims/<claim_id>/reject")
@endpoint("CustomerServiceAgent")
def reject_claim(claim_id):
    claim = _need_claim_with_transition(claim_id, ("UNDER_REVIEW",))
    claim["status"] = "REJECTED"
    touch(claim)
    return respond_object(dump(claim))


@bp.post("/v1/claims/<claim_id>/dispute")
@endpoint("CustomerServiceAgent")
def dispute_claim(claim_id):
    claim = _need_claim_with_transition(claim_id, ("UNDER_REVIEW",))
    claim["status"] = "DISPUTED"
    touch(claim)
    return respond_object(dump(claim))


@bp.post("/v1/claims/<claim_id>/pay")
@endpoint("CustomerServiceAgent")
def pay_claim(claim_id):
    claim = _need_claim_with_transition(claim_id, ("APPROVED",))
    claim["status"] = "PAID"
    touch(claim)
    _adjust_store_liability(
        claim, -claim["refund_amount_cents"], delta_paid=claim["refund_amount_cents"]
    )
    return respond_object(dump(claim))


@bp.post("/v1/claims/<claim_id>/rescind")
@endpoint("CustomerServiceAgent")
def rescind_claim(claim_id):
    claim = _need_claim_with_transition(claim_id, ("APPROVED",))
    claim["status"] = "RESCINDED"
    touch(claim)
    _adjust_store_liability(claim, -claim["refund_amount_cents"])
    return respond_object(dump(claim))

"""Pools and payment events."""
from flask import Blueprint, g

from core import (
    ApiError, db, dump, endpoint, f_bool, f_dt, f_enum, f_int, f_str, body,
    new_row, now, paginate, q_enum, q_str, respond_object, sort_created,
    touch, bad_request,
)
from svc import (
    appeal_deadline_from, find_pipeline, recompute_pool_balance,
    recompute_relief_tier, revalue_pipeline,
)

bp = Blueprint("pools", __name__)

ALL_ROLES = ("GseAdmin", "GseUnderwritingEngine", "SellerOfficer", "Underwriter", "QcAuditor", "ServicerOfficer")
POOL_STATUSES = ("OPEN", "LOCKED", "ISSUED", "CANCELLED")


# ---------------------------------------------------------------------------
# Pools
# ---------------------------------------------------------------------------
@bp.post("/gse/pools")
@endpoint("SellerOfficer")
def create_pool():
    payload = body()
    seller_id = f_str(payload, "seller_id")
    agreement_id = f_str(payload, "agreement_id")
    pool_number = f_str(payload, "pool_number")
    issue_date = f_dt(payload, "issue_date")
    target_balance_cents = f_int(payload, "target_balance_cents", minimum=1)
    if issue_date <= now():
        raise ApiError("ERR_INVALID_REQUEST", "issue_date must be strictly after the current logical time.")
    # Existence of body-referenced identifiers precedes the ownership gate (PRD §2.9).
    if seller_id not in db.sellers:
        raise ApiError("ERR_NOT_FOUND", "Seller not found.")
    if agreement_id not in db.agreements:
        raise ApiError("ERR_NOT_FOUND", "Master agreement not found.")
    if g.user_id != seller_id:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE", "SellerOfficer may only create pools for their own seller.")
    for existing in db.pools.values():
        if existing["pool_number"] == pool_number:
            raise ApiError("ERR_DUPLICATE_IDENTIFIER", "pool_number already in use.")
    pool = new_row(
        "pool",
        seller_id=seller_id,
        agreement_id=agreement_id,
        pool_number=pool_number,
        issue_date=issue_date,
        target_balance_cents=target_balance_cents,
        current_balance_cents=0,
        loan_count=0,
        status="OPEN",
    )
    db.pools[pool["id"]] = pool
    return respond_object(dump(pool), 201)


def get_pool_or_404(pool_id):
    pool = db.pools.get(pool_id)
    if pool is None:
        raise ApiError("ERR_NOT_FOUND", "Pool not found.")
    return pool


@bp.get("/gse/pools/<pool_id>")
@endpoint(*ALL_ROLES)
def get_pool(pool_id):
    return respond_object(dump(get_pool_or_404(pool_id)), 200)


@bp.get("/gse/pools")
@endpoint(*ALL_ROLES)
def list_pools():
    rows = list(db.pools.values())
    seller_id = q_str("seller_id")
    agreement_id = q_str("agreement_id")
    status = q_enum("status", POOL_STATUSES)
    if seller_id is not None:
        rows = [r for r in rows if r["seller_id"] == seller_id]
    if agreement_id is not None:
        rows = [r for r in rows if r["agreement_id"] == agreement_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(sort_created(rows))


@bp.post("/gse/pools/<pool_id>/lock")
@endpoint("SellerOfficer")
def lock_pool(pool_id):
    pool = get_pool_or_404(pool_id)
    if pool["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Only an OPEN pool can be locked.")
    if int(pool["loan_count"]) < 1:
        raise ApiError("ERR_POOL_EMPTY", "Pool lock requires at least one delivered loan.")
    pool["status"] = "LOCKED"
    touch(pool)
    return respond_object(dump(pool), 200)


@bp.post("/gse/pools/<pool_id>/unlock")
@endpoint("SellerOfficer")
def unlock_pool(pool_id):
    pool = get_pool_or_404(pool_id)
    if pool["status"] != "LOCKED":
        raise ApiError("ERR_INVALID_STATE", "Only a LOCKED pool can be unlocked.")
    pool["status"] = "OPEN"
    touch(pool)
    return respond_object(dump(pool), 200)


@bp.post("/gse/pools/<pool_id>/issue")
@endpoint("SellerOfficer")
def issue_pool(pool_id):
    pool = get_pool_or_404(pool_id)
    payload = body()
    expected_pool_version = f_int(payload, "expected_pool_version")
    if pool["status"] != "LOCKED":
        raise ApiError("ERR_INVALID_STATE", "Only a LOCKED pool can be issued.")
    if int(expected_pool_version) != int(pool["version"]):
        raise ApiError("ERR_STALE_VERSION", "Pool version has advanced since the caller's last read.")
    pool["status"] = "ISSUED"
    touch(pool)
    for loan in db.loans.values():
        if loan.get("pool_id") == pool["id"] and loan["status"] == "DELIVERED":
            loan["status"] = "PURCHASED"
            touch(loan)
    revalue_pipeline(pool["seller_id"])
    return respond_object(dump(pool), 200)


@bp.post("/gse/pools/<pool_id>/cancel")
@endpoint("SellerOfficer")
def cancel_pool(pool_id):
    pool = get_pool_or_404(pool_id)
    if pool["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Only an OPEN pool can be cancelled.")
    pool["status"] = "CANCELLED"
    touch(pool)
    for loan in db.loans.values():
        if loan.get("pool_id") == pool["id"] and loan["status"] == "DELIVERED":
            loan["status"] = "DRAFT"
            loan["pool_id"] = None
            loan["delivered_at"] = None
            touch(loan)
    recompute_pool_balance(pool)
    revalue_pipeline(pool["seller_id"])
    return respond_object(dump(pool), 200)


# ---------------------------------------------------------------------------
# Payment events
# ---------------------------------------------------------------------------
@bp.post("/gse/payment-events")
@endpoint("ServicerOfficer")
def create_payment_event():
    payload = body()
    loan_id = f_str(payload, "loan_id")
    due_date = f_dt(payload, "due_date")
    paid_on_time = f_bool(payload, "paid_on_time")
    amount_cents = f_int(payload, "amount_cents")
    if amount_cents <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "amount_cents must be a positive number of cents.")
    loan = db.loans.get(loan_id)
    if loan is None:
        raise ApiError("ERR_NOT_FOUND", "Loan not found.")
    if loan["status"] != "PURCHASED":
        raise ApiError("ERR_LOAN_NOT_PURCHASED", "Payment events require a PURCHASED loan.")
    for existing in db.payments.values():
        if existing["loan_id"] == loan_id and existing["due_date"] == due_date:
            raise ApiError("ERR_DUPLICATE_PAYMENT_PERIOD", "A payment event already exists for this loan and due_date.")
    outcome = "ON_TIME" if paid_on_time else "LATE"
    event = new_row(
        "payment",
        audited=False,
        loan_id=loan_id,
        due_date=due_date,
        paid_on_time=paid_on_time,
        amount_cents=amount_cents,
        outcome=outcome,
    )
    db.payments[event["id"]] = event
    if outcome == "ON_TIME":
        loan["consecutive_on_time_payments"] = int(loan["consecutive_on_time_payments"]) + 1
    else:
        loan["consecutive_on_time_payments"] = 0
    touch(loan)
    recompute_relief_tier(loan)
    return respond_object(dump(event), 201)


@bp.get("/gse/payment-events")
@endpoint(*ALL_ROLES)
def list_payment_events():
    rows = list(db.payments.values())
    loan_id = q_str("loan_id")
    outcome = q_enum("outcome", ("ON_TIME", "LATE"))
    if loan_id is not None:
        rows = [r for r in rows if r["loan_id"] == loan_id]
    if outcome is not None:
        rows = [r for r in rows if r["outcome"] == outcome]
    return paginate(sort_created(rows))

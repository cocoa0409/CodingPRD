"""Loans: registration, retrieval, delivery into pools."""
from flask import Blueprint, g

from core import (
    ApiError, db, dump, endpoint, f_enum, f_int, f_str, body, new_row, now,
    paginate, q_enum, q_str, respond_object, sort_created, touch, rhu_int,
)
from svc import active_matrix, match_pricing_row, recompute_pool_balance, revalue_pipeline

bp = Blueprint("loans", __name__)

ALL_ROLES = ("GseAdmin", "GseUnderwritingEngine", "SellerOfficer", "Underwriter", "QcAuditor", "ServicerOfficer")
OCCUPANCIES = ("PRIMARY_RESIDENCE", "SECOND_HOME", "INVESTMENT")
PRODUCT_TYPES = ("FIXED_30", "FIXED_15", "ARM_5_1")
LOAN_STATUSES = ("DRAFT", "UNDERWRITTEN", "DELIVERED", "PURCHASED", "REJECTED", "REPURCHASED")


@bp.post("/gse/loans")
@endpoint("SellerOfficer")
def create_loan():
    payload = body()
    seller_id = f_str(payload, "seller_id")
    servicer_id = f_str(payload, "servicer_id")
    agreement_id = f_str(payload, "agreement_id")
    loan_number = f_str(payload, "loan_number")
    borrower_name = f_str(payload, "borrower_name")
    upb = f_int(payload, "unpaid_principal_balance_cents", minimum=1)
    appraised = f_int(payload, "appraised_value_cents", minimum=1)
    credit_score = f_int(payload, "credit_score", minimum=300, maximum=850)
    occupancy = f_enum(payload, "occupancy", OCCUPANCIES)
    product_type = f_enum(payload, "product_type", PRODUCT_TYPES)
    # Existence of body-referenced identifiers precedes the ownership gate (PRD §2.9).
    if seller_id not in db.sellers:
        raise ApiError("ERR_NOT_FOUND", "Seller not found.")
    if servicer_id not in db.servicers:
        raise ApiError("ERR_NOT_FOUND", "Servicer not found.")
    if agreement_id not in db.agreements:
        raise ApiError("ERR_NOT_FOUND", "Master agreement not found.")
    # Entity-backed ownership: the SellerOfficer acts for their own seller.
    if g.user_id != seller_id:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE", "SellerOfficer may only register loans for their own seller.")
    for existing in db.loans.values():
        if existing["loan_number"] == loan_number:
            raise ApiError("ERR_DUPLICATE_IDENTIFIER", "loan_number already in use.")
    ltv_bp = rhu_int(10000 * upb / appraised)
    loan = new_row(
        "loan",
        seller_id=seller_id,
        servicer_id=servicer_id,
        agreement_id=agreement_id,
        loan_number=loan_number,
        borrower_name=borrower_name,
        unpaid_principal_balance_cents=upb,
        appraised_value_cents=appraised,
        credit_score=credit_score,
        occupancy=occupancy,
        product_type=product_type,
        ltv_bp=ltv_bp,
        au_status="NOT_SUBMITTED",
        status="DRAFT",
        relief_tier="NONE",
        consecutive_on_time_payments=0,
        independent_validation_complete=False,
        pool_id=None,
        delivery_price_cents=None,
        applied_llpa_bps=None,
        delivered_at=None,
    )
    db.loans[loan["id"]] = loan
    revalue_pipeline(seller_id)
    return respond_object(dump(loan), 201)


def get_loan_or_404(loan_id):
    loan = db.loans.get(loan_id)
    if loan is None:
        raise ApiError("ERR_NOT_FOUND", "Loan not found.")
    return loan


@bp.get("/gse/loans/<loan_id>")
@endpoint(*ALL_ROLES)
def get_loan(loan_id):
    return respond_object(dump(get_loan_or_404(loan_id)), 200)


@bp.get("/gse/loans")
@endpoint(*ALL_ROLES)
def list_loans():
    rows = list(db.loans.values())
    seller_id = q_str("seller_id")
    servicer_id = q_str("servicer_id")
    agreement_id = q_str("agreement_id")
    pool_id = q_str("pool_id")
    status = q_enum("status", LOAN_STATUSES)
    if seller_id is not None:
        rows = [r for r in rows if r["seller_id"] == seller_id]
    if servicer_id is not None:
        rows = [r for r in rows if r["servicer_id"] == servicer_id]
    if agreement_id is not None:
        rows = [r for r in rows if r["agreement_id"] == agreement_id]
    if pool_id is not None:
        rows = [r for r in rows if r.get("pool_id") == pool_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(sort_created(rows))


@bp.post("/gse/loans/<loan_id>/deliver")
@endpoint("SellerOfficer")
def deliver_loan(loan_id):
    loan = get_loan_or_404(loan_id)
    payload = body()
    pool_id = f_str(payload, "pool_id")
    # Priority 4: state gate.
    if loan["status"] != "UNDERWRITTEN":
        raise ApiError("ERR_INVALID_STATE", "Only an UNDERWRITTEN loan can be delivered.")
    # Priority 6: referential pool gate.
    pool = db.pools.get(pool_id)
    if (
        pool is None
        or pool["status"] != "OPEN"
        or pool["seller_id"] != loan["seller_id"]
        or pool["agreement_id"] != loan["agreement_id"]
    ):
        raise ApiError("ERR_POOL_NOT_OPEN", "Pool missing, not OPEN, or mismatched seller/agreement.")
    # Priority 8: fiscal gate (capacity).
    if int(pool["current_balance_cents"]) + int(loan["unpaid_principal_balance_cents"]) > int(pool["target_balance_cents"]):
        raise ApiError("ERR_POOL_CAPACITY_EXCEEDED", "Delivery would exceed pool target balance.")
    # Priority 9: constraint gates.
    if loan["au_status"] != "RECOMMEND_APPROVE":
        raise ApiError("ERR_LOAN_NOT_ELIGIBLE", "Loan lacks RECOMMEND_APPROVE.")
    seller = db.sellers.get(loan["seller_id"])
    if seller is None or seller["status"] != "APPROVED":
        raise ApiError("ERR_SELLER_NOT_APPROVED", "Seller is not APPROVED.")
    agreement = db.agreements.get(loan["agreement_id"])
    if agreement is None or agreement["status"] != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_EFFECTIVE", "Agreement is not ACTIVE.")
    # Final pricing against the ACTIVE grid at the delivery instant.
    matrix = active_matrix()
    row = match_pricing_row(loan, matrix)
    if row is not None:
        loan["applied_llpa_bps"] = int(row["llpa_bps"])
        adjustment = rhu_int(int(loan["unpaid_principal_balance_cents"]) * int(row["llpa_bps"]) / 10000)
        loan["delivery_price_cents"] = int(loan["unpaid_principal_balance_cents"]) - adjustment
    loan["status"] = "DELIVERED"
    loan["pool_id"] = pool["id"]
    loan["delivered_at"] = now()
    touch(loan)
    recompute_pool_balance(pool)
    revalue_pipeline(loan["seller_id"])
    return respond_object(dump(loan), 200)

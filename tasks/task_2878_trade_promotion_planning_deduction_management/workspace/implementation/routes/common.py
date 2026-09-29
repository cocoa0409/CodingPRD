"""Shared lookup, ordering and pagination helpers for the route modules."""

from errors import ApiError
from db import db
from response import list_response

PREFIX = "/trade-marketing"

ALL_ROLES = [
    "TradeMarketingDirector",
    "KeyAccountManager",
    "TradeFinanceAnalyst",
    "DeductionSpecialist",
    "ComplianceAuditor",
]
ALL_ROLES_WITH_PORTAL = ALL_ROLES + ["CustomerPortalUser"]
AUDIT_READ_ROLES = [
    "TradeMarketingDirector",
    "TradeFinanceAnalyst",
    "ComplianceAuditor",
    "DeductionSpecialist",
]


def _lookup(table, key, error_id):
    row = table.get(key)
    if row is None:
        raise ApiError(error_id)
    return row


def get_program(key):
    return _lookup(db.programs, key, "ERR_PROGRAM_NOT_FOUND")


def get_brand(key):
    return _lookup(db.brands, key, "ERR_BRAND_NOT_FOUND")


def get_customer(key):
    return _lookup(db.customers, key, "ERR_CUSTOMER_NOT_FOUND")


def get_allocation(key):
    return _lookup(db.allocations, key, "ERR_ALLOCATION_NOT_FOUND")


def get_promotion(key):
    return _lookup(db.promotions, key, "ERR_PROMOTION_NOT_FOUND")


def get_tactic(key):
    return _lookup(db.tactics, key, "ERR_TACTIC_NOT_FOUND")


def get_document(key):
    return _lookup(db.documents, key, "ERR_DOCUMENT_NOT_FOUND")


def get_fact(key):
    return _lookup(db.facts, key, "ERR_VOLUME_FACT_NOT_FOUND")


def get_accrual(key):
    return _lookup(db.accruals, key, "ERR_ACCRUAL_NOT_FOUND")


def get_deduction(key):
    return _lookup(db.deductions, key, "ERR_DEDUCTION_NOT_FOUND")


def get_dispute(key):
    return _lookup(db.disputes, key, "ERR_DISPUTE_NOT_FOUND")


def get_analysis(key):
    return _lookup(db.analyses, key, "ERR_ANALYSIS_NOT_FOUND")


def get_audit(key):
    return _lookup(db.audits, key, "ERR_AUDIT_NOT_FOUND")


# --------------------------------------------------------------------------
# ordering + pagination
# --------------------------------------------------------------------------

def created_asc(rows):
    return sorted(rows, key=lambda r: r["_seq"])


def created_desc(rows):
    return sorted(rows, key=lambda r: -r["_seq"])


def period_then_created(rows):
    return sorted(rows, key=lambda r: (r["period_start"], r["_seq"]))


def opened_then_created(rows):
    return sorted(rows, key=lambda r: (r["opened_at"], r["_seq"]))


def page(rows, limit, offset, serializer):
    total = len(rows)
    window = rows[offset:offset + limit]
    return list_response([serializer(row) for row in window], limit, offset, total)

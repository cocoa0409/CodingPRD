"""NationalAccount endpoints (PRD 3.4, 2.8).

POST /franchise/national-accounts, GET /franchise/national-accounts[/{id}]
"""
from flask import Blueprint

import derived
from auth import guard
from config import ACCOUNT_TYPES
from errors import ApiError
from fetch import get_account, paged
from response import created, ok
from store import common_fields, db
from validate import (
    body,
    reject_unknown,
    req_enum,
    req_int,
    req_str,
    req_str_list,
)

bp = Blueprint("accounts", __name__)

CREATE_INPUT = [
    "account_name", "account_type", "contracted_brands", "service_level_hours",
    "sla_credit_per_breach_cents", "breach_tolerance", "annual_commitment_cents",
]


@bp.post("/franchise/national-accounts")
def create_account():
    guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, CREATE_INPUT)
    account_name = req_str(b, "account_name")
    account_type = req_enum(b, "account_type", ACCOUNT_TYPES)
    contracted_brands = req_str_list(b, "contracted_brands", min_items=1)
    service_level_hours = req_int(b, "service_level_hours", minimum=1)
    credit_per_breach = req_int(b, "sla_credit_per_breach_cents", minimum=0)
    breach_tolerance = req_int(b, "breach_tolerance", minimum=1)
    annual_commitment = req_int(b, "annual_commitment_cents", minimum=0)

    # Body foreign keys resolve in the order the input list declares them.
    for brand_id in contracted_brands:
        if db.brands.get(brand_id) is None:
            raise ApiError("ERR_BRAND_NOT_FOUND")

    record = common_fields()
    record.update({
        "_kind": "NationalAccount",
        "account_name": account_name,
        "account_type": account_type,
        "contracted_brands": list(contracted_brands),
        "service_level_hours": service_level_hours,
        "sla_credit_per_breach_cents": credit_per_breach,
        "breach_tolerance": breach_tolerance,
        "annual_commitment_cents": annual_commitment,
        "open_breach_count": 0,
        "sla_credit_accrued_cents": 0,
        "accumulated_revenue_cents": 0,
        "commitment_attainment_pct": 0,
        "status": "ACTIVE",
    })
    db.national_accounts[record["id"]] = record
    return created(record)


@bp.get("/franchise/national-accounts/<account_id>")
def read_account(account_id):
    guard(["FranchiseAdmin", "ComplianceAuditor"])
    account = get_account(account_id)
    derived.refresh_account(account)
    return ok(account)


@bp.get("/franchise/national-accounts")
def list_accounts():
    guard(["FranchiseAdmin", "ComplianceAuditor"])
    records = list(db.national_accounts.values())
    for account in records:
        derived.refresh_account(account)
    return paged(db.national_accounts, "account_type", "status", rows=records)
"""Brand and Franchisee endpoints (PRD 3.1, 2.4).

POST /franchise/brands, GET /franchise/brands[/{id}]
POST /franchise/franchisees, GET /franchise/franchisees[/{id}]
POST /franchise/franchisees/{id}/suspend
"""
import re

from flask import Blueprint, request

import cascades
import derived
from auth import guard
from config import ENTITY_TYPES, FRANCHISEE_STATUSES, TRADES, CERTIFICATION_LEVELS
from errors import ApiError
from fetch import get_franchisee, get_brand, paged
from money import as_number, dec
from response import created, ok
from store import common_fields, db, touch
from validate import (
    body,
    opt_bool,
    opt_str,
    reject_unknown,
    req_enum,
    req_int,
    req_rate,
    req_str,
)

bp = Blueprint("portfolio", __name__)

BRAND_CODE_RE = re.compile(r"^[A-Z0-9-]{3,12}$")

BRAND_INPUT = [
    "brand_code", "display_name", "trade", "royalty_rate", "national_ad_fund_rate",
    "min_certification_level", "audit_cycle_months", "cross_brand_fee_table",
]
FRANCHISEE_INPUT = ["legal_name", "principal_name", "entity_type", "shared_services_enrolled"]


@bp.post("/franchise/brands")
def create_brand():
    _, _role = guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, BRAND_INPUT)
    brand_code = req_str(b, "brand_code")
    if not BRAND_CODE_RE.match(brand_code):
        raise ApiError("ERR_INVALID_REQUEST",
                       "brand_code must match ^[A-Z0-9-]{3,12}$.")
    if any(x.get("brand_code") == brand_code for x in db.brands.values()):
        raise ApiError("ERR_DUPLICATE_BRAND_CODE")
    display_name = req_str(b, "display_name")
    trade = req_enum(b, "trade", TRADES)
    royalty_rate = req_rate(b, "royalty_rate")
    ad_fund_rate = req_rate(b, "national_ad_fund_rate")
    min_cert = req_enum(b, "min_certification_level", CERTIFICATION_LEVELS)
    cycle = req_int(b, "audit_cycle_months", minimum=1)
    table = b.get("cross_brand_fee_table")
    if table is not None and not isinstance(table, dict):
        raise ApiError("ERR_INVALID_REQUEST", "cross_brand_fee_table must be an object.")

    record = common_fields()
    record.update({
        "_kind": "Brand",
        "brand_code": brand_code,
        "display_name": display_name,
        "trade": trade,
        "royalty_rate": as_number(royalty_rate),
        "national_ad_fund_rate": as_number(ad_fund_rate),
        "min_certification_level": min_cert,
        "cross_brand_fee_table": table or {},
        "audit_cycle_months": cycle,
        "status": "ACTIVE",
    })
    db.brands[record["id"]] = record
    return created(record)


@bp.get("/franchise/brands/<brand_id>")
def read_brand(brand_id):
    guard(["FranchiseAdmin", "FranchiseeOperator", "ComplianceAuditor"])
    return ok(get_brand(brand_id))


@bp.get("/franchise/brands")
def list_brands():
    guard(["FranchiseAdmin", "ComplianceAuditor"])
    return paged(db.brands, "trade", "brand_code")


@bp.post("/franchise/franchisees")
def create_franchisee():
    _, _role = guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, FRANCHISEE_INPUT)
    legal_name = req_str(b, "legal_name")
    principal_name = req_str(b, "principal_name")
    entity_type = req_enum(b, "entity_type", ENTITY_TYPES)
    enrolled = opt_bool(b, "shared_services_enrolled", default=False)

    record = common_fields()
    record.update({
        "_kind": "Franchisee",
        "legal_name": legal_name,
        "principal_name": principal_name,
        "entity_type": entity_type,
        "shared_services_enrolled": enrolled,
        "status": "PROSPECT",
        "active_brand_count": 0,
        "active_agreement_count": 0,
        "allocated_households": 0,
        "lead_cost_balance_cents": 0,
        "standards_score": 0,
        "standards_score_basis": "AUDIT_BASED",
    })
    db.franchisees[record["id"]] = record
    return created(record)


@bp.get("/franchise/franchisees/<franchisee_id>")
def read_franchisee(franchisee_id):
    guard(["FranchiseAdmin", "FranchiseeOperator", "ComplianceAuditor"])
    franchisee = get_franchisee(franchisee_id)
    derived.refresh_franchisee(franchisee)
    return ok(franchisee)


@bp.get("/franchise/franchisees")
def list_franchisees():
    guard(["FranchiseAdmin", "ComplianceAuditor"])
    records = list(db.franchisees.values())
    for franchisee in records:
        derived.refresh_franchisee(franchisee)
    return paged(db.franchisees, "status", "shared_services_enrolled", rows=records)


@bp.post("/franchise/franchisees/<franchisee_id>/suspend")
def suspend_franchisee(franchisee_id):
    guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, ["reason"])
    req_str(b, "reason")
    franchisee = get_franchisee(franchisee_id)
    franchisee["status"] = "SUSPENDED"
    cascades.stand_down_franchisee_territories(franchisee_id)
    derived.refresh_franchisee(franchisee)
    touch(franchisee)
    return ok(franchisee)
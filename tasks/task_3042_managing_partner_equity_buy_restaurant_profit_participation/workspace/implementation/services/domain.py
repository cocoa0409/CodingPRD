"""Domain helpers: entity getters, serializers, shared business lookups."""

from datetime import datetime, timezone

import db
from errors import (
    ERR_AGREEMENT_NOT_FOUND,
    ERR_BATCH_NOT_FOUND,
    ERR_BUYOUT_NOT_FOUND,
    ERR_CONTRACT_NOT_FOUND,
    ERR_DISPUTE_NOT_FOUND,
    ERR_GRANT_NOT_FOUND,
    ERR_LINE_ITEM_NOT_FOUND,
    ERR_MARKET_GROUP_NOT_FOUND,
    ERR_PARTNER_NOT_FOUND,
    ERR_PERIOD_NOT_FOUND,
    ERR_PROGRAM_NOT_FOUND,
    ERR_REFERENCE_NOT_FOUND,
    ERR_RESTAURANT_NOT_FOUND,
    ERR_YIELD_STANDARD_NOT_FOUND,
    not_found,
    reference_not_found,
)
from util import iso_out

# ---------------- program-wide constants (PRD §2.10) ----------------
FUNDING_WINDOW_DAYS = 14
RENEWAL_EXTENSION_YEARS = 2
MIN_TRAINING_WEEKS = 52
MAX_TRAINING_WEEKS = 78
DISPUTE_WINDOW_DAYS = 30
DISPUTE_ESCALATION_DAYS = 45
VESTING_DAYS = 365

TIER1_CAP = 5000000
TIER2_CAP = 10000000
TIER1_RATE_PCT = 8
TIER2_RATE_PCT = 10
TIER3_RATE_PCT = 12

SALES_TARGET_CENTS = 20000000
MARGIN_TARGET = 0.10
WASTE_ALLOWANCE_CENTS = 500000
STOCK_TIER1_SCORE = 80
STOCK_TIER2_SCORE = 90

CONTRACT_OPEN_STATUSES = ("PENDING_FUNDING", "ACTIVE", "RENEWAL_OFFERED", "BUYOUT_PENDING")
CONTRACT_ACTIVE_FAMILY = ("ACTIVE", "RENEWAL_OFFERED", "BUYOUT_PENDING")
DISPUTE_OPEN_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "EVIDENCE_REQUESTED", "ESCALATED")
BATCH_WASTE_STATUSES = ("AUDITED_CONFORMING", "VARIANCE_CONFIRMED")
PERIOD_BATCH_OPEN_STATUSES = ("OPEN", "COMPUTED", "REOPENED")

LINE_ITEM_CATEGORIES = (
    "REVENUE",
    "COST_OF_GOODS",
    "LABOR",
    "CORPORATE_ADMIN_FEE",
    "CORPORATE_MARKETING_FEE",
    "MEAT_WASTE_CHARGE",
    "ADJUSTMENT",
)


# ---------------- path getters (tier-3 existence, specific 404 ids) ----------------

def get_partner(pid):
    p = db.partners.get(pid)
    if p is None:
        raise not_found(ERR_PARTNER_NOT_FOUND, "Partner %s not found" % pid)
    return p


def get_market_group(gid):
    g = db.market_groups.get(gid)
    if g is None:
        raise not_found(ERR_MARKET_GROUP_NOT_FOUND, "MarketGroup %s not found" % gid)
    return g


def get_restaurant(rid):
    r = db.restaurants.get(rid)
    if r is None:
        raise not_found(ERR_RESTAURANT_NOT_FOUND, "Restaurant %s not found" % rid)
    return r


def get_contract(cid):
    c = db.contracts.get(cid)
    if c is None:
        raise not_found(ERR_CONTRACT_NOT_FOUND, "ManagingPartnerContract %s not found" % cid)
    return c


def get_period(pid):
    p = db.periods.get(pid)
    if p is None:
        raise not_found(ERR_PERIOD_NOT_FOUND, "ProfitPeriod %s not found" % pid)
    return p


def get_line_item(lid):
    li = db.line_items.get(lid)
    if li is None:
        raise not_found(ERR_LINE_ITEM_NOT_FOUND, "ProfitStatementLineItem %s not found" % lid)
    return li


def get_yield_standard(yid):
    y = db.yield_standards.get(yid)
    if y is None:
        raise not_found(ERR_YIELD_STANDARD_NOT_FOUND, "YieldStandard %s not found" % yid)
    return y


def get_batch(bid):
    b = db.batches.get(bid)
    if b is None:
        raise not_found(ERR_BATCH_NOT_FOUND, "MeatCutBatch %s not found" % bid)
    return b


def get_program(pid):
    p = db.award_programs.get(pid)
    if p is None:
        raise not_found(ERR_PROGRAM_NOT_FOUND, "AwardProgram %s not found" % pid)
    return p


def get_grant(gid):
    g = db.award_grants.get(gid)
    if g is None:
        raise not_found(ERR_GRANT_NOT_FOUND, "AwardGrant %s not found" % gid)
    return g


def get_dispute(did):
    d = db.disputes.get(did)
    if d is None:
        raise not_found(ERR_DISPUTE_NOT_FOUND, "DisputeCase %s not found" % did)
    return d


def get_agreement(aid):
    a = db.agreements.get(aid)
    if a is None:
        raise not_found(ERR_AGREEMENT_NOT_FOUND, "MarketPartnerAgreement %s not found" % aid)
    return a


def get_buyout(bid):
    b = db.buyout_orders.get(bid)
    if b is None:
        raise not_found(ERR_BUYOUT_NOT_FOUND, "BuyoutOrder %s not found" % bid)
    return b


# ---------------- body FK resolvers (tier-4, ERR_REFERENCE_NOT_FOUND) ----------------

def ref_partner(pid):
    if pid not in db.partners:
        raise reference_not_found("partner_id %s does not resolve" % pid)
    return db.partners[pid]


def ref_restaurant(rid):
    if rid not in db.restaurants:
        raise reference_not_found("restaurant_id %s does not resolve" % rid)
    return db.restaurants[rid]


def ref_market_group(gid):
    if gid not in db.market_groups:
        raise reference_not_found("market_group_id %s does not resolve" % gid)
    return db.market_groups[gid]


def ref_period(pid):
    if pid not in db.periods:
        raise reference_not_found("period_id %s does not resolve" % pid)
    return db.periods[pid]


# ---------------- computed fields ----------------

def training_weeks_accrued(partner):
    started = partner.get("training_started_at")
    if started is None:
        return 0
    delta = db.clock_now() - started
    return int(delta.total_seconds() // (7 * 86400))


# ---------------- serializers ----------------

def ser_partner(p):
    return {
        "id": p["id"],
        "full_name": p["full_name"],
        "email": p["email"],
        "role_in_program": p["role_in_program"],
        "status": p["status"],
        "training_started_at": iso_out(p.get("training_started_at")),
        "training_weeks_accrued": training_weeks_accrued(p),
        "certified_at": iso_out(p.get("certified_at")),
        "placed_restaurant_id": p.get("placed_restaurant_id"),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_market_group(g):
    return {
        "id": g["id"],
        "name": g["name"],
        "status": g["status"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def ser_restaurant(r):
    return {
        "id": r["id"],
        "name": r["name"],
        "city": r["city"],
        "state_code": r["state_code"],
        "market_group_id": r.get("market_group_id"),
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_contract(c):
    return {
        "id": c["id"],
        "partner_id": c["partner_id"],
        "restaurant_id": c["restaurant_id"],
        "term_start_date": c["term_start_date"],
        "term_end_date": c["term_end_date"],
        "buy_in_required_cents": c["buy_in_required_cents"],
        "buy_in_escrow_cents": c["buy_in_escrow_cents"],
        "capital_account_cents": c["capital_account_cents"],
        "submitted_at": iso_out(c.get("submitted_at")),
        "renewed_count": c["renewed_count"],
        "departure_date": c.get("departure_date"),
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_buy_in_payment(p):
    return {
        "id": p["id"],
        "contract_id": p["contract_id"],
        "amount_cents": p["amount_cents"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_agreement(a):
    return {
        "id": a["id"],
        "partner_id": a["partner_id"],
        "market_group_id": a["market_group_id"],
        "coverage_start_date": a["coverage_start_date"],
        "coverage_end_date": a["coverage_end_date"],
        "override_pct": a["override_pct"],
        "basis": a["basis"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_period(p):
    return {
        "id": p["id"],
        "restaurant_id": p["restaurant_id"],
        "period_start_date": p["period_start_date"],
        "period_end_date": p["period_end_date"],
        "status": p["status"],
        "provisional_profit_cents": p.get("provisional_profit_cents"),
        "final_distributable_profit_cents": p.get("final_distributable_profit_cents"),
        "partner_share_cents": p.get("partner_share_cents"),
        "market_override_cents": p.get("market_override_cents"),
        "corporate_retained_cents": p.get("corporate_retained_cents"),
        "partner_share_paid": p.get("partner_share_paid", False),
        "finalized_at": iso_out(p.get("finalized_at")),
        "dispute_deadline": iso_out(p.get("dispute_deadline")),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_line_item(li):
    return {
        "id": li["id"],
        "period_id": li["period_id"],
        "category": li["category"],
        "amount_cents": li["amount_cents"],
        "entry_status": li["entry_status"],
        "actual_amount_cents": li["actual_amount_cents"],
        "partner_basis": li["partner_basis"],
        "created_at": li["created_at"],
        "updated_at": li["updated_at"],
        "version": li["version"],
    }


def ser_yield_standard(y):
    return {
        "id": y["id"],
        "cut_code": y["cut_code"],
        "expected_yield_pct": y["expected_yield_pct"],
        "waste_tolerance_pct": y["waste_tolerance_pct"],
        "standard_cost_per_lb_cents": y["standard_cost_per_lb_cents"],
        "active": y["active"],
        "created_at": y["created_at"],
        "updated_at": y["updated_at"],
        "version": y["version"],
    }


def ser_batch(b):
    return {
        "id": b["id"],
        "restaurant_id": b["restaurant_id"],
        "profit_period_id": b["profit_period_id"],
        "cut_code": b["cut_code"],
        "sub_primal_weight_lbs": b["sub_primal_weight_lbs"],
        "actual_yield_lbs": b.get("actual_yield_lbs"),
        "actual_waste_lbs": b.get("actual_waste_lbs"),
        "excess_waste_lbs": b.get("excess_waste_lbs"),
        "waste_charge_cents": b.get("waste_charge_cents"),
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def ser_program(p):
    return {
        "id": p["id"],
        "name": p["name"],
        "program_type": p["program_type"],
        "performance_period_start_date": p["performance_period_start_date"],
        "performance_period_end_date": p["performance_period_end_date"],
        "eligibility_threshold_score": p["eligibility_threshold_score"],
        "stock_units_pool": p.get("stock_units_pool"),
        "units_reserved": p["units_reserved"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_grant(g):
    return {
        "id": g["id"],
        "program_id": g["program_id"],
        "partner_id": g["partner_id"],
        "source_period_id": g["source_period_id"],
        "eligibility_score": g["eligibility_score"],
        "units_awarded": g["units_awarded"],
        "status": g["status"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def ser_dispute(d):
    return {
        "id": d["id"],
        "period_id": d["period_id"],
        "filed_by_partner_id": d["filed_by_partner_id"],
        "claim_text": d["claim_text"],
        "filed_at": iso_out(d.get("filed_at")),
        "adjustment_cents": d.get("adjustment_cents"),
        "status": d["status"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def ser_buyout(b):
    return {
        "id": b["id"],
        "contract_id": b["contract_id"],
        "capital_return_cents": b["capital_return_cents"],
        "accrued_share_cents": b["accrued_share_cents"],
        "offset_cents": b["offset_cents"],
        "total_payout_cents": b["total_payout_cents"],
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


# ---------------- shared business lookups ----------------

def restaurant_has_open_dispute(restaurant_id):
    """Any open dispute on any period of this restaurant."""
    period_ids = {
        p["id"] for p in db.periods.values() if p["restaurant_id"] == restaurant_id
    }
    return any(
        d["period_id"] in period_ids and d["status"] in DISPUTE_OPEN_STATUSES
        for d in db.disputes.values()
    )


def active_family_contract(restaurant_id):
    """Contract on the restaurant in {ACTIVE, RENEWAL_OFFERED, BUYOUT_PENDING}, or None."""
    for c in db.contracts.values():
        if c["restaurant_id"] == restaurant_id and c["status"] in CONTRACT_ACTIVE_FAMILY:
            return c
    return None

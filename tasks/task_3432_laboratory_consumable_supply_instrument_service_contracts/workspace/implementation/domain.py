"""Domain constants, derived-state calculators, shared effects, serializers.

All values come from SCAFFOLD.yaml / PRD.md — nothing is assumed.
Derived-at-read fields (agreement/contract status, instrument operational
status, account trailing spend, engineer open tickets, catalog available
stock) are computed here on every read and never mutate stored records.
"""
from datetime import timedelta
from decimal import Decimal

import db as dbmod
from util import fmt_dt, round_half_up

# --- enum vocabularies -------------------------------------------------------
SEGMENTS = {"ACADEMIC", "PHARMA", "CLINICAL", "INDUSTRIAL"}
PRIORITY_CLASSES = {"STANDARD", "PRIORITY", "CRITICAL"}
PLACEMENT_TYPES = {"CAPITAL", "REAGENT_RENTAL", "LEASE"}
CONTRACT_TIERS = {"BRONZE", "SILVER", "GOLD", "PLATINUM"}
REQUEST_TYPES = {"BREAK_FIX", "PREVENTIVE_MAINTENANCE", "APP_SUPPORT", "METHOD_DEV"}
SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
SKILLS = {"BREAK_FIX", "PM", "APP_SUPPORT", "METHOD_DEV", "INSTALL"}
ENGINEER_STATUSES = {"ACTIVE", "INACTIVE"}
ITEM_CLASSES = {"STANDARD", "COLD_CHAIN", "HAZARDOUS", "CONTROLLED"}
ALLOCATION_GROUPS = {"GROUP_A", "GROUP_B", "GROUP_C"}
ACCOUNT_STATUSES = {"ACTIVE", "SUSPENDED", "CLOSED"}

# --- calculation constants ---------------------------------------------------
TIER_RESPONSE_HOURS = {"BRONZE": 72, "SILVER": 48, "GOLD": 24, "PLATINUM": 8}
TIER_PM_VISITS = {"BRONZE": 1, "SILVER": 2, "GOLD": 4, "PLATINUM": 12}
TIER_PARTS_PCT = {"BRONZE": 0, "SILVER": 50, "GOLD": 90, "PLATINUM": 100}
TIER_LOANER_ELIGIBLE = {"BRONZE": False, "SILVER": False, "GOLD": True, "PLATINUM": True}
TIER_MONTHLY_VALUE = {"BRONZE": 50000, "SILVER": 120000, "GOLD": 300000, "PLATINUM": 800000}

EA_TIER_DISCOUNT = {"BASE": 0, "SILVER": 5, "GOLD": 10, "PLATINUM": 15}
SILVER_FLOOR_CENTS = 10000000
GOLD_FLOOR_CENTS = 50000000
PLATINUM_FLOOR_CENTS = 200000000

HANDLING_FEE = {"STANDARD": 0, "COLD_CHAIN": 4500, "HAZARDOUS": 7500, "CONTROLLED": 9500}
CLASS_PRECEDENCE = {"STANDARD": 0, "COLD_CHAIN": 1, "HAZARDOUS": 2, "CONTROLLED": 3}
TRANSIT_DAYS = {"STANDARD": 3, "COLD_CHAIN": 1, "HAZARDOUS": 5, "CONTROLLED": 4}

PRIORITY_WEIGHT = {"STANDARD": 10, "PRIORITY": 50, "CRITICAL": 100}
TIER_MULT = {
    "BASE": Decimal("1.0"),
    "SILVER": Decimal("1.2"),
    "GOLD": Decimal("1.5"),
    "PLATINUM": Decimal("2.0"),
}

CREDIT_LIMIT_CENTS = 2000000
LABOR_RATE_CENTS_PER_HOUR = 18500
TRIP_CHARGE_CENTS = 45000
SLA_CREDIT_PCT = 10
DEFAULT_RESPONSE_HOURS = 72
ENGINEER_DAILY_CAPACITY = 4
PM_MIN_GAP_DAYS = 30
EA_EXPIRING_DAYS = 60
CONTRACT_RENEWAL_DUE_DAYS = 30
TRAILING_WINDOW_DAYS = 365
FORWARD_WEIGHT = Decimal("0.5")

REQUEST_TYPE_SKILL = {
    "BREAK_FIX": "BREAK_FIX",
    "PREVENTIVE_MAINTENANCE": "PM",
    "APP_SUPPORT": "APP_SUPPORT",
    "METHOD_DEV": "METHOD_DEV",
}

ACCOUNT_TRANSITIONS = {
    ("ACTIVE", "SUSPENDED"),
    ("SUSPENDED", "ACTIVE"),
    ("ACTIVE", "CLOSED"),
    ("SUSPENDED", "CLOSED"),
}


# --- derived-at-read calculators ---------------------------------------------
def agreement_status(agr, now=None):
    now = now or dbmod.now()
    if agr["terminated_at"] is not None:
        return "TERMINATED"
    if now >= agr["end_date"]:
        return "EXPIRED"
    if now >= agr["end_date"] - timedelta(days=EA_EXPIRING_DAYS):
        return "EXPIRING"
    return "ACTIVE"


def contract_status(contract, now=None):
    now = now or dbmod.now()
    if contract["cancelled_at"] is not None:
        return "CANCELLED"
    if now >= contract["end_date"]:
        return "EXPIRED"
    if now >= contract["end_date"] - timedelta(days=CONTRACT_RENEWAL_DUE_DAYS):
        return "RENEWAL_DUE"
    return "ACTIVE"


def account_trailing_spend(account_id, now=None):
    """Sum of total_cents over the account's DELIVERED orders in the last 365 days."""
    now = now or dbmod.now()
    cutoff = now - timedelta(days=TRAILING_WINDOW_DAYS)
    total = 0
    for o in dbmod.store.orders.values():
        if (
            o["account_id"] == account_id
            and o["status"] == "DELIVERED"
            and o["delivered_at"] is not None
            and o["delivered_at"] >= cutoff
        ):
            total += o["total_cents"]
    return total


def ea_tier_for_trailing(trailing):
    if trailing >= PLATINUM_FLOOR_CENTS:
        return "PLATINUM"
    if trailing >= GOLD_FLOOR_CENTS:
        return "GOLD"
    if trailing >= SILVER_FLOOR_CENTS:
        return "SILVER"
    return "BASE"


def live_agreement_for_account(account_id, now=None):
    """The account's agreement reading ACTIVE or EXPIRING, if one exists."""
    for g in dbmod.store.agreements.values():
        if g["account_id"] == account_id and agreement_status(g, now) in ("ACTIVE", "EXPIRING"):
            return g
    return None


def live_contract_for_instrument(instrument_id, now=None):
    """The instrument's contract reading ACTIVE or RENEWAL_DUE, if one exists."""
    for c in dbmod.store.contracts.values():
        if c["instrument_id"] == instrument_id and contract_status(c, now) in (
            "ACTIVE",
            "RENEWAL_DUE",
        ):
            return c
    return None


def instrument_operational_status(instrument_id):
    for r in dbmod.store.service_requests.values():
        if (
            r["instrument_id"] == instrument_id
            and r["request_type"] == "BREAK_FIX"
            and r["severity"] == "CRITICAL"
            and r["status"] in ("OPEN", "DISPATCHED")
        ):
            return "DOWN"
    return "UP"


def engineer_open_ticket_count(engineer_id):
    return sum(
        1
        for r in dbmod.store.service_requests.values()
        if r["engineer_id"] == engineer_id and r["status"] == "DISPATCHED"
    )


def engineer_dispatched_today(engineer_id, now=None):
    """Tickets currently DISPATCHED that were dispatched on today's UTC calendar day."""
    now = now or dbmod.now()
    today = now.date().isoformat()
    return sum(
        1
        for r in dbmod.store.service_requests.values()
        if r["engineer_id"] == engineer_id
        and r["status"] == "DISPATCHED"
        and r.get("dispatched_day") == today
    )


def active_surge_groups():
    return {
        s["allocation_group"]
        for s in dbmod.store.surge_events.values()
        if s["status"] == "ACTIVE"
    }


def order_items(order):
    """Resolve an order's lines to (catalog_item, quantity) pairs."""
    out = []
    for ln in order["lines"]:
        item = dbmod.store.catalog_items[dbmod.store.catalog_by_sku[ln["sku"]]]
        out.append((item, ln["quantity"]))
    return out


def created_sorted(items):
    """List endpoints sort by created_at ascending; seq breaks clock-tie groups."""
    return sorted(items, key=lambda e: (e["created_at"], e["seq"]))


# --- credit-hold cascade (PRD section 2.8) ------------------------------------
def evaluate_credit(account, now=None):
    """Recompute and persist credit_status; a GOOD->HOLD flip cancels DRAFT orders."""
    now = now or dbmod.now()
    new_status = "HOLD" if account["outstanding_balance_cents"] > CREDIT_LIMIT_CENTS else "GOOD"
    if account["credit_status"] != "HOLD" and new_status == "HOLD":
        account["credit_status"] = "HOLD"
        for o in dbmod.store.orders.values():
            if o["account_id"] == account["id"] and o["status"] == "DRAFT":
                o["status"] = "CANCELLED"
                o["version"] += 1
                o["updated_at"] = now
    else:
        account["credit_status"] = new_status


def post_charge(account, amount_cents, now=None):
    """Post a charge to outstanding_balance_cents and run credit evaluation."""
    account["outstanding_balance_cents"] += amount_cents
    evaluate_credit(account, now)


# --- serializers (compute derived fields at read; never mutate) ---------------
def account_json(a):
    return {
        "id": a["id"],
        "name": a["name"],
        "segment": a["segment"],
        "priority_class": a["priority_class"],
        "territory_code": a["territory_code"],
        "controlled_substance_license": a["controlled_substance_license"],
        "status": a["status"],
        "credit_status": a["credit_status"],
        "outstanding_balance_cents": a["outstanding_balance_cents"],
        "trailing_spend_cents": account_trailing_spend(a["id"]),
        "created_at": fmt_dt(a["created_at"]),
        "updated_at": fmt_dt(a["updated_at"]),
        "version": a["version"],
    }


def agreement_json(g):
    tier = ea_tier_for_trailing(account_trailing_spend(g["account_id"]))
    return {
        "id": g["id"],
        "account_id": g["account_id"],
        "start_date": fmt_dt(g["start_date"]),
        "end_date": fmt_dt(g["end_date"]),
        "committed_annual_spend_cents": g["committed_annual_spend_cents"],
        "status": agreement_status(g),
        "current_tier": tier,
        "discount_pct": EA_TIER_DISCOUNT[tier],
        "renewal_count": g["renewal_count"],
        "terminated_at": fmt_dt(g["terminated_at"]),
        "created_at": fmt_dt(g["created_at"]),
        "updated_at": fmt_dt(g["updated_at"]),
        "version": g["version"],
    }


def instrument_json(i):
    return {
        "id": i["id"],
        "account_id": i["account_id"],
        "model": i["model"],
        "serial_number": i["serial_number"],
        "placement_type": i["placement_type"],
        "monthly_consumable_commitment_cents": i["monthly_consumable_commitment_cents"],
        "monthly_baseline_consumable_cents": i["monthly_baseline_consumable_cents"],
        "placement_status": i["placement_status"],
        "operational_status": instrument_operational_status(i["id"]),
        "installed_at": fmt_dt(i["installed_at"]),
        "created_at": fmt_dt(i["created_at"]),
        "updated_at": fmt_dt(i["updated_at"]),
        "version": i["version"],
    }


def contract_json(c):
    tier = c["tier"]
    return {
        "id": c["id"],
        "instrument_id": c["instrument_id"],
        "tier": tier,
        "response_hours": TIER_RESPONSE_HOURS[tier],
        "pm_visits_per_year": TIER_PM_VISITS[tier],
        "parts_coverage_pct": TIER_PARTS_PCT[tier],
        "loaner_eligible": TIER_LOANER_ELIGIBLE[tier],
        "monthly_value_cents": TIER_MONTHLY_VALUE[tier],
        "start_date": fmt_dt(c["start_date"]),
        "end_date": fmt_dt(c["end_date"]),
        "status": contract_status(c),
        "used_pm_visits": c["used_pm_visits"],
        "renewal_count": c["renewal_count"],
        "cancelled_at": fmt_dt(c["cancelled_at"]),
        "created_at": fmt_dt(c["created_at"]),
        "updated_at": fmt_dt(c["updated_at"]),
        "version": c["version"],
    }


def engineer_json(e):
    return {
        "id": e["id"],
        "name": e["name"],
        "territory_code": e["territory_code"],
        "skills": list(e["skills"]),
        "status": e["status"],
        "open_ticket_count": engineer_open_ticket_count(e["id"]),
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def service_request_json(r):
    return {
        "id": r["id"],
        "instrument_id": r["instrument_id"],
        "engineer_id": r["engineer_id"],
        "loaner_unit_id": r["loaner_unit_id"],
        "request_type": r["request_type"],
        "severity": r["severity"],
        "scheduled_for": fmt_dt(r["scheduled_for"]),
        "status": r["status"],
        "opened_at": fmt_dt(r["opened_at"]),
        "response_deadline": fmt_dt(r["response_deadline"]),
        "resolved_at": fmt_dt(r["resolved_at"]),
        "sla_breached": r["sla_breached"],
        "hours_on_site": r["hours_on_site"],
        "parts_cost_cents": r["parts_cost_cents"],
        "billable_cents": r["billable_cents"],
        "covered_cents": r["covered_cents"],
        "credit_memo_cents": r["credit_memo_cents"],
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
    }


def loaner_unit_json(u):
    return {
        "id": u["id"],
        "model": u["model"],
        "serial_number": u["serial_number"],
        "status": u["status"],
        "created_at": fmt_dt(u["created_at"]),
        "updated_at": fmt_dt(u["updated_at"]),
        "version": u["version"],
    }


def catalog_item_json(c):
    return {
        "id": c["id"],
        "sku": c["sku"],
        "name": c["name"],
        "item_class": c["item_class"],
        "allocation_group": c["allocation_group"],
        "base_price_cents": c["base_price_cents"],
        "stock_on_hand": c["stock_on_hand"],
        "reserved_quantity": c["reserved_quantity"],
        "available_stock": c["stock_on_hand"] - c["reserved_quantity"],
        "created_at": fmt_dt(c["created_at"]),
        "updated_at": fmt_dt(c["updated_at"]),
        "version": c["version"],
    }


def order_json(o):
    score = o["allocation_score"]
    return {
        "id": o["id"],
        "account_id": o["account_id"],
        "lines": [{"sku": ln["sku"], "quantity": ln["quantity"]} for ln in o["lines"]],
        "status": o["status"],
        "shipping_class": o["shipping_class"],
        "handling_fee_cents": o["handling_fee_cents"],
        "discount_pct": o["discount_pct"],
        "goods_subtotal_cents": o["goods_subtotal_cents"],
        "total_cents": o["total_cents"],
        "total_quantity": o["total_quantity"],
        "allocation_score": (float(score) if score is not None else None),
        "submitted_at": fmt_dt(o["submitted_at"]),
        "shipped_at": fmt_dt(o["shipped_at"]),
        "delivered_at": fmt_dt(o["delivered_at"]),
        "created_at": fmt_dt(o["created_at"]),
        "updated_at": fmt_dt(o["updated_at"]),
        "version": o["version"],
    }


def surge_event_json(s):
    return {
        "id": s["id"],
        "allocation_group": s["allocation_group"],
        "reason": s["reason"],
        "status": s["status"],
        "started_at": fmt_dt(s["started_at"]),
        "resolved_at": fmt_dt(s["resolved_at"]),
        "created_at": fmt_dt(s["created_at"]),
        "updated_at": fmt_dt(s["updated_at"]),
        "version": s["version"],
    }

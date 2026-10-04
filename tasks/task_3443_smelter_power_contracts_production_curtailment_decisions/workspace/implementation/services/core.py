"""Derived state, lazy expiry transitions, and cross-entity selectors (PRD 2.4, 2.11)."""
from datetime import timedelta

from constants import (
    COLD_THRESHOLD_HOURS,
    CONTRACT_YEAR_DAYS,
    HEDGE_MIN_COVERAGE,
    MONTHLY_CAPACITY_DAYS,
    WARM_THRESHOLD_HOURS,
)
from db import STORE, bump, logical_clock
from util import D, next_month_start


# ---------- lazy expiry (PRD 2.4): each flip is a real mutation ----------

def lazy_expire_contract(contract):
    if contract["status"] == "ACTIVE" and logical_clock() >= contract["window_end"]:
        contract["status"] = "EXPIRED"
        bump(contract)


def lazy_expire_hedge(hedge):
    if hedge["status"] == "OPEN":
        year, month = hedge["delivery_ym"]
        if logical_clock() >= next_month_start(year, month):
            hedge["status"] = "EXPIRED"
            bump(hedge)


def lazy_expire_permit(permit):
    if permit["status"] == "ACTIVE" and logical_clock() >= permit["valid_to"]:
        permit["status"] = "EXPIRED"
        bump(permit)


def expire_contracts(smelter_id=None):
    for c in STORE["power_contracts"].values():
        if smelter_id is None or c["smelter_id"] == smelter_id:
            lazy_expire_contract(c)


def expire_hedges(smelter_id=None):
    for h in STORE["hedge_positions"].values():
        if smelter_id is None or h["smelter_id"] == smelter_id:
            lazy_expire_hedge(h)


def expire_permits(smelter_id=None):
    for p in STORE["environmental_permits"].values():
        if smelter_id is None or p["smelter_id"] == smelter_id:
            lazy_expire_permit(p)


# ---------- smelter derived fields (PRD 2.11) ----------

def potlines_of(smelter_id):
    return [p for p in STORE["potlines"].values() if p["smelter_id"] == smelter_id]


def smelter_posture(smelter_id):
    statuses = [p["operating_status"] for p in potlines_of(smelter_id)]
    if not statuses or all(s == "OPERATING" for s in statuses):
        return "FULL_OPERATION"
    if all(s == "SHUTDOWN" for s in statuses):
        return "SHUTDOWN"
    if not any(s in ("OPERATING", "RESTARTING") for s in statuses):
        return "FULL_CURTAILMENT"
    return "PARTIAL_CURTAILMENT"


def curtailed_capacity_tpd(smelter_id):
    total = D(0)
    for p in potlines_of(smelter_id):
        if p["operating_status"] in ("CURTAILED", "IDLE", "SHUTDOWN"):
            total += D(p["capacity_tpd"])
    return total


def open_hedged_tonnes(smelter_id):
    expire_hedges(smelter_id)
    total = D(0)
    for h in STORE["hedge_positions"].values():
        if h["smelter_id"] == smelter_id and h["status"] == "OPEN":
            total += D(h["volume_tonnes"])
    return total


def monthly_capacity(smelter):
    return D(smelter["rated_capacity_tpd"]) * MONTHLY_CAPACITY_DAYS


def hedge_coverage_ratio(smelter):
    """Unrounded Decimal ratio, used for gating; serializers round for display."""
    base = monthly_capacity(smelter)
    if base == 0:
        return D(0)
    return open_hedged_tonnes(smelter["id"]) / base


def coverage_sufficient(smelter):
    return hedge_coverage_ratio(smelter) >= HEDGE_MIN_COVERAGE


# ---------- potline restart cost class (PRD 2.11) ----------

def potline_restart_class(potline):
    status = potline["operating_status"]
    if status in ("OPERATING", "CURTAILED"):
        return "HOT"
    if status == "SHUTDOWN":
        return "COLD"
    if status == "IDLE":
        origin = potline.get("curtailed_since")
    else:  # RESTARTING: downtime keeps accruing from the origin captured at start
        origin = None
        for plan in STORE["restart_plans"].values():
            if plan["potline_id"] == potline["id"] and plan["status"] == "IN_PROGRESS":
                origin = plan.get("_origin")
                break
        if origin is None:
            origin = potline.get("curtailed_since")
    if origin is None:
        return "HOT"
    hours = (logical_clock() - origin).total_seconds() / 3600.0
    if hours < WARM_THRESHOLD_HOURS:
        return "HOT"
    if hours < COLD_THRESHOLD_HOURS:
        return "WARM"
    return "COLD"


# ---------- cross-entity selectors ----------

def covering_active_contract(smelter_id):
    expire_contracts(smelter_id)
    now = logical_clock()
    for c in STORE["power_contracts"].values():
        if (
            c["smelter_id"] == smelter_id
            and c["status"] == "ACTIVE"
            and c["window_start"] <= now < c["window_end"]
        ):
            return c
    return None


def active_labor_agreement(smelter_id):
    for a in STORE["labor_agreements"].values():
        if a["smelter_id"] == smelter_id and a["status"] == "ACTIVE":
            return a
    return None


def active_spl_permit_exists(smelter_id):
    expire_permits(smelter_id)
    for p in STORE["environmental_permits"].values():
        if (
            p["smelter_id"] == smelter_id
            and p["permit_type"] == "SPL_DISPOSAL"
            and p["status"] == "ACTIVE"
        ):
            return True
    return False


def contract_year_bounds(contract):
    """The 365-day window from the window_start anniversary containing the clock."""
    start = contract["window_start"]
    k = (logical_clock() - start).days // CONTRACT_YEAR_DAYS
    year_start = start + timedelta(days=CONTRACT_YEAR_DAYS * k)
    year_end = start + timedelta(days=CONTRACT_YEAR_DAYS * (k + 1))
    return year_start, year_end


def take_or_pay_exposed(contract):
    if contract["status"] != "ACTIVE":
        return False
    return smelter_posture(contract["smelter_id"]) in (
        "PARTIAL_CURTAILMENT",
        "FULL_CURTAILMENT",
        "SHUTDOWN",
    )

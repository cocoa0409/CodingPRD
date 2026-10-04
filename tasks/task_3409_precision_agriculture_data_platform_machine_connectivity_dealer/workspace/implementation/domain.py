"""Shared domain logic: records, derived fields, cascades, clock sweep, and
the calculations of the PRD (posture, usage, proration, uptime, payout,
license bundle fee)."""

import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from constants import (
    AGE_FULL_COVER_MAX_MONTHS,
    AGE_PARTIAL_COVER_MAX_MONTHS,
    BUNDLE_DISCOUNT_2,
    BUNDLE_DISCOUNT_3_PLUS,
    COVERAGE_FULL,
    COVERAGE_OLD,
    COVERAGE_PARTIAL,
    EXHAUST_AT_RATIO,
    LABOR_CAP_CENTS,
    LICENSE_BASE_FEE_CENTS,
    OVERHAUL_BELOW_PCT,
    PAYOUT_MAX_CENTS,
    SERVICE_BELOW_PCT,
    THROTTLE_AT_RATIO,
    TIER_CAP_MB,
    TIER_PRICE_CENTS,
    UPTIME_WINDOW_HOURS,
)
from db import STORES, TELEMETRY, iso, new_id, next_seq, now


# ---------------------------------------------------------------------------
# Record plumbing (PRD section 2.11 common fields)
# ---------------------------------------------------------------------------

def new_record(fields):
    t = now()
    r = dict(fields)
    r["id"] = new_id()
    r["created_at"] = t
    r["updated_at"] = t
    r["version"] = 1
    r["_seq"] = next_seq()
    return r


def touch(r):
    """Every mutation of a resource refreshes updated_at and bumps version,
    including cascade and derived-field mutations (PRD section 2.11)."""
    r["updated_at"] = now()
    r["version"] += 1


def serialize(r):
    out = {}
    for k, v in r.items():
        if k.startswith("_"):
            continue
        out[k] = v  # envelope JSON encoder handles datetime/date/Decimal
    return out


# ---------------------------------------------------------------------------
# Data plan usage and machine connectivity posture (PRD sections 2.5-2.6)
# ---------------------------------------------------------------------------

def machine_plan(machine_id):
    """The machine's unique plan in PENDING, ACTIVE or SUSPENDED (plans have
    no terminal state, so this is simply the machine's plan if one exists)."""
    for p in STORES["data_plans"].values():
        if p["machine_id"] == machine_id and p["status"] in ("PENDING", "ACTIVE", "SUSPENDED"):
            return p
    return None


def compute_usage_posture(plan):
    cap = TIER_CAP_MB[plan["tier"]]
    if cap is None:
        return "NORMAL"
    used = plan["used_mb"]
    if used >= Decimal(cap) * EXHAUST_AT_RATIO:
        return "EXHAUSTED"
    if used >= Decimal(cap) * THROTTLE_AT_RATIO:
        return "THROTTLED"
    return "NORMAL"


def compute_posture(machine):
    """Evaluation order is exactly as listed; first match wins."""
    if machine["modem_status"] != "PROVISIONED":
        return "OFFLINE"
    plan = machine_plan(machine["id"])
    if plan is None:
        return "NO_PLAN"
    if plan["status"] != "ACTIVE":
        return "PLAN_SUSPENDED"
    if plan["usage_posture"] == "EXHAUSTED":
        return "EXHAUSTED"
    if plan["usage_posture"] == "THROTTLED":
        return "THROTTLED"
    return "CONNECTED"


def recompute_posture(machine):
    p = compute_posture(machine)
    if machine["connectivity_posture"] != p:
        machine["connectivity_posture"] = p
        touch(machine)


def fail_downloading_deliveries(machine_id):
    for d in STORES["update_deliveries"].values():
        if d["machine_id"] == machine_id and d["status"] == "DOWNLOADING":
            d["status"] = "FAILED"
            d["failure_reason"] = "CONNECTIVITY_LOST"
            touch(d)


def cascade_plan_suspended(plan):
    machine = STORES["machines"].get(plan["machine_id"])
    if machine is None:
        return
    recompute_posture(machine)
    if machine["connectivity_posture"] == "PLAN_SUSPENDED":
        fail_downloading_deliveries(machine["id"])


def cascade_org_suspended(org):
    """PRD section 3.1: plans -> posture -> in-flight deliveries; plus grants
    and open sessions fan-out."""
    org_id = org["id"]
    for p in list(STORES["data_plans"].values()):
        if p["organization_id"] == org_id and p["status"] == "ACTIVE":
            p["status"] = "SUSPENDED"
            touch(p)
            cascade_plan_suspended(p)
    for g in list(STORES["data_share_grants"].values()):
        if g["organization_id"] == org_id and g["status"] == "ACTIVE":
            g["status"] = "SUSPENDED"
            touch(g)
    for s in list(STORES["diagnostic_sessions"].values()):
        if s["organization_id"] == org_id and s["status"] == "OPEN":
            s["status"] = "CLOSED"
            s["closed_at"] = now()
            s["closed_reason"] = "ACCESS_WITHDRAWN"
            touch(s)


def cascade_package_withdrawn(pkg):
    for d in list(STORES["update_deliveries"].values()):
        if d["package_id"] == pkg["id"] and d["status"] in ("AWAITING_CONSENT", "CONSENT_GRANTED"):
            d["status"] = "CANCELLED"
            touch(d)
            t = STORES["consent_tickets"].get(d["consent_ticket_id"])
            if t is not None and t["status"] in ("REQUESTED", "GRANTED"):
                t["status"] = "REVOKED"
                touch(t)


# ---------------------------------------------------------------------------
# Feature license count
# ---------------------------------------------------------------------------

def active_license_count(machine_id):
    n = 0
    for lic in STORES["feature_licenses"].values():
        if lic["machine_id"] == machine_id and lic["status"] in ("PURCHASED", "ACTIVATED", "SUSPENDED"):
            n += 1
    return n


def recompute_active_license_count(machine):
    n = active_license_count(machine["id"])
    if machine["active_license_count"] != n:
        machine["active_license_count"] = n
        touch(machine)


# ---------------------------------------------------------------------------
# Logical-clock sweep (PRD section 2.4): at-or-after semantics everywhere
# ---------------------------------------------------------------------------

def add_months(d, months):
    """Whole-month advance landing on the cycle anchor day, clamped to the
    target month's length."""
    m0 = d.month - 1 + months
    y = d.year + m0 // 12
    m = m0 % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


def add_months_dt(dt, months):
    d = add_months(dt.date(), months)
    return dt.replace(year=d.year, month=d.month, day=d.day)


def next_cycle_boundary(plan):
    cs = plan["cycle_start_date"]
    anchor = plan["cycle_anchor_day"]
    m = cs.month % 12 + 1
    y = cs.year + (1 if cs.month == 12 else 0)
    return date(y, m, min(anchor, calendar.monthrange(y, m)[1]))


def clock_sweep():
    t = now()
    today = t.date()
    for tk in list(STORES["consent_tickets"].values()):
        if tk["status"] in ("REQUESTED", "GRANTED") and t >= tk["expires_at"]:
            tk["status"] = "EXPIRED"
            touch(tk)
    for g in list(STORES["data_share_grants"].values()):
        if g["status"] in ("ACTIVE", "SUSPENDED") and t >= g["valid_until"]:
            g["status"] = "EXPIRED"
            touch(g)
    for lic in list(STORES["feature_licenses"].values()):
        if (
            lic["license_type"] == "TERM"
            and lic["status"] == "ACTIVATED"
            and lic["expires_at"] is not None
            and t >= lic["expires_at"]
        ):
            lic["status"] = "EXPIRED"
            touch(lic)
            m = STORES["machines"].get(lic["machine_id"])
            if m is not None:
                recompute_active_license_count(m)
    for p in list(STORES["integration_partners"].values()):
        if (
            p["status"] == "CERTIFIED"
            and p["certification_expires_on"] is not None
            and today >= p["certification_expires_on"]
        ):
            p["status"] = "EXPIRED"
            touch(p)
    # Billing-cycle rollovers
    for plan in list(STORES["data_plans"].values()):
        if plan["cycle_start_date"] is None:
            continue
        rolled = False
        while next_cycle_boundary(plan) <= today:
            plan["cycle_start_date"] = next_cycle_boundary(plan)
            plan["used_mb"] = Decimal(0)
            rolled = True
        if rolled:
            plan["usage_posture"] = compute_usage_posture(plan)
            touch(plan)
            m = STORES["machines"].get(plan["machine_id"])
            if m is not None:
                recompute_posture(m)
    # Partner daily counters reset when the UTC calendar date changes
    for p in list(STORES["integration_partners"].values()):
        if p["calls_window_date"] is not None and p["calls_window_date"] != today:
            p["calls_window_date"] = today
            p["calls_today"] = 0
            touch(p)


# ---------------------------------------------------------------------------
# Plan proration (calculations.plan_proration)
# ---------------------------------------------------------------------------

def compute_proration(plan, new_tier):
    delta = TIER_PRICE_CENTS[new_tier] - TIER_PRICE_CENTS[plan["tier"]]
    today = now().date()
    elapsed = max(0, (today - plan["cycle_start_date"]).days)
    if plan["proration_method"] == "CALENDAR_DAY":
        days_in_month = calendar.monthrange(today.year, today.month)[1]
        remaining = Decimal(days_in_month - today.day) / Decimal(days_in_month)
    else:  # THIRTY_DAY
        remaining = Decimal(max(0, 30 - elapsed)) / Decimal(30)
    charge = (Decimal(delta) * remaining).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(charge)


# ---------------------------------------------------------------------------
# Prescription product totals (calculations.prescription_product_totals)
# Per-zone rounding FIRST, then exact sum. Sum-then-round is explicitly not
# the rule.
# ---------------------------------------------------------------------------

def compute_prescription_totals(zones):
    zone_liters = [
        (Decimal(str(z["rate_l_per_ha"])) * Decimal(str(z["area_ha"]))).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        for z in zones
    ]
    total = sum(zone_liters, Decimal(0))
    total_area = sum((Decimal(str(z["area_ha"])) for z in zones), Decimal(0))
    avg = (total / total_area).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    return total, avg


# ---------------------------------------------------------------------------
# Uptime prediction + parts recommendation (calculations.uptime_prediction,
# calculations.parts_recommendation)
# ---------------------------------------------------------------------------

def compute_uptime(machine_id):
    t = now()
    window_start = (t - timedelta(hours=UPTIME_WINDOW_HOURS)).replace(
        minute=0, second=0, microsecond=0
    )
    filled = set()
    for rec in TELEMETRY.get(machine_id, {}).values():
        h = rec["start"].replace(minute=0, second=0, microsecond=0)
        idx = int((h - window_start).total_seconds() // 3600)
        for k in range(rec["hour_count"]):
            b = idx + k
            if 0 <= b < UPTIME_WINDOW_HOURS:
                filled.add(b)
    bridged = sum(
        1
        for b in range(1, UPTIME_WINDOW_HOURS)
        if b not in filled and (b - 1) in filled
    )
    conservative = (
        Decimal(100) * Decimal(len(filled)) / Decimal(UPTIME_WINDOW_HOURS)
    ).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    optimistic = (
        Decimal(100) * Decimal(len(filled) + bridged) / Decimal(UPTIME_WINDOW_HOURS)
    ).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return conservative, optimistic, len(filled), bridged


def parts_recommendation(conservative_score):
    if conservative_score < OVERHAUL_BELOW_PCT:
        return "OVERHAUL_KIT"
    if conservative_score < SERVICE_BELOW_PCT:
        return "SERVICE_KIT"
    return "NONE"


# ---------------------------------------------------------------------------
# Warranty payout waterfall (calculations.warranty_payout_allocation)
# ---------------------------------------------------------------------------

def age_months_floor(manufacture, today):
    months = (today.year - manufacture.year) * 12 + (today.month - manufacture.month)
    if today.day < manufacture.day:
        months -= 1
    return months


def compute_payout(claim, machine, dealer):
    age = age_months_floor(machine["manufacture_date"], now().date())
    if age <= AGE_FULL_COVER_MAX_MONTHS:
        pct = COVERAGE_FULL
    elif age <= AGE_PARTIAL_COVER_MAX_MONTHS:
        pct = COVERAGE_PARTIAL
    else:
        pct = COVERAGE_OLD
    covered_parts = int(
        (Decimal(claim["parts_amount_cents"]) * pct).to_integral_value(rounding=ROUND_FLOOR)
    )
    labor_cents = claim["claim_amount_cents"] - claim["parts_amount_cents"]
    labor_cap = LABOR_CAP_CENTS[dealer["service_tier"]]
    covered_labor = int(
        (Decimal(min(labor_cents, labor_cap)) * pct).to_integral_value(rounding=ROUND_FLOOR)
    )
    payout = min(claim["claim_amount_cents"], covered_parts + covered_labor, PAYOUT_MAX_CENTS)
    return pct, payout


# ---------------------------------------------------------------------------
# License bundle fee (calculations.license_bundle_fee). The count includes
# the license being purchased; evaluation order is part of the contract.
# ---------------------------------------------------------------------------

def compute_license_fee(machine_id, feature_code):
    n = active_license_count(machine_id) + 1
    if n == 1:
        discount = Decimal(0)
    elif n == 2:
        discount = BUNDLE_DISCOUNT_2
    else:
        discount = BUNDLE_DISCOUNT_3_PLUS
    base = LICENSE_BASE_FEE_CENTS[feature_code]
    fee = (Decimal(base) * (Decimal(1) - discount)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(fee)


# ---------------------------------------------------------------------------
# Partner data-pull record counts (interpretation: TELEMATICS -> machines,
# AGRONOMIC -> field boundaries + prescriptions, DIAGNOSTICS -> sessions)
# ---------------------------------------------------------------------------

def record_count(org_id, scope):
    if scope == "TELEMATICS":
        return sum(1 for m in STORES["machines"].values() if m["organization_id"] == org_id)
    if scope == "AGRONOMIC":
        return sum(
            1 for m in STORES["field_boundaries"].values() if m["organization_id"] == org_id
        ) + sum(1 for m in STORES["prescriptions"].values() if m["organization_id"] == org_id)
    return sum(1 for s in STORES["diagnostic_sessions"].values() if s["organization_id"] == org_id)

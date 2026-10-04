"""Domain computation helpers — pure functions mirroring PRD calculations.

These let tests compute expected values from the same PRD rules the
implementation must follow, instead of hard-coding magic numbers:
- bom_expand            (PRD §3.4 BOM expansion, exact integer arithmetic)
- module_unit_parts_cents
- queue_days_for_units  (PRD §2.8 queue tiers)
- configuration_lead_time (PRD §3.4: max module lead + queue days)
- tier_for_basis        (PRD §3.2 volume tiers)
- price_order           (PRD §3.5 seven-step pricing; variant picks the basis)
- business_age_days / escalated_expected (PRD §3.8 punch escalation)
- add_calendar_days     (date arithmetic for clock-driven fixtures)
"""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from .constants import (
    FABRIC_LEAD_DELTA_DAYS,
    FABRIC_UPCHARGE_PCT,
    MODULE_BOM_RULES,
    MODULE_CATEGORY,
    QUEUE_DAYS_LARGE,
    QUEUE_DAYS_MEDIUM,
    QUEUE_DAYS_SMALL,
    QUEUE_MEDIUM_MAX_UNITS,
    QUEUE_SMALL_MAX_UNITS,
    STORAGE_FABRIC_DELTA_DAYS,
    STORAGE_FABRIC_UPCHARGE_PCT,
    TIER2_MIN_CENTS,
    TIER3_MIN_CENTS,
    ESCALATION_BUSINESS_DAYS,
)


def _grade_value(module: dict):
    """fabric_grade as a plain string or None (accepts enums too)."""
    grade = module.get("fabric_grade")
    return getattr(grade, "value", grade)


def module_unit_parts_cents(module_type: str) -> int:
    """Exact per-unit parts total of a module type (PRD §2.7 bullets)."""
    rule = MODULE_BOM_RULES[module_type]
    return sum(qty * price for qty, price in rule.values())


def bom_expand(modules: list) -> dict:
    """PRD §3.4: merge parts across module entries by part_number, sort
    ascending; exact integer arithmetic.

    Pricing follows each module type's own recipe (PRD §2.7 pins per-unit
    module totals — e.g. 85837c for WORKSTATION_6X6, 180737c for
    PRIVATE_OFFICE): a line's extended_cents is the SUM of each contributing
    module entry's qty x its recipe price. This matters for PN-WRK-SRF, which
    the catalog prices at 15800c in workstation recipes and 21500c in the
    private-office recipe. unit_list_price_cents is the shared price when all
    contributions agree, else None (the PRD does not pin one display price
    for a divergent shared part).
    Returns {"lines": [...], "parts_total_cents": int, "total_units": int}."""
    merged = {}
    for module in modules:
        mtype = module["module_type"]
        qty = module["qty"]
        for part_number, (per_unit, price) in MODULE_BOM_RULES[mtype].items():
            entry = merged.setdefault(
                part_number, {"total_qty": 0, "extended_cents": 0, "prices": set()}
            )
            entry["total_qty"] += per_unit * qty
            entry["extended_cents"] += per_unit * qty * price
            entry["prices"].add(price)
    lines = []
    for part_number in sorted(merged):
        entry = merged[part_number]
        lines.append({
            "part_number": part_number,
            "total_qty": entry["total_qty"],
            "unit_list_price_cents": (
                next(iter(entry["prices"])) if len(entry["prices"]) == 1 else None
            ),
            "extended_cents": entry["extended_cents"],
        })
    return {
        "lines": lines,
        "parts_total_cents": sum(line["extended_cents"] for line in lines),
        "total_units": sum(m["qty"] for m in modules),
    }


def queue_days_for_units(total_units: int) -> int:
    """PRD §2.8: <=49 -> 3; 50..199 -> 7; >=200 -> 12 (upper bounds inclusive)."""
    if total_units <= QUEUE_SMALL_MAX_UNITS:
        return QUEUE_DAYS_SMALL
    if total_units <= QUEUE_MEDIUM_MAX_UNITS:
        return QUEUE_DAYS_MEDIUM
    return QUEUE_DAYS_LARGE


def configuration_lead_time(modules: list, base_lead_by_category: dict) -> int:
    """PRD §3.4: max over modules of (family base lead + fabric delta), plus
    the queue tier keyed on the configuration's total_units.
    base_lead_by_category maps e.g. {"SYSTEMS": 42, "SEATING": 28, ...}."""
    best = 0
    for module in modules:
        category = MODULE_CATEGORY[module["module_type"]]
        grade = _grade_value(module)
        delta = (
            STORAGE_FABRIC_DELTA_DAYS if grade is None
            else FABRIC_LEAD_DELTA_DAYS[grade]
        )
        best = max(best, base_lead_by_category[category] + delta)
    total_units = sum(m["qty"] for m in modules)
    return best + queue_days_for_units(total_units)


def tier_for_basis(basis_cents: int) -> int:
    """PRD §3.2: tier 1 below 25000000, tier 2 from 25000000 up to but not
    including 75000000, tier 3 from 75000000. Lower edges inclusive."""
    if basis_cents < TIER2_MIN_CENTS:
        return 1
    if basis_cents < TIER3_MIN_CENTS:
        return 2
    return 3


def _discount_for_tier(agreement: dict, tier: int) -> Decimal:
    return Decimal(str(agreement[f"tier{tier}_discount_pct"]))


def price_order(modules: list, agreement: dict, tier_basis_cents: int) -> dict:
    """PRD §3.5 seven-step pricing, round-half-up exactly twice.

    tier_basis_cents is the variant selector:
    - PROVISIONAL: agreement cumulative volume EXCLUDING this order;
    - FINAL: cumulative volume INCLUDING this order's pre-discount total.
    Returns {"pre_discount_total_cents", "tier", "discount_pct", "total_cents"}.
    """
    pre_discount = 0
    for module in modules:
        unit_parts = module_unit_parts_cents(module["module_type"])
        grade = _grade_value(module)
        pct = (
            STORAGE_FABRIC_UPCHARGE_PCT if grade is None
            else FABRIC_UPCHARGE_PCT[grade]
        )
        unit_exact = Decimal(unit_parts) * (Decimal(100 + pct) / Decimal(100))
        line_exact = unit_exact * module["qty"]
        line_cents = int(line_exact.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        pre_discount += line_cents
    tier = tier_for_basis(tier_basis_cents)
    discount = _discount_for_tier(agreement, tier)
    total = int(
        (Decimal(pre_discount) * (Decimal(1) - discount)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    return {
        "pre_discount_total_cents": pre_discount,
        "tier": tier,
        "discount_pct": float(discount),
        "total_cents": total,
    }


def add_calendar_days(date_iso: str, days: int) -> str:
    """Add whole days to an ISO YYYY-MM-DD date; returns ISO date."""
    y, m, d = (int(part) for part in date_iso[:10].split("-"))
    return (date(y, m, d) + timedelta(days=days)).isoformat()


def business_age_days(created_date_iso: str, clock_date_iso: str) -> int:
    """PRD §3.8: count of dates d with created_date < d <= clock_date whose
    weekday is Monday..Friday (no holiday calendar)."""
    cy, cm, cd = (int(part) for part in created_date_iso[:10].split("-"))
    ky, km, kd = (int(part) for part in clock_date_iso[:10].split("-"))
    start = date(cy, cm, cd)
    end = date(ky, km, kd)
    count = 0
    current = start
    while current < end:
        current += timedelta(days=1)
        if current.weekday() < 5:
            count += 1
    return count


def escalated_expected(status: str, created_date_iso: str, clock_date_iso: str) -> bool:
    """PRD §3.8: escalated is true while the ticket is OPEN and its business
    age is at least 5 (the boundary is inclusive)."""
    return (
        status == "OPEN"
        and business_age_days(created_date_iso, clock_date_iso) >= ESCALATION_BUSINESS_DAYS
    )

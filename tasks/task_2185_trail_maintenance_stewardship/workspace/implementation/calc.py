"""Calculation rules (PRD sections 2.9, 3.4, 3.7, 3.8).

All rounding is round-half-up.  Money is integer cents; hours are quantised to
quarter hours per shift before any aggregate sums them.
"""

import math
from decimal import Decimal, ROUND_HALF_UP

# --- condition_report_priority_score ---------------------------------------
SEVERITY_BASE = {"LOW": 20, "MODERATE": 50, "HIGH": 80, "CRITICAL": 100}
EXPOSURE_MULT = {"LOW": Decimal("0.8"), "MEDIUM": Decimal("1.0"), "HIGH": Decimal("1.25")}
TRAFFIC_MULT = {"LIGHT": Decimal("0.9"), "MODERATE": Decimal("1.0"), "HEAVY": Decimal("1.15")}
AGE_BONUS_PER_WEEK = 3
AGE_BONUS_CAP = 15
WET_SURCHARGE = 8
ESCALATION_THRESHOLD = 70

# --- segment_hazard_index ---------------------------------------------------
HAZARD_DIVISOR = Decimal(3)
ESCALATION_OVERRIDE_COUNT = 2
HAZARD_RESTRICT_THRESHOLD = 60
HAZARD_WEIGHT = {
    "TRIAGED": Decimal("1.0"),
    "SCHEDULED": Decimal("1.0"),
    "DEFERRED": Decimal("0.5"),
    "ESCALATED": Decimal("1.5"),
}
HAZARD_INCLUDED_STATUSES = ("TRIAGED", "SCHEDULED", "DEFERRED", "ESCALATED")

# --- shift_credited_hours ---------------------------------------------------
BREAK_THRESHOLD_MIN = 240
BREAK_MINUTES = 30
TRAVEL_CAP_MIN = 60
QUARTER_HOUR_MINUTES = 15

# --- material_order_total_cents --------------------------------------------
DISCOUNT_TIER_1_CENTS = 50000
DISCOUNT_TIER_2_CENTS = 250000
FREIGHT_FREE_THRESHOLD_CENTS = 200000
FREIGHT_BASE_CENTS = 4500
FREIGHT_RATE = Decimal("0.02")
BRIDGE_SURCHARGE_RATE = Decimal("0.06")

# --- work_plan_budget_ledger ------------------------------------------------
TIGHT_RATIO = Decimal("0.20")
OVERCOMMIT_CAP_RATIO = Decimal("1.20")

# --- grant_match_value_usd --------------------------------------------------
SKILL_RATE_USD = {
    "GENERAL": Decimal("28.54"),
    "SKILLED_TRAIL": Decimal("41.20"),
    "CERTIFIED_SAWYER": Decimal("63.75"),
    "PROFESSIONAL": Decimal("89.00"),
}

# --- roster / safety constants ---------------------------------------------
FIRST_AID_RATIO = 8
SEGMENT_BUFFER_MINUTES = 60
MAX_DAILY_SHIFT_HOURS = 10
MAX_REVISION_ROUNDS = 3
MOISTURE_FRESH_HOURS = 72

WORK_TYPES = ("TREAD_WORK", "CHAINSAW", "BRIDGE_CONSTRUCTION", "SIGNAGE", "BRUSHING", "DRY_WORK")
CERTIFICATIONS = ("CERT_FIRST_AID", "CERT_WFA", "CERT_SAWYER_B", "CERT_SAWYER_C",
                  "CERT_TRAIL_SKILLS", "CERT_ENGINEER", "CERT_CREW_LEADER")
FIRST_AID_CERTS = ("CERT_FIRST_AID", "CERT_WFA")
SAWYER_CERTS = ("CERT_SAWYER_B", "CERT_SAWYER_C")
WET_ALLOWED_WORK_TYPES = ("SIGNAGE", "DRY_WORK")


def round_half_up(value, places=0):
    quant = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(round_half_up(value, 0))


def money(value):
    """Return a USD figure as a float with two decimal places."""
    return float(round_half_up(value, 2))


def dec(value):
    return Decimal(str(value))


# ---------------------------------------------------------------------------
# skill class
# ---------------------------------------------------------------------------
def skill_class(certifications):
    certs = set(certifications or [])
    if "CERT_ENGINEER" in certs:
        return "PROFESSIONAL"
    if certs & set(SAWYER_CERTS):
        return "CERTIFIED_SAWYER"
    if certs & {"CERT_TRAIL_SKILLS", "CERT_CREW_LEADER"}:
        return "SKILLED_TRAIL"
    return "GENERAL"


# ---------------------------------------------------------------------------
# condition_report_priority_score
# ---------------------------------------------------------------------------
def priority_score(severity_class, exposure_class, traffic_class_snapshot,
                   age_days=0, wet=False, variant="INITIAL_TRIAGE"):
    base = Decimal(SEVERITY_BASE[severity_class])
    weighted = base * EXPOSURE_MULT[exposure_class] * TRAFFIC_MULT[traffic_class_snapshot]
    if variant == "INITIAL_TRIAGE":
        age_bonus = 0
        wet_surcharge = 0
    else:
        age_bonus = min(AGE_BONUS_CAP, (int(age_days) // 7) * AGE_BONUS_PER_WEEK)
        wet_surcharge = WET_SURCHARGE if wet else 0
    raw = weighted + Decimal(age_bonus) + Decimal(wet_surcharge)
    return min(100, rhu_int(raw))


# ---------------------------------------------------------------------------
# segment_hazard_index
# ---------------------------------------------------------------------------
def hazard_index(included_reports):
    total = Decimal(0)
    escalated = 0
    for report in included_reports:
        total += Decimal(report["priority_score"]) * HAZARD_WEIGHT[report["status"]]
        if report["status"] == "ESCALATED":
            escalated += 1
    value = min(100, rhu_int(total / HAZARD_DIVISOR))
    if escalated >= ESCALATION_OVERRIDE_COUNT:
        value = 100
    return value, escalated


# ---------------------------------------------------------------------------
# shift_credited_hours
# ---------------------------------------------------------------------------
def credited_hours(checked_in_at, checked_out_at, travel_allowance_minutes):
    worked = int(math.floor((checked_out_at - checked_in_at).total_seconds() / 60.0))
    if worked < 0:
        worked = 0
    break_minutes = BREAK_MINUTES if worked >= BREAK_THRESHOLD_MIN else 0
    travel = min(TRAVEL_CAP_MIN, int(travel_allowance_minutes or 0))
    billable = max(0, worked - break_minutes) + travel
    quarter_units = rhu_int(Decimal(billable) / Decimal(QUARTER_HOUR_MINUTES))
    hours = float(round_half_up(Decimal(quarter_units) * Decimal("0.25"), 2))
    return worked, billable, hours


# ---------------------------------------------------------------------------
# material_order_total_cents
# ---------------------------------------------------------------------------
def price_material_order(lines, category):
    line_subtotal = sum(int(l["unit_price_cents"]) * int(l["quantity"]) for l in lines)
    if line_subtotal < DISCOUNT_TIER_1_CENTS:
        discount_pct = Decimal("0.00")
    elif line_subtotal < DISCOUNT_TIER_2_CENTS:
        discount_pct = Decimal("0.04")
    else:
        discount_pct = Decimal("0.07")
    discount_cents = rhu_int(Decimal(line_subtotal) * discount_pct)
    discounted_subtotal = line_subtotal - discount_cents
    if discounted_subtotal >= FREIGHT_FREE_THRESHOLD_CENTS:
        freight = 0
    else:
        freight = FREIGHT_BASE_CENTS + rhu_int(Decimal(discounted_subtotal) * FREIGHT_RATE)
    if category == "BRIDGE":
        surcharge = rhu_int(Decimal(discounted_subtotal) * BRIDGE_SURCHARGE_RATE)
    else:
        surcharge = 0
    total = discounted_subtotal + freight + surcharge
    return {
        "line_subtotal_cents": line_subtotal,
        "discount_pct": float(discount_pct),
        "discount_cents": discount_cents,
        "discounted_subtotal_cents": discounted_subtotal,
        "freight_cents": freight,
        "bridge_surcharge_cents": surcharge,
        "total_cents": total,
    }


def budget_posture(available_cents, approved_budget_cents):
    if available_cents < 0:
        return "OVER_COMMITTED"
    if available_cents == 0:
        return "EXHAUSTED"
    tight_floor = rhu_int(Decimal(approved_budget_cents) * TIGHT_RATIO)
    if 0 < available_cents < tight_floor:
        return "TIGHT"
    return "HEALTHY"


def overcommit_cap(approved_budget_cents):
    return rhu_int(Decimal(approved_budget_cents) * OVERCOMMIT_CAP_RATIO)


# ---------------------------------------------------------------------------
# grant_match_value_usd
# ---------------------------------------------------------------------------
PROVISIONAL_STATUSES = ("CHECKED_OUT", "HOURS_DISPUTED", "HOURS_VERIFIED", "HOURS_CERTIFIED")


def grant_match(variant, included_shifts, delivered_total_cents):
    total_hours = Decimal(0)
    for shift in included_shifts:
        total_hours += dec(shift["credited_hours"])
    if variant == "PROVISIONAL":
        labor = round_half_up(total_hours * SKILL_RATE_USD["GENERAL"], 2)
        material = Decimal("0.00")
    else:
        labor = Decimal("0.00")
        for shift in included_shifts:
            rate = SKILL_RATE_USD.get(shift.get("skill_class_snapshot") or "GENERAL")
            labor += round_half_up(dec(shift["credited_hours"]) * rate, 2)
        labor = round_half_up(labor, 2)
        material = round_half_up(Decimal(delivered_total_cents) / Decimal(100), 2)
    grand = round_half_up(labor + material, 2)
    if total_hours == 0:
        average = Decimal("0.00")
    else:
        average = round_half_up(labor / total_hours, 2)
    return {
        "variant": variant,
        "included_shift_count": len(included_shifts),
        "total_credited_hours": float(round_half_up(total_hours, 2)),
        "labor_match_usd": float(labor),
        "material_match_usd": float(material),
        "grant_match_total_usd": float(grand),
        "average_rate_usd": float(average),
    }


def sum_hours(values):
    """Sum already-quantised per-shift hour values without re-quantising."""
    total = Decimal(0)
    for value in values:
        total += dec(value)
    return float(round_half_up(total, 2))


def add_hours(current, delta):
    return float(round_half_up(dec(current) + dec(delta), 2))

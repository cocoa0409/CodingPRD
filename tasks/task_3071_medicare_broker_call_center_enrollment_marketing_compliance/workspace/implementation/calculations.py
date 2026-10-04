"""Pure calculation rules from PRD Section 3 (and the scaffold calculation table).

Every monetary computation is carried out in exact Decimal arithmetic with
round-half-up applied at the point the specification pins it.
"""

import math
from decimal import Decimal, ROUND_HALF_UP

CENTS = Decimal("0.01")
MICRO = Decimal("0.000001")

FORWARD_WINDOW_DAYS = 365
METHOD_FEE_MULTIPLIER = Decimal("1.06")
LAPSE_GAP_DAYS = 0
DAYS_SUPPLY_RATIO_MULTIPLIER = Decimal("1.05")
DAYS_PER_FILL = 30
RENEWAL_ADJUSTMENT_MONTHS = Decimal("1")

DAY_BANDS = [
    {"name": "DAY_0_30", "min_day": 0, "max_day": 30, "base_pct": Decimal("1.00"), "penalty_points": 10},
    {"name": "DAY_31_60", "min_day": 31, "max_day": 60, "base_pct": Decimal("0.75"), "penalty_points": 15},
    {"name": "DAY_61_90", "min_day": 61, "max_day": 90, "base_pct": Decimal("0.50"), "penalty_points": 20},
]
ESCALATION_TIER_THRESHOLD = 4
HARD_ESCALATION_TIER_THRESHOLD = 7
ESCALATION_COMPLAINT_WINDOW_DAYS = 30

POSTURE_FREEZE_STRIKES = 5
POSTURE_FREEZE_LOSS_RATIO = Decimal("0.20")
POSTURE_RESTRICT_THRESHOLD = Decimal("0.05")
POSTURE_STRIKE_WINDOW_DAYS = 365
POSTURE_OVERDUE_COACHING_DAYS = 1

RISK_WINDOW_DAYS = 365
SESSION_RECORDING_PENALTY = Decimal("3.0")
SESSION_DISCLAIMER_PENALTY = Decimal("7.0")
SESSION_SCOPE_PENALTY = Decimal("2.0")
RAPID_DISENROLLMENT_PENALTY = Decimal("10.0")
COMPLAINT_SEVERITY_POINTS = {
    "LOW": Decimal("8.0"),
    "MEDIUM": Decimal("16.0"),
    "HIGH": Decimal("24.0"),
}
COACHING_ASSIGNMENT_POINTS = Decimal("5.0")
OVERDUE_DAY_POINTS = Decimal("3.0")

WEIGHT_PLAN_TYPE = Decimal("10")
WEIGHT_STAR = Decimal("12")
WEIGHT_PHARMACY = Decimal("8")
WEIGHT_PROVIDER = Decimal("15")
WEIGHT_COST = Decimal("1.0")
COST_DIVISOR_CENTS = Decimal("100")

COACHING_DUE_DAYS = 14
SHOPPER_SCORE_FLOOR = 70

PLAN_TYPES = {"MA", "MAPD", "PDP", "SNP"}


def dec(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def r2(value):
    """Round to 2 decimal places, half up."""
    return dec(value).quantize(CENTS, rounding=ROUND_HALF_UP)


def r6(value):
    """Round to 6 decimal places, half up."""
    return dec(value).quantize(MICRO, rounding=ROUND_HALF_UP)


def num(value):
    """JSON-safe rendering of a Decimal (or passthrough for plain numbers)."""
    if isinstance(value, Decimal):
        return float(value)
    return value


# ---------------------------------------------------------------------------
# Ledger amounts (PRD 3.8 / commission_ledger_entry)
# ---------------------------------------------------------------------------

def annual_initial(plan, carrier):
    return r2(dec(plan["monthly_premium_cents"]) * 12 * dec(carrier["initial_commission_rate_pct"]))


def annual_renewal(plan, carrier):
    return r2(dec(plan["monthly_premium_cents"]) * 12 * dec(carrier["renewal_commission_rate_pct"]))


def chargeback_amount(plan, carrier, pct):
    return -r2(annual_initial(plan, carrier) * dec(pct))


def default_adjustment_amount(plan, carrier):
    return r2(dec(plan["monthly_premium_cents"]) * RENEWAL_ADJUSTMENT_MONTHS
              * dec(carrier["renewal_commission_rate_pct"]))


# ---------------------------------------------------------------------------
# Rapid disenrollment chargeback (PRD 3.7)
# ---------------------------------------------------------------------------

def band_for_day(day_number):
    """The single DAY_BANDS row containing the day number, or None."""
    for band in DAY_BANDS:
        if band["min_day"] <= day_number <= band["max_day"]:
            return band
    return None


def selected_chargeback_pct(day_number, chargeback_tier, recent_substantiated_count):
    """Pinned evaluation order: band lookup, hard escalation, tier escalation,
    complaint escalation. Returns None when the day number is outside every
    band, meaning no chargeback is posted."""
    band = band_for_day(day_number)
    if band is None:
        return None
    base_pct = band["base_pct"]
    if chargeback_tier >= HARD_ESCALATION_TIER_THRESHOLD:
        base_pct = Decimal("1.00")
    elif chargeback_tier >= ESCALATION_TIER_THRESHOLD:
        index = DAY_BANDS.index(band)
        if index + 1 < len(DAY_BANDS):
            base_pct = DAY_BANDS[index + 1]["base_pct"]
        else:
            base_pct = Decimal("1.00")
    if recent_substantiated_count >= 2 and day_number <= 90:
        base_pct = Decimal("1.00")
    return base_pct


# ---------------------------------------------------------------------------
# Forward-looking and chronological commission projections (PRD 3.5)
# ---------------------------------------------------------------------------

def fill_months_first_year(effective_date):
    """12 minus the whole calendar months from effective_date to 31 December of
    that same year, counting the effective month itself."""
    months_including = 12 - effective_date.month + 1
    return 12 - months_including


def provisional_terms(plan, carrier, effective_date):
    """The two rounded terms a single enrollment contributes to the
    forward-looking projection."""
    initial_term = r2(dec(plan["monthly_premium_cents"]) * 12
                      * dec(carrier["initial_commission_rate_pct"]))
    renewal_term = r2(dec(plan["monthly_premium_cents"]) * fill_months_first_year(effective_date)
                      * dec(carrier["renewal_commission_rate_pct"]))
    return initial_term, renewal_term


def provisional_commission_cents(plan, carrier, effective_date):
    initial_term, renewal_term = provisional_terms(plan, carrier, effective_date)
    return initial_term + renewal_term


# ---------------------------------------------------------------------------
# Plan comparison (PRD 3.4)
# ---------------------------------------------------------------------------

def drug_annual_cost_cents(member_drug, formulary_rows):
    """Returns (status, cost_cents) where status is COVERED / NOT_COVERED."""
    matching = [
        row for row in formulary_rows
        if row.get("rxcui") == member_drug.get("rxcui")
        or row.get("drug_name") == member_drug.get("drug_name")
    ]
    covered_rows = [row for row in matching if row.get("covered", True)]
    if not covered_rows:
        return "NOT_COVERED", Decimal("0.00")
    covered_rows.sort(key=lambda r: (r["tier"], r["monthly_copay_cents"], r["_seq"]))
    row = covered_rows[0]
    monthly_fills = dec(member_drug.get("monthly_fills", 0))
    quantity_limit_days = dec(row.get("quantity_limit_days", DAYS_PER_FILL)) or Decimal(DAYS_PER_FILL)
    fills = math.ceil(monthly_fills * DAYS_PER_FILL / quantity_limit_days)
    cost = r2(dec(fills) * dec(row["monthly_copay_cents"]) * DAYS_SUPPLY_RATIO_MULTIPLIER)
    return "COVERED", cost


def plan_out_of_pocket_cents(plan, drug_costs):
    total = (dec(plan["monthly_premium_cents"]) * 12) + dec(plan["annual_drug_deductible_cents"])
    for cost in drug_costs:
        total += cost
    return total


def composite_score(plan_type_affinity_match, star_rating, pharmacy_component,
                    provider_ratio, out_of_pocket_cents):
    terms = [
        r2(WEIGHT_PLAN_TYPE * dec(plan_type_affinity_match)),
        r2(WEIGHT_STAR * dec(star_rating)),
        r2(WEIGHT_PHARMACY * dec(pharmacy_component)),
        r2(WEIGHT_PROVIDER * dec(provider_ratio)),
        r2(WEIGHT_COST * max(Decimal("0"), Decimal("1000") - dec(out_of_pocket_cents) / COST_DIVISOR_CENTS)),
    ]
    total = Decimal("0.00")
    for term in terms:
        total += term
    return r2(total)


# ---------------------------------------------------------------------------
# Complaint finding codes (PRD 3.9)
# ---------------------------------------------------------------------------

def finding_code(complaint):
    source = complaint.get("source")
    if source == "SECRET_SHOPPER":
        if complaint.get("soa_requested_correctly") is False:
            return "SHOPPER_SOA_FAILURE"
        if complaint.get("disclaimer_played") is False:
            return "SHOPPER_DISCLAIMER_FAILURE"
        if complaint.get("approved_marketing_used") is False:
            return "SHOPPER_MARKETING_FAILURE"
        score = complaint.get("shopper_score")
        if score is not None and score < SHOPPER_SCORE_FLOOR:
            return "SHOPPER_LOW_SCORE"
    ctype = complaint.get("complaint_type")
    if ctype in ("SOA_MISSING", "DISENROLLMENT_DELAY"):
        return "SOA_VIOLATION"
    if ctype == "DISCLAIMER_MISSING":
        return "DISCLAIMER_VIOLATION"
    if ctype in ("UNAPPROVED_MARKETING", "MISREPRESENTATION", "PLAN_MISREPRESENTATION"):
        return "MARKETING_VIOLATION"
    if ctype == "RECORDING_MISSING":
        return "RECORDING_VIOLATION"
    return "GENERAL_FINDING"
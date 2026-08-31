"""Calculation rules (PRD 3.2, 3.3, 3.5, 3.6, 3.7, 3.8, 3.9 / SCAFFOLD Table 3).

All monetary values are integer cents.  Every fractional result is rounded
half up.  Risk scoring and rank scoring are pure integer arithmetic.
"""

from decimal import Decimal, ROUND_HALF_UP

# --- composite_readmission_risk_score -------------------------------------
PRIOR_ADMIT_CAP = 4
PRIOR_ADMIT_POINTS = 8
FUNCTIONAL_WEIGHT = 3
COGNITIVE_WEIGHT = 2
SOCIAL_WEIGHT = 2
LIVES_ALONE_POINTS = 6
NO_PCP_POINTS = 5
POLYPHARMACY_THRESHOLD = 10
POLYPHARMACY_POINTS = 7
BARRIER_HISTORY_CAP = 5
BARRIER_HISTORY_POINTS = 3
PLACEMENT_CREDIT_POINTS = 12

# --- barrier_posture_rollup ----------------------------------------------
ESCALATION_HOURS = 72

# --- placement_cost_projection / authorization_award ----------------------
OUT_OF_NETWORK_MULTIPLIER = Decimal("1.25")
TIER1_DAYS = 20
TIER2_RATE_PCT = Decimal("0.85")
VOLUME_TIER1_CENTS = 500000
VOLUME_TIER2_CENTS = 1500000

# --- bed_offer_rank_score -------------------------------------------------
STAR_WEIGHT = 10
IN_NETWORK_BONUS = 25
PROXIMITY_BASE = 20
COST_PENALTY_DIVISOR = 5000

# --- referral fairness ----------------------------------------------------
MIN_BROADCAST_PROVIDERS = 3

# --- appeals --------------------------------------------------------------
MAX_APPEAL_ROUNDS = 2

# --- logistics ------------------------------------------------------------
TURNAROUND_BUFFER_MINUTES = 45
DME_ITEM_RATE_CENTS = {
    "HOSPITAL_BED": 45000,
    "OXYGEN_CONCENTRATOR": 32000,
    "WHEELCHAIR": 21000,
    "WALKER": 8000,
    "CPAP": 27000,
}

# --- throughput -----------------------------------------------------------
ACUITY_MULTIPLIER = {
    "LOW": Decimal("0.90"),
    "MODERATE": Decimal("1.00"),
    "HIGH": Decimal("1.15"),
    "VERY_HIGH": Decimal("1.30"),
}


# --------------------------------------------------------------------------
# rounding helpers
# --------------------------------------------------------------------------
def round_half_up(value, places):
    quant = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def cents(value):
    """Round a Decimal amount half up to whole cents."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def one_dp(value):
    return float(round_half_up(value, 1))


def three_dp(value):
    return float(round_half_up(value, 3))


# --------------------------------------------------------------------------
# composite readmission risk score (PRD 3.2)
# --------------------------------------------------------------------------
def risk_base(prior_admissions, functional, cognitive, social, lives_alone,
              has_pcp, medication_count):
    base = min(prior_admissions, PRIOR_ADMIT_CAP) * PRIOR_ADMIT_POINTS
    base += (10 - functional) * FUNCTIONAL_WEIGHT
    base += (10 - cognitive) * COGNITIVE_WEIGHT
    base += (10 - social) * SOCIAL_WEIGHT
    if lives_alone:
        base += LIVES_ALONE_POINTS
    if not has_pcp:
        base += NO_PCP_POINTS
    if medication_count >= POLYPHARMACY_THRESHOLD:
        base += POLYPHARMACY_POINTS
    return base


def risk_adjust(variant, barriers_ever_opened_count, has_institutional_placement):
    if variant != "PREDISCHARGE_VARIANT":
        return 0
    adjust = min(barriers_ever_opened_count, BARRIER_HISTORY_CAP) * BARRIER_HISTORY_POINTS
    if has_institutional_placement:
        adjust -= PLACEMENT_CREDIT_POINTS
    return adjust


def risk_band(score):
    if score >= 70:
        return "VERY_HIGH"
    if score >= 50:
        return "HIGH"
    if score >= 30:
        return "MODERATE"
    return "LOW"


def composite_risk(screening, variant, barriers_ever_opened_count,
                   has_institutional_placement):
    base = risk_base(
        screening["prior_admissions_snapshot"],
        screening["functional_score"],
        screening["cognitive_score"],
        screening["social_support_score"],
        screening["lives_alone_snapshot"],
        screening["has_pcp_snapshot"],
        screening["medication_count"],
    )
    adjust = risk_adjust(variant, barriers_ever_opened_count, has_institutional_placement)
    score = base + adjust
    if score < 0:
        score = 0
    if score > 100:
        score = 100
    return score, risk_band(score)


# --------------------------------------------------------------------------
# readmission bundle (PRD 3.8)
# --------------------------------------------------------------------------
REQUIRED_FLAGS = {
    "LOW": (),
    "MODERATE": ("pcp_followup_booked",),
    "HIGH": ("pcp_followup_booked", "med_reconciliation_completed"),
    "VERY_HIGH": ("pcp_followup_booked", "med_reconciliation_completed",
                  "tcm_call_scheduled", "home_monitoring_enrolled"),
}


def bundle_complete(episode, band):
    for flag in REQUIRED_FLAGS.get(band, ()):
        if not episode.get(flag):
            return False
    return True


# --------------------------------------------------------------------------
# avoidable delay union (PRD 3.3)
# --------------------------------------------------------------------------
def merge_intervals(intervals):
    """intervals: list of (start, end) aware datetimes; returns merged list."""
    ordered = sorted(intervals, key=lambda iv: (iv[0], iv[1]))
    merged = []
    for start, end in ordered:
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1][1] = end
        else:
            merged.append([start, end])
    return merged


def union_minutes(intervals):
    total = 0
    for start, end in merge_intervals(intervals):
        total += int((end - start).total_seconds() // 60)
    return total


# --------------------------------------------------------------------------
# placement cost projection (PRD 3.5)
# --------------------------------------------------------------------------
def raw_daily_rate(contract, billed_rate_cents):
    if contract is not None and contract.get("in_network"):
        return "NETWORK_RATE", int(contract["negotiated_daily_rate_cents"])
    return "BILLED_RATE", cents(Decimal(billed_rate_cents) * OUT_OF_NETWORK_MULTIPLIER)


def placement_projection(contract, offer_daily_rate_cents, covered_days, coinsurance_pct):
    variant, raw = raw_daily_rate(contract, offer_daily_rate_cents)
    tier2_day = cents(Decimal(raw) * TIER2_RATE_PCT)
    gross = 0
    for day in range(1, max(0, covered_days) + 1):
        gross += raw if day <= TIER1_DAYS else tier2_day
    patient = cents(Decimal(gross) * Decimal(str(coinsurance_pct)))
    return {
        "rate_variant_applied": variant,
        "projected_gross_cents": gross,
        "projected_patient_share_cents": patient,
        "projected_plan_share_cents": gross - patient,
    }


# --------------------------------------------------------------------------
# authorization award (PRD 3.6)
# --------------------------------------------------------------------------
def authorization_award(contract, billed_daily_rate_cents, approved_days):
    variant, raw = raw_daily_rate(contract, billed_daily_rate_cents)
    gross = raw * int(approved_days)
    if gross >= VOLUME_TIER2_CENTS:
        discount = Decimal("0.05")
    elif gross >= VOLUME_TIER1_CENTS:
        discount = Decimal("0.03")
    else:
        discount = Decimal("0.00")
    authorized = gross - cents(Decimal(gross) * discount)
    return {
        "rate_variant_applied": variant,
        "gross_projection_cents": gross,
        "volume_discount_pct": float(discount),
        "authorized_amount_cents": authorized,
    }


# --------------------------------------------------------------------------
# bed offer rank score (PRD 3.5)
# --------------------------------------------------------------------------
def rank_score(provider, offer_daily_rate_cents, in_network):
    score = int(provider["quality_star_rating"]) * STAR_WEIGHT
    if in_network:
        score += IN_NETWORK_BONUS
    score += max(0, PROXIMITY_BASE - int(provider["distance_miles_from_hospital"]))
    score -= int(Decimal(offer_daily_rate_cents) // COST_PENALTY_DIVISOR)
    return score


# --------------------------------------------------------------------------
# logistics cost (PRD 3.7)
# --------------------------------------------------------------------------
def logistics_cost(order_type, vehicle, mileage_miles, item_code):
    if order_type == "PATIENT_TRANSPORT":
        return int(vehicle["base_rate_cents"]) + int(vehicle["per_mile_cents"]) * int(mileage_miles)
    return DME_ITEM_RATE_CENTS[item_code]


# --------------------------------------------------------------------------
# throughput (PRD 3.9)
# --------------------------------------------------------------------------
def throughput_grade(ratio):
    ratio = Decimal(str(ratio))
    if ratio <= Decimal("0.900"):
        return "EXEMPLARY"
    if ratio <= Decimal("1.050"):
        return "ON_TARGET"
    if ratio <= Decimal("1.250"):
        return "ABOVE_TARGET"
    return "OUTLIER"

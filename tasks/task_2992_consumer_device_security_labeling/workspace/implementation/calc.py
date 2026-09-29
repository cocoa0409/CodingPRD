"""Derived quantities: conformance scores, issuance fees, penalties, ledgers,
participation tiers and the program evaluation.  All rounding is half up and
the *order* of rounding is contractual (PRD 2.9)."""

from decimal import Decimal, ROUND_HALF_UP

import store

# ---- practice areas and their program weights (PRD 3.4 step three) --------
AUTHENTICATION = "AUTHENTICATION"
SOFTWARE_UPDATE = "SOFTWARE_UPDATE"
DATA_PROTECTION = "DATA_PROTECTION"
VULN_DISCLOSURE = "VULN_DISCLOSURE"

PRACTICE_AREAS = (AUTHENTICATION, SOFTWARE_UPDATE, DATA_PROTECTION, VULN_DISCLOSURE)

AREA_WEIGHT = {
    AUTHENTICATION: Decimal("0.30"),
    SOFTWARE_UPDATE: Decimal("0.30"),
    DATA_PROTECTION: Decimal("0.25"),
    VULN_DISCLOSURE: Decimal("0.15"),
}

AREA_FLOOR_SCORE = Decimal("60.00")
GATE_CAP_SCORE = Decimal("65.00")
GRADE_A_SCORE = Decimal("90.00")
GRADE_B_SCORE = Decimal("80.00")

PROVISIONAL = "PROVISIONAL"
VERIFIED = "VERIFIED"

# ---- fee schedule (PRD 3.6) ----------------------------------------------
RENEWAL_SUPPLEMENT_CENTS = 12000
FEE_BAND_LOW_CENTS = 50000
FEE_BAND_HIGH_CENTS = 150000
FEE_RATE_LOW = Decimal("0")
FEE_RATE_MID = Decimal("0.10")
FEE_RATE_HIGH = Decimal("0.18")

# ---- penalty schedule (PRD 3.9) ------------------------------------------
STATUTORY_SCHEDULE = "STATUTORY_SCHEDULE"
REVENUE_LINKED = "REVENUE_LINKED"

STATUTORY_PER_UNIT_CENTS = {
    "UNAUTHORIZED_DISPLAY": Decimal("4200"),
    "EXPIRED_LABEL_DISPLAY": Decimal("2750"),
    "FALSE_CLAIM": Decimal("6100"),
}
CHANNEL_FACTOR = {
    "IN_STORE": Decimal("1.15"),
    "ONLINE": Decimal("1.35"),
}
AGGRAVATION_STEP = Decimal("0.25")
AGGRAVATION_CAP = Decimal("2.00")
STATUTORY_CAP_CENTS = 5000000
REVENUE_RATE = Decimal("0.0004")
REVENUE_CAP_CENTS = 25000000

# ---- standing thresholds (PRD 3.9) ---------------------------------------
BARRED_UPHELD_COUNT = 3
DELINQUENT_OUTSTANDING_CENTS = 25000

# ---- retailer participation (PRD 3.8) ------------------------------------
PLATINUM_DISPLAY_COUNT = 5
GOLD_DISPLAY_COUNT = 2

# ---- program evaluation targets (PRD 3.10) -------------------------------
PARTICIPATION_TARGET = Decimal("40.00")
RECOGNITION_TARGET = Decimal("35.00")


def q2(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def cents(value):
    """Round a fractional cent amount half up to a whole number of cents."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# Conformance scoring (PRD 3.4)
# --------------------------------------------------------------------------
def _credit(criterion, response, tier, variant):
    weight = Decimal(criterion["weight"])
    if variant == PROVISIONAL:
        if not response["self_declared_conformant"]:
            return Decimal("0")
        if criterion["requires_lab_verification"]:
            return weight * Decimal(tier["unverified_weight_factor"])
        return weight
    # VERIFIED
    if criterion["requires_lab_verification"]:
        return weight if response["lab_result"] == "PASS" else Decimal("0")
    return weight if response["self_declared_conformant"] else Decimal("0")


def conformance_score(assessment, tier, variant):
    """Return (area_scores, overall_score, min_area_score, gate_applied, grade)."""
    earned = {area: Decimal("0") for area in PRACTICE_AREAS}
    possible = {area: Decimal("0") for area in PRACTICE_AREAS}

    for response in store.responses_of(assessment["id"]):
        criterion = store.security_criteria.get(response["criterion_id"])
        if criterion is None:
            continue
        area = criterion["practice_area"]
        if area not in earned:
            continue
        possible[area] += Decimal(criterion["weight"])
        earned[area] += _credit(criterion, response, tier, variant)

    # Step one -- per-area scores, each rounded to 2dp before it is weighted.
    area_scores = {}
    for area in PRACTICE_AREAS:
        if possible[area] == 0:
            area_scores[area] = Decimal("0.00")
        else:
            area_scores[area] = q2(earned[area] / possible[area] * Decimal("100"))

    # Step two -- the floor reads the already-rounded area scores.
    min_area = min(area_scores[area] for area in PRACTICE_AREAS)

    # Step three -- weight the rounded scores, sum, then round once more.
    weighted = Decimal("0")
    for area in PRACTICE_AREAS:
        weighted += area_scores[area] * AREA_WEIGHT[area]
    weighted = q2(weighted)

    # Step four -- the floor gate.  Strict comparison; the cap only pulls down.
    if min_area < AREA_FLOOR_SCORE:
        gate_applied = True
        overall = weighted if weighted < GATE_CAP_SCORE else GATE_CAP_SCORE
    else:
        gate_applied = False
        overall = weighted

    return area_scores, overall, min_area, gate_applied, grade_for(overall, tier)


def grade_for(overall, tier):
    """Step five -- the letter (PRD 3.4)."""
    if overall is None:
        return None
    if overall >= GRADE_A_SCORE:
        return "A"
    if overall >= GRADE_B_SCORE:
        return "B"
    if overall >= Decimal(tier["min_overall_score"]):
        return "C"
    return "FAIL"


# --------------------------------------------------------------------------
# Label issuance fee (PRD 3.6)
# --------------------------------------------------------------------------
def label_issuance_fee(tier, renewal_generation):
    subtotal = Decimal(tier["issuance_base_fee_cents"]) + (
        Decimal(RENEWAL_SUPPLEMENT_CENTS) * Decimal(renewal_generation)
    )
    # The band is pinned to the subtotal, selected exactly once.
    if subtotal < FEE_BAND_LOW_CENTS:
        rate = FEE_RATE_LOW
    elif subtotal < FEE_BAND_HIGH_CENTS:
        rate = FEE_RATE_MID
    else:
        rate = FEE_RATE_HIGH
    surcharge = cents(subtotal * rate)
    return int(subtotal) + surcharge


# --------------------------------------------------------------------------
# Enforcement penalty (PRD 3.9)
# --------------------------------------------------------------------------
def aggravation_multiplier(prior_upheld_count):
    """Read from the count as it stands immediately BEFORE this adjudication."""
    value = Decimal("1.00") + AGGRAVATION_STEP * Decimal(prior_upheld_count)
    if value > AGGRAVATION_CAP:
        value = AGGRAVATION_CAP
    return q2(value)


def enforcement_penalty(case, manufacturer, multiplier):
    """Return (penalty_variant, penalty_cents)."""
    if manufacturer["enterprise_class"] == "SMALL":
        per_unit = STATUTORY_PER_UNIT_CENTS[case["violation_type"]]
        subtotal = 0
        # Declared array order is load-bearing; each line rounds before summing.
        for line in case["violation_line_items"]:
            line_amount = (
                per_unit
                * Decimal(line["unit_count"])
                * multiplier
                * CHANNEL_FACTOR[line["channel"]]
            )
            subtotal += cents(line_amount)
        return STATUTORY_SCHEDULE, min(subtotal, STATUTORY_CAP_CENTS)
    # LARGE -- revenue linked, line items ignored entirely, one rounding only.
    amount = cents(Decimal(manufacturer["annual_us_revenue_cents"]) * REVENUE_RATE * multiplier)
    return REVENUE_LINKED, min(amount, REVENUE_CAP_CENTS)


# --------------------------------------------------------------------------
# Conserved ledgers (PRD 2.10)
# --------------------------------------------------------------------------
def manufacturer_penalty_ledger(manufacturer_id):
    """Pure re-aggregation over every case ever opened against the subject."""
    outstanding = 0
    paid = 0
    vacated = 0
    upheld = 0
    for case in store.cases_of_manufacturer(manufacturer_id):
        status = case["penalty_status"]
        if status == "ASSESSED":
            outstanding += case["penalty_cents"]
        elif status == "PAID":
            paid += case["penalty_cents"]
        elif status == "VACATED":
            vacated += case["penalty_cents"]
        if case["case_status"] == "ADJUDICATED_UPHELD":
            upheld += 1
    return {
        "outstanding_penalty_cents": outstanding,
        "paid_penalty_cents": paid,
        "vacated_penalty_cents": vacated,
        "total_assessed_penalty_cents": outstanding + paid + vacated,
        "upheld_case_count": upheld,
    }


def standing_for(upheld_case_count, outstanding_penalty_cents):
    """Fixed order: BARRED must win over DELINQUENT (PRD 3.9)."""
    if upheld_case_count >= BARRED_UPHELD_COUNT:
        return "BARRED"
    if outstanding_penalty_cents >= DELINQUENT_OUTSTANDING_CENTS:
        return "DELINQUENT"
    return "GOOD"


def lab_bench_hour_ledger(lab_id):
    """reserved is the sum over SCHEDULED / IN_PROGRESS engagements."""
    reserved = 0
    for engagement in store.engagements_of_lab(lab_id):
        if engagement["status"] in ("SCHEDULED", "IN_PROGRESS"):
            reserved += engagement["bench_hours"]
    return reserved


# --------------------------------------------------------------------------
# Retailer participation tier (PRD 3.8)
# --------------------------------------------------------------------------
def retailer_participation_tier(education_materials_ack, active_display_count):
    if education_materials_ack and active_display_count >= PLATINUM_DISPLAY_COUNT:
        return "PLATINUM"
    if education_materials_ack and active_display_count >= GOLD_DISPLAY_COUNT:
        return "GOLD"
    return "BASELINE"


def rate(numerator, denominator):
    """Percentage rounded half up to 2dp; an empty denominator yields 0.00."""
    if denominator == 0:
        return Decimal("0.00")
    return q2(Decimal(100) * Decimal(numerator) / Decimal(denominator))

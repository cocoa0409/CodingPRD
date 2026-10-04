"""Pure calculation rules (scaffold §1.3, PRD §2.7 / §3).

All money is integer cents and every rounding step uses ROUND_HALF_UP on
decimal.Decimal — never float, never Python's banker's-rounding round().
"""

from decimal import Decimal, ROUND_HALF_UP

import db

CENT = Decimal("1")


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def cents(value):
    """Round half up to the cent, returned as an int."""
    return int(dec(value).quantize(CENT, rounding=ROUND_HALF_UP))


def round4(value):
    return dec(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def round2(value):
    return dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def clamp(value, low, high):
    return max(low, min(high, value))


# --- constants (scaffold §1.3) ----------------------------------------------
GUARANTEE_RATIO = Decimal("1.50")
EXTENDED_REPLACEMENT_FACTOR = Decimal("1.5")
BASE_APPRAISAL_CURRENCY_MONTHS = 24
PROVISION_BASELINE_MULTIPLE = Decimal("1.25")

BASE_SCORE = 300
MAX_SCORE = 999
BAND_POINTS = {"STANDARD": 0, "ELEVATED": 240, "EXTREME": 420}
MITIGATION_CREDIT = {"CLEARED": 420, "PARTIAL": 250, "FAILED": 60, "UNVERIFIED": 0}
AGENCY_POINTS = {"NORMAL": 0, "ELEVATED": 70, "CRITICAL": 150}

DEDUCTIBLE_PCT = {
    "WILDFIRE": Decimal("0.02"),
    "WIND": Decimal("0.01"),
    "HALL": Decimal("0.01"),
    "WATER": Decimal("0.005"),
    "THEFT": Decimal("0.005"),
    "OTHER": Decimal("0.005"),
}
SCARCITY_FACTOR = Decimal("1.20")

ZONE_BAND_ELEVATED_PCT = Decimal("18.0")
ZONE_BAND_CRITICAL_PCT = Decimal("30.0")
AGENCY_BAND_ELEVATED_PCT = Decimal("15.0")
AGENCY_BAND_CRITICAL_PCT = Decimal("25.0")
MIN_PORTFOLIO_ACTIVE_COUNT = 2

NOTICE_DAYS_NORMAL = 45
NOTICE_DAYS_ELEVATED = 60
NOTICE_DAYS_CRITICAL = 90
MIN_POLICY_AGE_DAYS = 60

DWELLING_CURRENCY_MONTHS = 24

# Enrollment states that make up the ACTIVE population.
ACTIVE_ENROLLMENT_STATUSES = ("SUBMITTED", "REFERRED", "APPROVED", "ATTACHED")


def is_common(record):
    return record is not None and "version" in record


# --- §3.1 replacement-cost valuation ----------------------------------------
def valuation_contributions(property_id):
    """Every Appraisal of the property with status APPROVED or SUPERSEDED."""
    rows = [a for a in db.APPRAISALS.values() if a["property_id"] == property_id]
    return [a for a in rows if a["status"] in ("APPROVED", "SUPERSEDED")]


def scheduled_valuation(property_id):
    """Sum of attached_value_cents over APPROVED/ATTACHED scheduled items."""
    return sum(
        s["attached_value_cents"]
        for s in db.SCHEDULED_ITEMS.values()
        if s["property_id"] == property_id and s["status"] in ("APPROVED", "ATTACHED")
    )


def replacement_cost(property_id):
    """Pinned order: weight each row, round each product, then sum (PRD §2.7)."""
    dwelling = 0
    contents = 0
    for appraisal in valuation_contributions(property_id):
        weight = dec(appraisal["percent_complete"])
        dwelling += int((dec(appraisal["dwelling_cost_cents"]) * weight)
                        .quantize(CENT, rounding=ROUND_HALF_UP))
        contents += int((dec(appraisal["contents_cost_cents"]) * weight)
                        .quantize(CENT, rounding=ROUND_HALF_UP))
    return dwelling, contents


def total_insured_value(property_id):
    dwelling, contents = replacement_cost(property_id)
    return dwelling + contents + scheduled_valuation(property_id)


def valuation_fingerprint(property_id):
    dwelling, contents = replacement_cost(property_id)
    return "%d:%d:%d" % (dwelling, contents, scheduled_valuation(property_id))


# --- §3.3 mitigation band ----------------------------------------------------
def mitigation_band(property_id):
    """Ordered cascade: CLEARED, else PARTIAL, else FAILED, else UNVERIFIED."""
    rows = [r for r in db.MITIGATION_REQUIREMENTS.values()
            if r["property_id"] == property_id]
    verified = [r for r in rows if r["status"] == "VERIFIED"]
    if any(r["band_awarded"] == "CLEARED" for r in verified):
        return "CLEARED"
    if any(r["band_awarded"] == "PARTIAL" for r in verified):
        return "PARTIAL"
    if any(r["status"] in ("LAPSED", "WAIVED") for r in rows):
        return "FAILED"
    return "UNVERIFIED"


# --- §3.7 wildfire risk score -----------------------------------------------
def risk_score_parts(property_id, gross=False):
    """Weighted integer score; rounded once, at the end.  PRD §3.7."""
    prop = db.PROPERTIES[property_id]
    zone = db.ZONES.get(prop["risk_zone_id"])
    agency = db.AGENCIES.get(prop["agency_id"])
    band_points = BAND_POINTS.get(zone["exposure_band"] if zone else "STANDARD", 0)
    credit = MITIGATION_CREDIT[mitigation_band(property_id)]
    applied_credit = 0 if gross else credit
    agency_points = AGENCY_POINTS.get(agency["concentration_band"] if agency else "NORMAL", 0)
    base = BASE_SCORE + band_points + agency_points - applied_credit
    score = clamp(base, 0, MAX_SCORE)
    return {
        "band_points": band_points,
        "mitigation_credit": applied_credit,
        "agency_points": agency_points,
        "base_score": base,
        "risk_score": score,
        "risk_tier": risk_tier(score),
    }


def risk_tier(score):
    if score >= 700:
        return "REFER"
    if score >= 450:
        return "SURCHARGE"
    if score >= 200:
        return "REVIEW"
    return "MANAGED"


# --- §3.7 premiums -----------------------------------------------------------
def premium_block(dwelling_replacement_cost_cents, dwelling_coverage_cents,
                  contents_coverage_cents):
    ratio = (round4(dec(dwelling_coverage_cents) / dec(dwelling_replacement_cost_cents))
             if dwelling_replacement_cost_cents else Decimal("0.0000"))
    base_rate = cents(Decimal("0.0021") * dec(dwelling_coverage_cents))
    premium = cents(dec(base_rate) * ratio)
    extended_premium = max(premium, 12500)
    contents_premium = cents(Decimal("0.0009") * dec(contents_coverage_cents))
    return ratio, extended_premium, contents_premium, extended_premium + contents_premium


# --- §3.7 replacement provision ---------------------------------------------
def dispatch_in_progress(property_id):
    return any(
        d["property_id"] == property_id and d["status"] in ("VENDOR_ASSIGNED", "ON_SITE")
        for d in db.DISPATCHES.values()
    )


def provision_block(dwelling_replacement_cost_cents, band, defense_active):
    """PRD §3.7: "When the property's `mitigation_band` is `CLEARED` and no defense
    dispatch is in progress, the provision is `EXTENDED` ... When a defense
    dispatch is in progress ... the provision is `GUARANTEED` ... A property that
    is both design-cleared and under active defense therefore takes `EXTENDED`,
    never the larger guarantee.\""""
    extended_limit = cents(EXTENDED_REPLACEMENT_FACTOR * dec(dwelling_replacement_cost_cents))
    if band == "CLEARED":
        guaranteed = cents(dec(dwelling_replacement_cost_cents) / EXTENDED_REPLACEMENT_FACTOR)
        return "EXTENDED", guaranteed, extended_limit
    if defense_active:
        return "GUARANTEED", None, extended_limit
    return "NONE", dwelling_replacement_cost_cents, extended_limit


def required_dwelling_coverage(dwelling_replacement_cost_cents):
    return cents(GUARANTEE_RATIO * dec(dwelling_replacement_cost_cents))


# --- §3.8 cash settlement ----------------------------------------------------
def raw_deductible(cause_of_loss, dwelling_coverage_cents):
    return cents(DEDUCTIBLE_PCT[cause_of_loss] * dec(dwelling_coverage_cents))


def applicable_limit(enrollment):
    provision = enrollment["replacement_provision"]
    if provision == "GUARANTEED":
        return None
    if provision == "EXTENDED":
        return enrollment["extended_replacement_limit_cents"]
    return enrollment["dwelling_coverage_cents"]


def settlement_block(enrollment, claim):
    """Deductible first, ceiling second, settlement last (PRD §3.8)."""
    deductible = raw_deductible(claim["cause_of_loss"], enrollment["dwelling_coverage_cents"])
    limit = applicable_limit(enrollment)
    scarcity = SCARCITY_FACTOR if claim["adjuster_override"] else Decimal("1.0")
    reported = claim["reported_indemnity_cents"]
    # Cap BEFORE the scarcity factor — the factor is not a limit extension.
    capped = reported if limit is None else min(reported, limit)
    settlement = cents(dec(capped) * scarcity)
    applied = min(deductible, settlement)
    return {
        "settlement_amount_cents": settlement,
        "deductible_applied_cents": applied,
        "limit_applied_cents": 0 if limit is None else limit,
        "cash_settlement_eligible": enrollment["replacement_provision"] == "GUARANTEED",
        "raw_deductible_cents": deductible,
    }


# --- §3.9 notice period ------------------------------------------------------
def required_notice_days(zone_band):
    if zone_band == "CRITICAL":
        return NOTICE_DAYS_CRITICAL
    if zone_band == "ELEVATED":
        return NOTICE_DAYS_ELEVATED
    return NOTICE_DAYS_NORMAL


# --- §3.6 defense dispatch priority -----------------------------------------
def priority_rank(prop, logical_now):
    band = mitigation_band(prop["id"])
    zone_rank = 1 if band in ("PARTIAL", "UNVERIFIED") else 2
    horizon = logical_now.timestamp() + 14 * 86400
    expiring = 1
    for req in db.MITIGATION_REQUIREMENTS.values():
        if req["property_id"] != prop["id"] or req["status"] != "IMPOSED":
            continue
        due = req["due_on"]
        if due is None:
            continue
        if due.timestamp() <= horizon:
            expiring = 0
            break
    from clock import whole_days_ago
    age_days = whole_days_ago(prop["created_at"], logical_now)
    return zone_rank * 1000000 + expiring * 1000 + age_days


# --- §3.2 appraisal-document currency ---------------------------------------
AGING_AT_MONTHS = 12


def currency_status(currency_months):
    """Derived band.  A document is consumed at the 24-month expiry."""
    if currency_months < AGING_AT_MONTHS:
        return "CURRENT"
    if currency_months < DWELLING_CURRENCY_MONTHS:
        return "AGING"
    return "EXPIRED"
"""The scoring, fee-pooling and window calculations of scaffold §1.3."""

from decimal import Decimal

from core import constants as C
from core.utils import (
    add_days,
    add_months,
    days_between,
    money_score,
    months_between,
    round_half_up,
    round_half_up_int,
    whole_dollar_cents,
)


# ---------------------------------------------------------------------------
# Decay
# ---------------------------------------------------------------------------
def decay_factor(age_months):
    if age_months <= C.DECAY_TIER_1_MONTHS:
        return Decimal(str(C.DECAY_TIER_1_FACTOR))
    if age_months <= C.DECAY_TIER_2_MONTHS:
        return Decimal(str(C.DECAY_TIER_2_FACTOR))
    return Decimal(str(C.DECAY_TIER_3_FACTOR))


def assessment_age_months(assessment, now):
    return months_between(assessment.get("assessed_on"), now)


def decayed_penalty(assessments, now):
    total = Decimal("0")
    for row in assessments:
        impact = Decimal(str(row.get("score_impact") or 0))
        total += impact * decay_factor(assessment_age_months(row, now))
    return total


# ---------------------------------------------------------------------------
# integrity_score — every assessment contributes, resolved or not
# ---------------------------------------------------------------------------
def integrity_score(assessments, now):
    penalty = decayed_penalty(assessments, now)
    score = Decimal(str(C.MAX_INTEGRITY_SCORE)) - penalty
    if score < 0:
        score = Decimal("0")
    return money_score(score)


# ---------------------------------------------------------------------------
# client_risk_score — PROVISIONAL keeps resolved rows only, FINAL keeps all
# ---------------------------------------------------------------------------
def client_risk_score(client, assessments, variant, now):
    base = Decimal(str(C.INDUSTRY_RISK_INDEX.get(client.get("industry_code"), 0)))
    base += Decimal(str(C.JURISDICTION_RISK_INDEX.get(
        client.get("jurisdiction_country"), C.DEFAULT_JURISDICTION_RISK)))
    if client.get("is_public_interest_entity"):
        base += Decimal(str(C.PIE_SURCHARGE))
    if variant == "PROVISIONAL":
        contributing = [row for row in assessments if row.get("resolved") is True]
    else:
        contributing = list(assessments)
    return money_score(base + decayed_penalty(contributing, now))


def clamp_score(value):
    score = Decimal(str(value))
    if score < C.SCORE_FLOOR:
        score = Decimal(str(C.SCORE_FLOOR))
    if score > C.SCORE_CEILING:
        score = Decimal(str(C.SCORE_CEILING))
    return money_score(score)


def risk_tier_for(combined_score):
    score = Decimal(str(combined_score))
    if score < Decimal(str(C.RISK_TIER_LOW_MAX)):
        return "LOW"
    if score < Decimal(str(C.RISK_TIER_MODERATE_MAX)):
        return "MODERATE"
    if score < Decimal(str(C.RISK_TIER_HIGH_MAX)):
        return "HIGH"
    return "SIGNIFICANT"


# ---------------------------------------------------------------------------
# naf_fee_pool — round each service to whole dollars first, then sum
# ---------------------------------------------------------------------------
def naf_fee_pool(client_id, services):
    total = 0
    for row in services:
        if row.get("client_id") != client_id:
            continue
        if row.get("status") != "APPROVED":
            continue
        total += whole_dollar_cents(row.get("fee_cents") or 0)
    return total


def rounded_candidate_fee(fee_cents):
    return whole_dollar_cents(fee_cents or 0)


# ---------------------------------------------------------------------------
# financial_interest_materiality
# ---------------------------------------------------------------------------
def financial_interest_materiality(threat_type, instrument_type, value_cents, grade, is_pie):
    if threat_type != "FINANCIAL_INTEREST":
        return False
    if instrument_type in C.DIRECT_INSTRUMENTS:
        if is_pie:
            return True
        multiplier = 1
    elif instrument_type in C.INDIRECT_INSTRUMENTS:
        multiplier = C.INDIRECT_MULTIPLIER
    else:
        multiplier = 1
    threshold = C.MATERIALITY_CENTS.get(grade, 0) * multiplier
    return int(value_cents or 0) >= threshold


# ---------------------------------------------------------------------------
# cooling_off_window
# ---------------------------------------------------------------------------
def cooling_off_end(effective_on, relationship_type):
    months = C.COOLING_OFF_MONTHS.get(relationship_type, 0)
    if months <= 0:
        return effective_on
    return add_months(effective_on, months)


def cooling_off_months(relationship_type):
    return C.COOLING_OFF_MONTHS.get(relationship_type, 0)


# ---------------------------------------------------------------------------
# affiliate_network_risk
# ---------------------------------------------------------------------------
def affiliate_network_risk(engagement, attestations, affiliates):
    if not engagement.get("is_multinational"):
        return 0
    raw = 0
    for row in attestations:
        if row.get("engagement_id") != engagement.get("id"):
            continue
        affiliate = affiliates.get(row.get("affiliate_id"))
        tier = affiliate.get("network_tier") if affiliate else None
        weight = C.TIER_WEIGHT.get(tier, 0)
        raw += int(row.get("breach_count") or 0) * weight
    if raw < 0:
        raw = 0
    if raw > C.NETWORK_RISK_CEILING:
        raw = C.NETWORK_RISK_CEILING
    return raw


# ---------------------------------------------------------------------------
# inspection_response_due
# ---------------------------------------------------------------------------
def inspection_response_due(review_type, inspection_body, deficiency_count, received_on):
    if review_type != "REGULATORY_INSPECTION":
        return None
    base_days = C.RESPONSE_WINDOW_DAYS.get(inspection_body)
    if base_days is None:
        return None
    if int(deficiency_count or 0) >= C.DEFICIENCY_HALVING_THRESHOLD:
        effective_days = round_half_up_int(Decimal(str(base_days)) / Decimal("2"))
    else:
        effective_days = base_days
    return add_days(received_on, effective_days)


# ---------------------------------------------------------------------------
# remediation window
# ---------------------------------------------------------------------------
def remediation_due(discovered_on, severity):
    return add_days(discovered_on, C.REMEDIATION_WINDOW_DAYS.get(severity, 0))


# ---------------------------------------------------------------------------
# review buffering
# ---------------------------------------------------------------------------
def review_buffer_conflict(candidate_received_on, candidate_due_on, existing_reviews):
    """True when the candidate lands inside another review's buffer window.

    A review is overlapping or adjacent when the candidate starts less than
    REVIEW_BUFFER_DAYS after its due_on and the review itself does not begin
    well beyond the candidate's own window.
    """
    for row in existing_reviews:
        existing_due = row.get("due_on")
        existing_received = row.get("received_on")
        if existing_due is None or existing_received is None:
            continue
        starts_inside_buffer = days_between(existing_due, candidate_received_on) < C.REVIEW_BUFFER_DAYS
        adjacent = days_between(candidate_due_on, existing_received) < C.REVIEW_BUFFER_DAYS
        if starts_inside_buffer and adjacent:
            return True
    return False

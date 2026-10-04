"""Calculation rules (SCAFFOLD Table 3 / PRD 2.10, 3.3, 3.4, 3.9).

All scored arithmetic uses Decimal with ROUND_HALF_UP; money is integer cents.
"""
from decimal import Decimal, ROUND_HALF_UP

from db import (
    DAYS_PER_MONTH, HALF_MONTH_DAYS, MIN_DIMENSION_FLOOR, NEUTRAL_MIN,
    READJUSTMENT_MONTHLY_RATE_CENTS, RECOMMEND_MIN, STRONGLY_RECOMMEND_MIN,
)

TWO_PLACES = Decimal("0.01")


def D(x):
    return x if isinstance(x, Decimal) else Decimal(str(x))


def round2(value):
    return D(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


# --- interview_overall_score -------------------------------------------------
def interview_result(motivation, adaptability, skill_competency, cross_cultural):
    """Round the weighted sum FIRST, then apply the minimum-dimension cap,
    then tier on the rounded value (fixed evaluation order)."""
    raw = (D("0.30") * D(motivation) + D("0.25") * D(adaptability)
           + D("0.25") * D(skill_competency) + D("0.20") * D(cross_cultural))
    overall = round2(raw)
    minimum = min(D(motivation), D(adaptability), D(skill_competency),
                  D(cross_cultural))
    if minimum < D(MIN_DIMENSION_FLOOR):
        recommendation = "NOT_RECOMMENDED"
    elif overall >= D(STRONGLY_RECOMMEND_MIN):
        recommendation = "STRONGLY_RECOMMEND"
    elif overall >= D(RECOMMEND_MIN):
        recommendation = "RECOMMEND"
    elif overall >= D(NEUTRAL_MIN):
        recommendation = "NEUTRAL"
    else:
        recommendation = "NOT_RECOMMENDED"
    return float(overall), recommendation


# --- skill_match_score -------------------------------------------------------
def strict_met(required_skills, applicant_skills):
    """Eligibility gate: strict coverage exactly 1.0 (empty R defined as 1.0)."""
    return set(required_skills) <= set(applicant_skills)


def strict_score(required_skills, applicant_skills):
    if len(required_skills) == 0:
        return Decimal("1.0")
    met = len(set(required_skills) & set(applicant_skills))
    return Decimal(met) / Decimal(len(set(required_skills)))


def country_bonus(country_preference_ids, country_program_id):
    """Empty preference list -> 0.5; ranked 0-based index i -> 1.0 - 0.25*i;
    absent from a non-empty list -> 0.0."""
    if not country_preference_ids:
        return Decimal("0.5")
    if country_program_id in country_preference_ids:
        rank = country_preference_ids.index(country_program_id)
        return Decimal("1.0") - Decimal("0.25") * rank
    return Decimal("0.0")


def weighted_score(strict, sector_bonus, c_bonus):
    total = D("0.7") * D(strict) + D("0.2") * D(sector_bonus) + D("0.1") * D(c_bonus)
    return float(round2(total))


# --- service_duration / readjustment_allowance -------------------------------
def whole_days(end_dt, start_dt):
    return (end_dt - start_dt).days


def months_served(days):
    """Half-month round-up: floor((days + 15) / 30)."""
    return (days + HALF_MONTH_DAYS) // DAYS_PER_MONTH


def penalized_month_cents():
    """round_half_up(47500 * 2 / 3) = 31667, rounded BEFORE multiplying."""
    return int((D(READJUSTMENT_MONTHLY_RATE_CENTS) * 2 / 3).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))

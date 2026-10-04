"""Calculation rules (scaffold §1.3, PRD §2.8/§2.9/§2.10, §3.8).

Pure functions; the logical clock and entity dicts are passed in explicitly.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import constants as C
from store import parse_dt


# --- §2.9 anniversary arithmetic ---------------------------------------------
def _is_leap(year):
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def anniversary_add(dt, years):
    """Shift a datetime forward N years; Feb 29 lands on Feb 28 in non-leap
    target years. Time-of-day is preserved."""
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:  # Feb 29 into a non-leap year
        return dt.replace(year=dt.year + years, day=28)


def records_age_years(clock, cutoff):
    """Whole-year age: clock.year - cutoff.year, minus one when the cutoff's
    anniversary has not yet occurred in the clock's year. A Feb 29 cutoff has
    its anniversary on Feb 28 in non-leap clock years."""
    md = (cutoff.month, cutoff.day)
    if md == (2, 29) and not _is_leap(clock.year):
        md = (2, 28)
    age = clock.year - cutoff.year
    if (clock.month, clock.day) < md:
        age -= 1
    return age


def add_days(dt, days):
    return dt + timedelta(days=days)


# --- §3.8 reproduction fee (canonical order pinned by the scaffold) ----------
def reproduction_fee_cents(page_count, affiliation, rush):
    """Tiered pricing; ACADEMIC discount applied PER TIER with round-half-up,
    discounted tiers summed, then the rush multiplier applied to the sum with
    round-half-up. Exactly two rounding points, integer cents out."""
    t1 = min(page_count, C.TIER1_PAGES)
    t2 = min(max(page_count - C.TIER1_PAGES, 0), C.TIER2_PAGES)
    t3 = max(page_count - C.TIER1_PAGES - C.TIER2_PAGES, 0)
    tiers = [
        t1 * C.TIER1_RATE_CENTS,
        t2 * C.TIER2_RATE_CENTS,
        t3 * C.TIER3_RATE_CENTS,
    ]
    if affiliation == "ACADEMIC":
        rate = Decimal(C.ACADEMIC_DISCOUNT_RATE)
        discounted_total = sum(
            int((Decimal(t) * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            for t in tiers
        )
    else:
        discounted_total = sum(tiers)
    if rush:
        return int(
            (Decimal(discounted_total) * Decimal(C.RUSH_MULTIPLIER)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
    return discounted_total


# --- digitization priority (demand_weighted variant, canonical) --------------
def digitization_priority(collection, clock):
    age_years = records_age_years(clock, parse_dt(collection["records_cutoff_date"]))
    return (
        C.AGE_POINTS_PER_YEAR * min(age_years, C.AGE_CAP_YEARS)
        + C.PULL_POINTS * min(collection["pull_count_total"], C.PULL_CAP)
        + C.FOIA_POINTS * min(collection["foia_release_count"], C.FOIA_CAP)
        + min(collection["repro_pages_fulfilled"], C.REPRO_PAGES_CAP)
        // C.REPRO_PAGES_DIVISOR
        + (C.DECLASSIFIED_BONUS if collection["declass_outcome"] == "DECLASSIFIED" else 0)
    )


# --- processing backlog score (snapshot at accession) ------------------------
def backlog_score(classification_level, records_domain, cutoff_dt, clock):
    age_years = records_age_years(clock, cutoff_dt)
    return (
        C.BACKLOG_AGE_POINTS_PER_YEAR * min(age_years, C.BACKLOG_AGE_CAP)
        + C.CLASSIFICATION_WEIGHT[classification_level]
        + (C.PRESIDENTIAL_BONUS if records_domain == "PRESIDENTIAL" else 0)
    )


# --- §2.8 restriction posture -------------------------------------------------
def restriction_posture(collection, live_restrictions):
    """live_restrictions = the collection's restrictions in any status; the
    RELEASED filter is applied here."""
    if any(r["status"] in ("IMPOSED", "NOTIFIED") for r in live_restrictions):
        return "PRESIDENTIAL_HOLD"
    if collection["classification_level"] != "NONE":
        return "CLASSIFIED_REVIEW_REQUIRED"
    return "PUBLIC"


# --- declassification review outcome (calculations.declass_review_outcome) ----
def declass_review_outcome(reviewer_assessment, referrals):
    """referrals = all referrals of the review. Only RESPONDED+EXEMPT referrals
    count; overdue SENT referrals are concurrence and are ignored."""
    if reviewer_assessment == "EXEMPT":
        return "EXEMPT_RETAINED"
    if any(r["status"] == "RESPONDED" and r["decision"] == "EXEMPT" for r in referrals):
        return "PARTIAL"
    return "DECLASSIFIED"

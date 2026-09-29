"""Denial-risk scoring (PRD 3.8)."""

from decimal import Decimal

import calc
import lookup
from clock import now
from store import db, new_row, touch


def _raw_total(stay, review):
    notes = lookup.stay_notes(stay["id"])
    documented = set(note["discipline"] for note in notes)
    missing = 0
    for discipline in calc.REQUIRED_DISCIPLINES:
        if discipline not in documented:
            missing += 1

    plan = lookup.stay_weaning_plan(stay["id"])
    weaning_gap = 0
    if plan is None:
        weaning_gap = 1
    elif plan["status"] == "VENT_DEPENDENT" and Decimal(plan["max_tolerated_sbt_hours"]) == 0:
        weaning_gap = 1

    determination = lookup.stay_live_determination(stay["id"])
    sso_flag = 0
    site_neutral_flag = 0
    los_excess = 0
    if determination is not None:
        if determination["short_stay_outlier_applied"]:
            sso_flag = 1
        if determination["payment_variant"] == "SITE_NEUTRAL":
            site_neutral_flag = 1
        used = determination["covered_los_days_used"]
        alos = determination["alos_days_used"]
        if used is not None and alos is not None:
            los_excess = used - alos
            if los_excess < 0:
                los_excess = 0

    raw = (calc.MISSING_DISCIPLINE_WEIGHT * Decimal(missing)
           + calc.WEANING_GAP_WEIGHT * Decimal(weaning_gap)
           + calc.SSO_WEIGHT * Decimal(sso_flag)
           + calc.SITE_NEUTRAL_WEIGHT * Decimal(site_neutral_flag)
           + calc.LOS_EXCESS_WEIGHT * Decimal(los_excess))
    return raw, missing


def _answered_count(review):
    total = 0
    for row in lookup.review_queries(review["id"]):
        if row["status"] in ("ANSWERED", "CLOSED"):
            total += 1
    return total


def compute(review):
    """Both score variants, the effective score and the band, from live chart data."""
    stay = db.stays[review["stay_id"]]
    raw, missing = _raw_total(stay, review)
    answered = _answered_count(review)
    as_documented = calc.clamp_score(raw)
    if answered > 0:
        query_adjusted = calc.clamp_score(raw - calc.ANSWERED_QUERY_CREDIT * Decimal(answered))
        effective = query_adjusted
    else:
        query_adjusted = None
        effective = as_documented
    return {
        "missing_discipline_count": missing,
        "answered_query_count": answered,
        "as_documented_score": as_documented,
        "query_adjusted_score": query_adjusted,
        "effective_score": effective,
        "risk_band": calc.risk_band(effective),
    }


def apply_scores(review, bump=True):
    review.update(compute(review))
    if bump:
        touch(review)
    return review


def open_review(stay, opened_by_user_id):
    """Cascade level three: open and score the stay's denial-risk review."""
    review = new_row("reviews")
    review.update({
        "stay_id": stay["id"],
        "as_documented_score": None,
        "query_adjusted_score": None,
        "effective_score": None,
        "risk_band": None,
        "missing_discipline_count": 0,
        "answered_query_count": 0,
        "status": "OPEN",
        "opened_by_user_id": opened_by_user_id,
        "resolved_by_user_id": None,
        "resolution_note": None,
    })
    db.reviews[review["id"]] = review
    apply_scores(review, bump=False)
    return review


def expire_overdue_queries(review):
    """Lazy expiry sweep performed by a rescore (PRD 3.8)."""
    instant = now()
    for row in lookup.review_queries(review["id"]):
        if row["status"] == "ISSUED" and row["due_at"] is not None and instant > row["due_at"]:
            row["status"] = "EXPIRED"
            touch(row)


def has_issued_query(review):
    for row in lookup.review_queries(review["id"]):
        if row["status"] == "ISSUED":
            return True
    return False

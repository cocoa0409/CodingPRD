"""Audit weighting (PRD 3.1.1) — the system's single decimal regime."""

from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

import clock
import store

AUDIT_PASS_THRESHOLD = 85

WEIGHTS = {
    "STORAGE": (60, 20, 20),
    "DISTRIBUTION": (20, 60, 20),
    "REPORTING": (20, 20, 60),
    "COMPREHENSIVE": (40, 30, 30),
}
STRICT_STORAGE_WEIGHTS = (70, 15, 15)

LOOKBACK_DAYS = 365


def has_recent_failed_storage(member_id):
    """Any FAILED STORAGE audit within the preceding 12 months."""
    cutoff = clock.now() - timedelta(days=LOOKBACK_DAYS)
    for row in store.audits.values():
        if (row["member_id"] == member_id
                and row["audit_type"] == "STORAGE"
                and row["audit_status"] == "FAILED"
                and row["created_at"] >= cutoff):
            return True
    return False


def weights_for(member, audit_type):
    if audit_type == "STORAGE" and has_recent_failed_storage(member["id"]):
        return STRICT_STORAGE_WEIGHTS
    return WEIGHTS[audit_type]


def weighted_score(member, audit_type, storage_score, distribution_score, reporting_score):
    """round_half_up to one decimal place."""
    w_s, w_d, w_r = weights_for(member, audit_type)
    hundred = Decimal(100)
    total = (Decimal(storage_score) * Decimal(w_s) / hundred
             + Decimal(distribution_score) * Decimal(w_d) / hundred
             + Decimal(reporting_score) * Decimal(w_r) / hundred)
    return total.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def passes(score):
    return score >= Decimal(AUDIT_PASS_THRESHOLD)


def floor_score(score):
    """audit_score is the integer floor of a weighted score, clamped at 0."""
    floored = int(score.to_integral_value(rounding=ROUND_FLOOR))
    return max(0, floored)

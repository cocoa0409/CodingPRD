"""Replacement requests: the trailing budget, the window, and the two awards."""

from db import (
    CLAIM_VALUATION_RATE,
    COMPLETION_CREDIT_PER_UNIT,
    REPLACEMENT_LIMIT_PER_90_DAYS,
    REPLACEMENT_WINDOW_LOOKBACK_DAYS,
    db,
)
from services.core import rh


def window_start():
    from db import now
    from datetime import timedelta
    return now() - timedelta(days=REPLACEMENT_WINDOW_LOOKBACK_DAYS)


def trailing_used(member_id):
    """Count of the member's filings that are not DENIED inside the trailing window."""
    start = window_start()
    count = 0
    for record in db().replacement_requests.values():
        if record["member_id"] != member_id:
            continue
        if record["stage"] == "DENIED":
            continue
        if record["created_at"] >= start.isoformat().replace("+00:00", "Z"):
            count += 1
    return count


def budget_exhausted(member_id):
    """replacement_request_budget -- at the limit is a refusal, below it is admitted."""
    return trailing_used(member_id) >= REPLACEMENT_LIMIT_PER_90_DAYS


def expiry_instant(approved_at, window_days):
    """window_expires_utc = approval instant + window_days days."""
    from datetime import timedelta
    return approved_at + timedelta(days=window_days)


def claim_points(record, element):
    """CLAIM_VALUATION variant."""
    return rh(record["quantity_missing"] * element["cost_basis_cents"]
              * CLAIM_VALUATION_RATE)


def completion_points(record):
    """COMPLETION_CREDIT variant -- a flat per-unit credit, no cost basis."""
    return COMPLETION_CREDIT_PER_UNIT * record["quantity_missing"]
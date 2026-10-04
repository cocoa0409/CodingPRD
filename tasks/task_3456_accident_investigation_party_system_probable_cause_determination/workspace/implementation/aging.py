"""Recommendation aging (PRD section 3.7; calculations.recommendation_aging).

calendar_elapsed_days: whole days from issued_at to the logical clock.
business_elapsed_days: days in (issued_at, now] at date granularity whose
weekday is Monday-Friday; no holiday calendar.
overdue: calendar_elapsed_days STRICTLY greater than 90 and not closed.
aging_bucket: GREEN < 60 business days; AMBER 60..89 inclusive; RED >= 90.
"""

from datetime import timedelta

import clock
from constants import (
    AGING_AMBER_MIN_BUSINESS_DAYS,
    AGING_RED_MIN_BUSINESS_DAYS,
    RECOMMENDATION_CLOSED_STATUSES,
    RESPONSE_WINDOW_DAYS,
    SECONDS_PER_DAY,
)


def _business_days_between(issued_date, now_date):
    count = 0
    current = issued_date + timedelta(days=1)
    while current <= now_date:
        if current.weekday() < 5:  # Monday=0 .. Friday=4
            count += 1
        current += timedelta(days=1)
    return count


def compute_aging(recommendation):
    """Return (calendar_elapsed_days, business_elapsed_days, overdue, bucket)."""
    issued = clock.parse_iso(recommendation["issued_at"])
    now = clock.clock_dt()
    if issued is None or now is None:
        return 0, 0, False, "GREEN"
    delta_seconds = (now - issued).total_seconds()
    calendar_days = int(delta_seconds // SECONDS_PER_DAY)
    business_days = _business_days_between(issued.date(), now.date())
    overdue = (
        calendar_days > RESPONSE_WINDOW_DAYS
        and recommendation["status"] not in RECOMMENDATION_CLOSED_STATUSES
    )
    if business_days < AGING_AMBER_MIN_BUSINESS_DAYS:
        bucket = "GREEN"
    elif business_days < AGING_RED_MIN_BUSINESS_DAYS:
        bucket = "AMBER"
    else:
        bucket = "RED"
    return calendar_days, business_days, overdue, bucket

"""Statutory day arithmetic (PRD section 2.6).

CALENDAR_DAYS advances a plain UTC date by n days.  BUSINESS_DAYS steps one day
at a time from the start date and counts only dates that are neither Saturday
nor Sunday nor listed in the agency's holiday_dates.  A deadline instant is the
resulting date at T23:59:59.000Z.
"""
from datetime import timedelta

import clock

CALENDAR_DAYS = "CALENDAR_DAYS"
BUSINESS_DAYS = "BUSINESS_DAYS"


def _is_countable(day, holidays):
    if day.weekday() >= 5:  # Saturday = 5, Sunday = 6
        return False
    return day.isoformat() not in holidays


def add_days(start_date, n, basis, holidays):
    """Return the resulting UTC date."""
    holiday_set = set(holidays or [])
    if basis == CALENDAR_DAYS:
        return start_date + timedelta(days=n)
    remaining = n
    cursor = start_date
    while remaining > 0:
        cursor = cursor + timedelta(days=1)
        if _is_countable(cursor, holiday_set):
            remaining -= 1
    return cursor


def deadline_instant(start_date, n, basis, holidays):
    """The day-arithmetic result rendered as that date's final second."""
    return clock.end_of_day_iso(add_days(start_date, n, basis, holidays))


def tolling_days_for_span(open_instant, close_instant, basis, holidays):
    """Days from the UTC date of open_instant inclusive to the UTC date of
    close_instant exclusive.  Under CALENDAR_DAYS every such day counts; under
    BUSINESS_DAYS only non-weekend, non-holiday days count."""
    if open_instant is None or close_instant is None:
        return 0
    holiday_set = set(holidays or [])
    start = clock.utc_date(open_instant)
    end = clock.utc_date(close_instant)
    count = 0
    cursor = start
    while cursor < end:
        if basis == CALENDAR_DAYS or _is_countable(cursor, holiday_set):
            count += 1
        cursor = cursor + timedelta(days=1)
    return count


def strict_due_at(submitted_instant, agency):
    return deadline_instant(
        clock.utc_date(submitted_instant),
        agency["initial_response_days"],
        agency["deadline_basis"],
        agency.get("holiday_dates") or [],
    )


def tolled_due_at(submitted_instant, agency, tolled_days_total):
    return deadline_instant(
        clock.utc_date(submitted_instant),
        agency["initial_response_days"] + int(tolled_days_total or 0),
        agency["deadline_basis"],
        agency.get("holiday_dates") or [],
    )


def retention_expires_at(delivery_instant, retention_policy_days):
    return clock.end_of_day_iso(
        add_days(clock.utc_date(delivery_instant), int(retention_policy_days), CALENDAR_DAYS, [])
    )


def appeal_decision_due_at(filed_instant, agency):
    return deadline_instant(
        clock.utc_date(filed_instant),
        agency["appeal_decision_days"],
        agency["deadline_basis"],
        agency.get("holiday_dates") or [],
    )

"""Temporal helpers driven by the server-side logical clock (PRD 2.6).

Advertised weeks are half-open: [week_start_date 00:00:00Z, week_end_date
00:00:00Z).  Submission deadlines are computed from the purchase DATE at
00:00:00Z plus submission_window_days days, deadline instant INCLUDED.
Certificate expiry: expires_at is issued_at advanced by whole calendar
months and snapped to 00:00:00Z; the expiry instant itself is EXPIRED.
"""

import calendar
from datetime import date, datetime, timedelta, timezone

import db


def parse_date_str(value):
    """'YYYY-MM-DD' -> date."""
    return datetime.strptime(value, "%Y-%m-%d").date()


def day_start_utc(d):
    """00:00:00Z of a date."""
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def purchase_dt(receipt):
    """Purchase instant as a datetime (prefers the second-granularity
    normalized value captured at creation)."""
    norm = receipt.get("_purchase_at_norm")
    if norm is not None:
        return parse_timestamp_iso(norm)
    return parse_timestamp_iso(receipt["purchase_at"])


def purchase_day(purchase_at_iso):
    """The UTC calendar date of a stored purchase_at timestamp."""
    return parse_timestamp_iso(purchase_at_iso).date()


def parse_timestamp_iso(text):
    """Stored ISO timestamp string -> aware datetime (UTC)."""
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def submission_deadline(receipt, store):
    """Purchase date 00:00:00Z + submission_window_days days (inclusive)."""
    day = purchase_dt(receipt).date()
    return day_start_utc(day) + timedelta(days=store["submission_window_days"])


def submission_window_open(receipt, store):
    return db.clock_now() <= submission_deadline(receipt, store)


def week_open(program_rec):
    return day_start_utc(parse_date_str(program_rec["week_start_date"]))


def week_close(program_rec):
    return day_start_utc(parse_date_str(program_rec["week_end_date"]))


def week_contains(program_rec, instant):
    return week_open(program_rec) <= instant < week_close(program_rec)


def auto_close_cutoff(program_rec, store):
    return week_close(program_rec) + timedelta(
        days=store["submission_window_days"])


def refresh_program_status(program_rec):
    """Lazy auto-close (PRD 3.2): the first read or write against an ACTIVE
    program observed at logical clock >= week_end 00:00:00Z +
    submission_window_days transitions it to CLOSED."""
    if program_rec["status"] != "ACTIVE":
        return program_rec
    store = db.stores[program_rec["store_id"]]
    if db.clock_now() >= auto_close_cutoff(program_rec, store):
        program_rec["status"] = "CLOSED"
        db.touch(program_rec)
    return program_rec


def refresh_store_programs(store_id):
    """Auto-close evaluation for every ACTIVE program of a store."""
    for prog in db.programs.values():
        if prog["store_id"] == store_id and prog["status"] == "ACTIVE":
            refresh_program_status(prog)


def add_months(instant, months):
    """Advance by whole calendar months, clamping the day to the target
    month's last day (issued 2026-01-31 + 1 month -> 2026-02-28)."""
    y, m = instant.year, instant.month
    m0 = m - 1 + months
    y += m0 // 12
    m = m0 % 12 + 1
    d = min(instant.day, calendar.monthrange(y, m)[1])
    return datetime(y, m, d, instant.hour, instant.minute, instant.second,
                    instant.microsecond, tzinfo=timezone.utc)


def expiry_instant(store, issued_at):
    """expires_at = issued_at + certificate_validity_months whole calendar
    months, snapped to 00:00:00Z of the resulting calendar day
    (PRD 3.6; calculation certificate_expiry_timestamp)."""
    shifted = add_months(issued_at, store["certificate_validity_months"])
    return day_start_utc(shifted.date())


REISSUE_GRACE_DAYS = 30


def reissue_deadline(certificate):
    """Reissue is permitted while logical clock < expires_at + 30 days."""
    return parse_timestamp_iso(certificate["expires_at"]) + timedelta(
        days=REISSUE_GRACE_DAYS)


MAX_RESUBMITS = 3

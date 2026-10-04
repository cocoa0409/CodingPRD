"""The logical clock and every configured window constant.

The service never reads wall-clock time.  The logical clock starts at exactly
2026-09-01T00:00:00Z and moves only when a caller sets it or advances it.

Window lengths are configured once for the service (PRD 3.3, 2.6).  The
schedule-to-trigger windows are pinned to the only figures the specification
supplies in worked form (authorization validity of 180 days, 2026-09-01 ->
2027-02-28, and the pregnancy-test interval, where a 2026-09-30 transfer is
already OUTCOME_PENDING by 2026-10-14).
"""

from datetime import datetime, timedelta, timezone

DEFAULT_CLOCK = "2026-09-01T00:00:00Z"

# --- Configured windows -----------------------------------------------------
AUTHORIZATION_WINDOW_DAYS = 180       # 2026-09-01 -> 2027-02-28
PREGNANCY_TEST_DAYS = 14
SUBMITTED_EXPIRY_HOURS = 45 * 24      # submission-expiry interval in hours
CLAIM_PEND_AFTER_DAYS = 90            # late-submission interval
APPEAL_WINDOW_DAYS = 90
REVERSAL_WINDOW_DAYS = 90
AMENDMENT_WINDOW_DAYS = 120
STORAGE_RETENTION_DAYS = 30
PREROUTE_LEAD_DAYS = 0                # routes ride the clock; no lead time


def parse_dt(value):
    """Parse an ISO 8601 instant into an aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """Render an instant as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    if isinstance(dt, str):
        dt = parse_dt(dt)
    dt = dt.astimezone(timezone.utc).replace(microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def fmt_now_string(dt):
    """Render an instant for the logical clock read-back (whole seconds)."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


class Clock:
    """Single logical clock; every time-dependent read is measured against it."""

    def __init__(self):
        self.now = parse_dt(DEFAULT_CLOCK)

    def set(self, value):
        self.now = parse_dt(value)
        return self.now

    def advance_to(self, value):
        dt = parse_dt(value)
        if dt > self.now:
            self.now = dt
        return self.now

    def days_after(self, dt, days):
        return dt + timedelta(days=days)

    def hours_after(self, dt, hours):
        return dt + timedelta(hours=hours)
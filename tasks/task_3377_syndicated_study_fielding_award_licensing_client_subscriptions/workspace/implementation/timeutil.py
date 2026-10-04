"""Time helpers: ISO8601 parsing/rendering and calendar-month arithmetic.

Two renderings are used:
- iso3(): always three fractional digits (created_at / updated_at / request
  timestamps per PRD section 2.4).
- iso(): canonical logical-clock instants (no fractional part when the
  microsecond is zero, three fractional digits otherwise) — used for
  clock-driven domain instants (submitted_at, activated_at, expires_at,
  published_at, embargo_lift_at, starts_at/ends_at echoes, current_utc).
"""
import uuid
from calendar import monthrange
from datetime import datetime, timezone


def parse_iso(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def iso3(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def add_months(dt, months):
    total = (dt.year * 12 + (dt.month - 1)) + months
    y, m0 = divmod(total, 12)
    m = m0 + 1
    d = min(dt.day, monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=d)


def new_id():
    return str(uuid.uuid4())

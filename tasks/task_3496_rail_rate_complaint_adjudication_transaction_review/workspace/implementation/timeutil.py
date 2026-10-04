"""Timestamp parsing and rendering.

Two rendering families (PRD 2.4):
  - identity block (created_at / updated_at / api_request_timestamp): ISO-8601
    UTC with exactly three fractional digits.
  - domain timestamps (issued_at / expires_at / comment_close_at /
    nitu_expires_at): rendered exactly as the logical clock read when they were
    computed (the clock's own fractional-digit shape, default none).
"""
import re
from datetime import datetime, timezone

_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_FRAC_RE = re.compile(r'\.(\d+)')


def parse_instant(value):
    """Parse an ISO-8601 instant; returns (datetime_utc, frac_digits) or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    zulu = text.endswith('Z')
    core = text[:-1] if zulu else text
    try:
        dt = datetime.fromisoformat(core)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    frac = 0
    m = _FRAC_RE.search(core)
    if m:
        frac = len(m.group(1))
    return dt, frac


def parse_date(value):
    """Parse a strict YYYY-MM-DD date; returns a date or None."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        return None


def render_identity(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + '{:03d}Z'.format(dt.microsecond // 1000)


def render_domain(dt, frac_digits):
    base = dt.strftime('%Y-%m-%dT%H:%M:%S')
    if frac_digits > 0:
        micro = '{:06d}'.format(dt.microsecond)
        return '{}.{}Z'.format(base, micro[:frac_digits].ljust(frac_digits, '0'))
    return base + 'Z'

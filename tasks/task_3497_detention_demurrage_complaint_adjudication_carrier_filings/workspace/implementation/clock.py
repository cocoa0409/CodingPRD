"""Server-side logical clock — the ONLY source of time for the platform.

Boot default: 2026-09-01T00:00:00Z. Advanced only via POST /_clock/set_current_utc.
Two rendering families (PRD §2.4/§2.5):
  * created_at / updated_at / api_request_timestamp -> exactly 3 fractional digits
  * domain timestamps (filed_at, issued_at, deadlines, ...) -> rendered "as the
    logical clock reads": the fractional-digit style of the most recent clock set
    (default: no fractional digits).
"""
import re
from datetime import datetime, timezone

DEFAULT_ISO = "2026-09-01T00:00:00Z"

_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.(\d+))?(?:Z|[+-]\d{2}:?\d{2})?$"
)


def parse_iso(value):
    """Parse an ISO-8601 string -> (aware UTC datetime, fractional digit count)."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    m = _ISO_RE.match(s)
    if not m:
        raise ValueError("not iso8601: %r" % value)
    frac = len(m.group(1)) if m.group(1) else 0
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc), frac


def format_dt(dt, frac_digits):
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if frac_digits > 0:
        frac_str = "%06d" % dt.microsecond
        if frac_digits <= 6:
            frac_str = frac_str[:frac_digits]
        else:
            frac_str = frac_str + "0" * (frac_digits - 6)
        base += "." + frac_str
    return base + "Z"


class LogicalClock:
    def __init__(self):
        self._dt = None
        self._frac = 0
        self.set(DEFAULT_ISO)

    def set(self, iso):
        dt, frac = parse_iso(iso)
        self._dt = dt
        self._frac = frac

    def now(self):
        return self._dt

    def render(self, dt=None):
        """Domain-timestamp family: as the clock reads."""
        return format_dt(dt if dt is not None else self._dt, self._frac)

    def render_precise(self, dt=None):
        """System-timestamp family: exactly three fractional digits."""
        return format_dt(dt if dt is not None else self._dt, 3)


CLOCK = LogicalClock()

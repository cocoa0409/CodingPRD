"""In-memory data store and logical clock.

Storage is dict-of-dicts keyed by resource id. Everything lives in process
memory; nothing is persisted to disk. The store starts empty on every boot.
"""
import uuid
from datetime import datetime, timezone

CLOCK_DEFAULT_START = "2026-09-01T00:00:00Z"


def parse_iso(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Accepts a trailing 'Z' or a numeric offset; naive values are assumed UTC.
    Raises ValueError on unparseable input.
    """
    if not isinstance(value, str):
        raise ValueError("datetime must be a string")
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def render_bookkeeping(dt):
    """Bookkeeping timestamps (created_at/updated_at/api_request_timestamp):
    ISO 8601 UTC with exactly three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class _Clock:
    """The controllable logical clock. `raw` is the string exactly as last
    supplied (domain timestamps render as the clock reads); `dt` is the parsed
    instant used for gate arithmetic."""

    def __init__(self):
        self.raw = CLOCK_DEFAULT_START
        self.dt = parse_iso(CLOCK_DEFAULT_START)

    def set(self, raw):
        self.dt = parse_iso(raw)
        self.raw = raw


clock = _Clock()

STORE = {
    "funding_programs": {},
    "apportionments": {},
    "stips": {},
    "comments": {},
    "projects": {},
    "clearances": {},
    "authorizations": {},
    "bids": {},
    "vouchers": {},
    "change_orders": {},
    "audits": {},
}


def new_id():
    """Server-minted UUID, dashed form (never uuid4().hex)."""
    return str(uuid.uuid4())


def now_bookkeeping():
    return render_bookkeeping(clock.dt)


def touch(entity):
    """Refresh updated_at and bump version by exactly 1 (one logical mutation)."""
    entity["updated_at"] = now_bookkeeping()
    entity["version"] += 1

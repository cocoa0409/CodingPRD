import uuid
import secrets
import string
from datetime import datetime, timezone, timedelta

# Logical clock: startup default exactly 2026-09-01T00:00:00Z
_clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def get_clock():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


def now_iso():
    """Current logical clock as ISO8601 UTC with millisecond precision."""
    return format_dt(_clock)


def format_dt(dt):
    if dt is None:
        return None
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f'{dt.microsecond // 1000:03d}Z'


def wall_iso():
    """Wall-clock timestamp for meta (request receipt), ISO8601 with ms."""
    dt = datetime.now(timezone.utc)
    return format_dt(dt)


def parse_dt(s):
    """Parse an ISO8601 string into an aware UTC datetime. Returns None on failure."""
    if not isinstance(s, str):
        return None
    try:
        t = s.strip()
        if t.endswith('Z'):
            t = t[:-1] + '+00:00'
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def new_id():
    return str(uuid.uuid4())


def req_id():
    return 'req_' + ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(22))


# In-memory stores: dicts keyed by id. Start empty on every boot.
db = {
    'product_categories': {},
    'test_programs': {},
    'lab_protocols': {},
    'test_samples': {},
    'purchase_orders': {},
    'measurements': {},
    'survey_waves': {},
    'rating_publications': {},
    'safety_findings': {},
    'members': {},
}

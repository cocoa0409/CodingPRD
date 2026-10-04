"""In-memory data store, logical clock, ids, and timestamps.

Storage is in-memory only (Python dicts keyed by id). The store starts empty
on every boot; nothing is seeded. The logical clock defaults to the fixed
2026-09-01T00:00:00Z and only moves via POST /ja-programs/_clock/set_current_utc.
"""
import re
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

STORES = {
    'area_offices': {},
    'districts': {},
    'schools': {},
    'partners': {},
    'volunteers': {},
    'programs': {},
    'agreements': {},
    'deliveries': {},
    'sessions': {},
    'inventories': {},
    'capstones': {},
    'students': {},
}

CLOCK = {'now': DEFAULT_CLOCK}
_SEQ = [0]
_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def next_seq():
    _SEQ[0] += 1
    return _SEQ[0]


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Wall-clock UTC timestamp with three fractional digits (PRD 2.2/2.5)."""
    n = datetime.now(timezone.utc)
    return n.strftime('%Y-%m-%dT%H:%M:%S') + '.%03dZ' % (n.microsecond // 1000)


def render_dt(dt):
    """Canonical ISO 8601 UTC render for logical-clock datetimes."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    return dt.strftime('%Y-%m-%dT%H:%M:%S') + '.%03dZ' % (dt.microsecond // 1000)


def parse_datetime(s):
    """Parse an ISO 8601 datetime; returns aware UTC datetime or None."""
    if not isinstance(s, str):
        return None
    t = s.strip()
    if t.endswith('Z'):
        t = t[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    """Parse a strict ISO YYYY-MM-DD date; returns a date or None."""
    if not isinstance(s, str) or not _DATE_RE.match(s):
        return None
    try:
        return datetime.strptime(s, '%Y-%m-%d').date()
    except ValueError:
        return None


def make_record(fields):
    ts = now_iso()
    rec = {
        'id': new_id(),
        'created_at': ts,
        'updated_at': ts,
        'version': 1,
        '_seq': next_seq(),
    }
    rec.update(fields)
    return rec


def touch(rec):
    """Mark a mutation: refresh updated_at and bump version by 1 (PRD 2.5)."""
    rec['updated_at'] = now_iso()
    rec['version'] += 1


def logical_now():
    return CLOCK['now']


def logical_today():
    return CLOCK['now'].date()


def set_clock(dt):
    CLOCK['now'] = dt

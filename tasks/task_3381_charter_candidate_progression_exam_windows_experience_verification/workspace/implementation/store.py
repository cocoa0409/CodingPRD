"""In-memory data store and the program's logical clock.

Storage is process-local dicts keyed by id; every boot starts completely
empty. The logical clock defaults to exactly 2026-09-01T00:00:00Z and never
falls back to wall-clock time.
"""
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.candidates = {}
        self.enrollments = {}
        self.levels = {}
        self.cycles = {}
        self.windows = {}
        self.centers = {}
        self.appointments = {}
        self.attempts = {}
        self.submissions = {}
        self.references = {}
        self.cases = {}
        self.societies = {}
        self.memberships = {}
        self.clock = DEFAULT_CLOCK
        self.seq = 0  # global creation-order counter (tie-breaks equal created_at)


DB = Store()


def now():
    return DB.clock


def today():
    return DB.clock.date()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    DB.seq += 1
    return DB.seq


def iso(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-09-01T00:00:00.000Z."""
    if dt is None:
        return None
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + '%03dZ' % (dt.microsecond // 1000)


def wall_iso():
    return iso(datetime.now(timezone.utc))


def parse_dt(s):
    if not isinstance(s, str) or not s.strip():
        raise ValueError('bad datetime')
    t = s.strip()
    if t.endswith('Z'):
        t = t[:-1] + '+00:00'
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    if not isinstance(s, str):
        raise ValueError('bad date')
    return datetime.strptime(s.strip(), '%Y-%m-%d').date()


def midnight_utc(date_str):
    d = parse_date(date_str)
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def touch(entity):
    """Refresh updated_at and bump version (one mutation of the resource)."""
    entity['updated_at'] = iso(now())
    entity['version'] += 1


def base_fields():
    ts = iso(now())
    return {'id': new_id(), 'created_at': ts, 'updated_at': ts,
            'version': 1, '_seq': next_seq()}


def months_between(s, e):
    """Whole calendar months per PRD 2.9: year diff * 12 + month diff,
    minus one if the end day-of-month is earlier than the start's."""
    return (e.year - s.year) * 12 + (e.month - s.month) - (1 if e.day < s.day else 0)

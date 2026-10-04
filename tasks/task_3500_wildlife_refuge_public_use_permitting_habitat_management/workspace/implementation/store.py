"""In-memory data store + logical clock. Store starts EMPTY on every boot;
no seeding of any entity. Logical clock starts at exactly 2026-09-01T00:00:00Z
and never falls back to wall-clock time (PRD section 2.5)."""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.units = {}
        self.determinations = {}
        self.comments = {}
        self.permits = {}
        self.treatments = {}
        self.closures = {}
        self.programs = {}
        self.volunteers = {}
        self.assignments = {}
        self.offerings = {}
        self.bids = {}
        self.agreements = {}
        self.citations = {}
        self.objectives = {}
        self.seq = 0
        self.clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


DB = Store()


def new_id():
    # Dashed UUID, never uuid4().hex (downstream UUID validation needs dashes).
    return str(uuid.uuid4())


def clock_date():
    """UTC date portion of the logical clock; basis of every date comparison."""
    return DB.clock.date()


def fmt_ts3(dt):
    """Audit-family timestamp: ISO 8601 UTC with exactly three fractional digits."""
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f'{dt.microsecond // 1000:03d}Z'


def now_ts3():
    return fmt_ts3(DB.clock)


def render_clock():
    """current_utc renders as the clock reads (no forced fractional digits)."""
    dt = DB.clock
    if dt.microsecond:
        return fmt_ts3(dt)
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def next_seq():
    DB.seq += 1
    return DB.seq


def new_record(fields):
    ts = now_ts3()
    rec = {
        'id': new_id(),
        'created_at': ts,
        'updated_at': ts,
        'version': 1,
        '_seq': next_seq(),
    }
    rec.update(fields)
    return rec


def mutate(rec, force=False, **changes):
    """Apply field changes; bump updated_at/version only when a value actually
    changes (a recompute landing on the same value is not a modification).
    One mutate call = exactly one version increment (PRD 2.4).
    force=True bumps updated_at/version exactly once even when no field value
    changed — required on the four pinned agreement write paths (period
    assessment, ledger entry, agreement-subject citation issue/void), which
    PRD 2.4 defines as modifications regardless of amount."""
    dirty = False
    for k, v in changes.items():
        if rec.get(k) != v:
            rec[k] = v
            dirty = True
    if dirty or force:
        rec['updated_at'] = now_ts3()
        rec['version'] += 1
    return rec


def pub(rec, fields):
    return {k: rec.get(k) for k in fields}

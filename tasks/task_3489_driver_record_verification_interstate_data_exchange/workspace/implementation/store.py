"""In-memory data store and the logical clock (PRD sections 2.4 and 2.5).

All state lives in plain dicts keyed by resource id. A fresh process boots with
an empty store and the logical clock at exactly 2026-09-01T00:00:00Z; nothing is
seeded or preloaded.
"""
import uuid
from datetime import date, datetime, timezone

DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"


def parse_datetime(value):
    """Parse an ISO 8601 datetime; naive values are treated as UTC."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a strict YYYY-MM-DD calendar date."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if len(text) != 10 or text[4] != "-" or text[7] != "-":
        raise ValueError("not YYYY-MM-DD")
    year = int(text[0:4])
    month = int(text[5:7])
    day = int(text[8:10])
    return date(year, month, day)


def format_datetime(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD section 2.5)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.jurisdictions = {}
        self.participations = {}
        self.certifications = {}
        self.drivers = {}
        self.records = {}
        self.licenses = {}
        self.license_transfers = {}
        self.convictions = {}
        self.disqualifications = {}
        self.vehicle_titles = {}
        self.title_transfers = {}
        self.fee_invoices = {}
        self.clock = parse_datetime(DEFAULT_CLOCK_ISO)
        self.seq = 0


db = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    return db.clock


def now_iso():
    return format_datetime(db.clock)


def today():
    return db.clock.date()


def stamp(entity):
    """Apply the common system fields at creation: created_at, updated_at,
    version (PRD section 2.5). _seq is an internal insertion counter used only
    as a deterministic sort tiebreak."""
    ts = now_iso()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    db.seq += 1
    entity["_seq"] = db.seq
    return entity


def stamp_conviction(entity):
    """Convictions are immutable: they carry id and created_at only, with no
    updated_at and no version (PRD section 2.5)."""
    entity["created_at"] = now_iso()
    db.seq += 1
    entity["_seq"] = db.seq
    return entity


def touch(entity):
    """Refresh updated_at and increment version on a mutation."""
    entity["updated_at"] = now_iso()
    entity["version"] += 1


def sorted_by_created(items):
    """created_at ascending; stable and deterministic via the insertion
    counter for resources minted at the same logical instant."""
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))

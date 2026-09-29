"""In-memory store. Nothing is seeded: every collection starts empty on boot."""

import itertools
import threading
import uuid
from datetime import datetime, timedelta, timezone

from constants import CLOCK_EPOCH

LOCK = threading.RLock()

COLLECTIONS = [
    "allotments",
    "pastures",
    "permittees",
    "base_properties",
    "permits",
    "aois",
    "use_records",
    "bills",
    "assessments",
    "decisions",
    "appeals",
    "closure_orders",
    "trespass_incidents",
    "projects",
]

DB = {name: {} for name in COLLECTIONS}

_SEQ = itertools.count(1)

CLOCK = {"now": None}


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_SEQ)


# ------------------------------------------------------------------ wall clock


_WALL_LOCK = threading.Lock()
_WALL_LAST = {"value": None}


def _fmt_wall(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (moment.microsecond // 1000)


def wall_now_iso():
    """A strictly increasing millisecond stamp, so a mutation is always visible."""
    with _WALL_LOCK:
        text = _fmt_wall(datetime.now(timezone.utc))
        last = _WALL_LAST["value"]
        if last is not None and text <= last:
            text = _fmt_wall(parse_instant(last) + timedelta(milliseconds=1))
        _WALL_LAST["value"] = text
        return text


# --------------------------------------------------------------- logical clock


def parse_instant(text):
    """Parse an ISO-8601 UTC instant with a trailing Z. Returns None when invalid."""
    if not isinstance(text, str) or not text.endswith("Z"):
        return None
    body = text[:-1]
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(body, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def format_instant(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (moment.microsecond // 1000)


def canonical_instant(text):
    moment = parse_instant(text)
    return format_instant(moment) if moment else text


def clock_now():
    if CLOCK["now"] is None:
        CLOCK["now"] = parse_instant(CLOCK_EPOCH)
    return CLOCK["now"]


def clock_set(moment):
    CLOCK["now"] = moment


def clock_date():
    return clock_now().date()


def current_grazing_year():
    return clock_now().year


def add_days(day, count):
    return day + timedelta(days=count)


# ------------------------------------------------------------ record lifecycle


def insert(collection, record):
    record["_seq"] = next_seq()
    stamp = wall_now_iso()
    record.setdefault("id", new_id())
    record["created_at"] = stamp
    record["updated_at"] = stamp
    record["version"] = 1
    DB[collection][record["id"]] = record
    return record


def touch(record):
    """Register a mutation: refresh updated_at and advance version by one."""
    record["updated_at"] = wall_now_iso()
    record["version"] = record.get("version", 1) + 1
    return record


def get(collection, record_id):
    if not isinstance(record_id, str):
        return None
    return DB[collection].get(record_id)


def rows(collection):
    """All rows of a collection in insertion order."""
    return list(DB[collection].values())


def where(collection, **criteria):
    out = []
    for record in DB[collection].values():
        if all(record.get(key) == value for key, value in criteria.items()):
            out.append(record)
    return out


def reset():
    for name in COLLECTIONS:
        DB[name].clear()
    CLOCK["now"] = parse_instant(CLOCK_EPOCH)

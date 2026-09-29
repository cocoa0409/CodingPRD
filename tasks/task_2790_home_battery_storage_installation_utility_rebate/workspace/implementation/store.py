"""In-memory store. Process-local dictionaries only -- nothing is persisted, so a
fresh process always starts with an empty world and a logical clock at the epoch.
"""

from decimal import Decimal

from common import LOGICAL_CLOCK_EPOCH, new_uuid, wall_now_iso

TABLES = (
    "installers",
    "sites",
    "load_calculations",
    "battery_systems",
    "permits",
    "applications",
    "programs",
    "claims",
    "tests",
    "alerts",
    "enrollments",
    "events",
    "performances",
)


class _State(object):
    def __init__(self):
        self.tables = {}
        self.clock = LOGICAL_CLOCK_EPOCH
        self.seq = 0
        self.reset()

    def reset(self):
        self.tables = dict((name, {}) for name in TABLES)
        self.clock = LOGICAL_CLOCK_EPOCH
        self.seq = 0


DB = _State()


# --------------------------------------------------------------------------- #
# Logical clock
# --------------------------------------------------------------------------- #

def now():
    """Current logical clock reading (never wall-clock time)."""
    return DB.clock


def set_clock(iso_value):
    DB.clock = iso_value
    return DB.clock


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #

def _next_seq():
    DB.seq += 1
    return DB.seq


def insert(table, fields):
    stamp = wall_now_iso()
    record = dict(fields)
    record["id"] = new_uuid()
    record["created_at"] = stamp
    record["updated_at"] = stamp
    record["version"] = 1
    record["_seq"] = _next_seq()
    record["_table"] = table
    DB.tables[table][record["id"]] = record
    return record


def touch(record):
    """Register a mutation: refresh updated_at and advance version by exactly one."""
    record["updated_at"] = wall_now_iso()
    record["version"] += 1
    return record


def get(table, ident):
    if not isinstance(ident, str):
        return None
    return DB.tables[table].get(ident)


def rows(table):
    """All records of a table in created_at ascending order (insertion order breaks ties)."""
    return sorted(DB.tables[table].values(), key=lambda r: (r["created_at"], r["_seq"]))


def where(table, **filters):
    result = []
    for record in rows(table):
        keep = True
        for key, value in filters.items():
            if value is None:
                continue
            if record.get(key) != value:
                keep = False
                break
        if keep:
            result.append(record)
    return result


# --------------------------------------------------------------------------- #
# Serialization
# --------------------------------------------------------------------------- #

def _plain(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return dict((k, _plain(v)) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def view(record):
    """Public JSON projection of a record: private keys dropped, Decimals as numbers."""
    if record is None:
        return None
    out = {}
    for key, value in record.items():
        if key.startswith("_"):
            continue
        out[key] = _plain(value)
    return out


def views(records):
    return [view(record) for record in records]

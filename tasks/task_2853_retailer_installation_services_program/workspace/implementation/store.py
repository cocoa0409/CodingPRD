"""In-memory store and logical clock for the Retailer Installation Services API.

Every byte of state lives in module-level dicts. A fresh process starts empty:
no seeding, no preloading, no persistence of any kind.
"""
import uuid
from datetime import datetime, timedelta, timezone

# --- logical clock -----------------------------------------------------------
# PRD 2.4: the server's startup default is EXACTLY 2026-08-01T00:00:00.000Z and
# the clock never falls back to wall-clock time.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=timezone.utc)

_clock = {"now": CLOCK_DEFAULT}


def now():
    return _clock["now"]


def set_now(value):
    _clock["now"] = value


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def parse_instant(text):
    """Parse an ISO-8601 UTC instant with exactly three fractional digits.

    Returns None when the shape is not exactly what the contract demands.
    """
    if not isinstance(text, str) or len(text) != 24:
        return None
    if text[4] != "-" or text[7] != "-" or text[10] != "T":
        return None
    if text[13] != ":" or text[16] != ":" or text[19] != "." or text[23] != "Z":
        return None
    try:
        base = datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    frac = text[20:23]
    if not frac.isdigit():
        return None
    return base.replace(microsecond=int(frac) * 1000, tzinfo=timezone.utc)


# --- collections -------------------------------------------------------------
COLLECTIONS = (
    "service_categories",
    "jurisdictions",
    "installers",
    "installer_credentials",
    "customers",
    "projects",
    "measurements",
    "change_orders",
    "material_deliveries",
    "installer_assignments",
    "punch_list_items",
    "warranty_claims",
    "scorecard_events",
)

DB = {name: {} for name in COLLECTIONS}

_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_id():
    return str(uuid.uuid4())


def insert(collection, row, common_fields=True):
    """Insert a row, minting id / created_at / updated_at / version."""
    ts = now()
    row["id"] = new_id()
    row["created_at"] = ts
    if common_fields:
        row["updated_at"] = ts
        row["version"] = 1
    row["_seq"] = next_seq()
    DB[collection][row["id"]] = row
    return row


def touch(row):
    """Bump version and updated_at on every mutation, cascades included."""
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = now()
    return row


def get(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return DB[collection].get(row_id)


def all_rows(collection):
    return list(DB[collection].values())


def days_after(dt, whole_days):
    return dt + timedelta(days=whole_days)


def whole_days_between(earlier, later):
    """Whole days from `earlier` to `later`, floored."""
    delta = later - earlier
    return int(delta.total_seconds() // 86400)

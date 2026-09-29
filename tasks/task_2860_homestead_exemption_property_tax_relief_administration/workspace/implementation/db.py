"""In-memory data store, the logical assessment clock (PRD §2.5) and row helpers.

Everything lives in process memory only.  A fresh process starts with a
completely empty store and the clock pinned to the fixed default instant; no
entity is ever seeded here.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

# --------------------------------------------------------------------------
# The logical assessment clock — begins at the fixed instant and only ever
# moves when a ProgramAdministrator sets it.  There is no wall-clock fallback.
# --------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_clock = {"now": DEFAULT_CLOCK}

APPEAL_WINDOW_DAYS = 30
HEARING_BUFFER_MINUTES = 15
MAX_INFO_REQUEST_ROUNDS = 2
MAX_CONTINUANCES = 2
SENIOR_MIN_AGE = 65
COUNTY_MILL_RATE_BPS = 125
REFUND_INTEREST_BPS_PER_YEAR = 400
RISK_SUBSTANTIATION_THRESHOLD = 60
DEFAULT_ASSESSMENT_CAP_PCT_BPS = 200


def now():
    return _clock["now"]


def set_now(dt):
    _clock["now"] = dt.astimezone(timezone.utc)
    return _clock["now"]


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return iso(now())


def plus_days(dt, days):
    return dt + timedelta(days=days)


# --------------------------------------------------------------------------
# Collections
# --------------------------------------------------------------------------
COLLECTIONS = (
    "relief_programs",
    "parcels",
    "taxpayer_accounts",
    "ownership_records",
    "exemption_applications",
    "verification_checks",
    "income_certifications",
    "exemption_grants",
    "retroactive_claims",
    "fraud_cases",
    "notices",
    "hearing_dockets",
    "appeals",
    "registry_records",
)

store = {name: {} for name in COLLECTIONS}

_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def insert(collection, row, versioned=True):
    stamp = now_iso()
    row.setdefault("id", new_id())
    row["created_at"] = stamp
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    row["_seq"] = next(_seq)
    store[collection][row["id"]] = row
    return row


def touch(row):
    """Record a mutation: refresh updated_at and advance version by exactly 1."""
    row["updated_at"] = now_iso()
    row["version"] = row.get("version", 1) + 1
    return row


def get(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return store[collection].get(row_id)


def order_key(row):
    return (row.get("created_at") or "", row.get("_seq") or 0)


def rows(collection):
    """Every row of a collection in created_at ascending order."""
    return sorted(store[collection].values(), key=order_key)


def find(collection, **filters):
    out = []
    for row in rows(collection):
        if all(row.get(k) == v for k, v in filters.items()):
            out.append(row)
    return out


def latest(candidates, key=None):
    """The greatest row by created_at (tie-break insertion order), or a custom key."""
    if not candidates:
        return None
    return sorted(candidates, key=key or order_key)[-1]


def public(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}

"""Core primitives: error catalog, response envelope, logical clock, data store.

Fresh Doughnut Hub-and-Spoke Distribution & Theater Store Operations.
Storage is entirely in-memory; the store starts empty on every boot and nothing
is ever seeded — every entity a test needs is built through the API surface.
"""
import re
import uuid
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Error catalog (PRD §5 / SCAFFOLD §1.6)
# ---------------------------------------------------------------------------
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_FRESHNESS_VIOLATION": 422,
    "ERR_WINDOW_OVERLAP": 422,
    "ERR_TERRITORY_VIOLATION": 422,
    "ERR_LICENSE_QUOTA_EXCEEDED": 422,
    "ERR_CAPACITY_EXCEEDED": 422,
    "ERR_CROSS_SCOPE_REFERENCE": 422,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_LINE_BUSY": 409,
    "ERR_PICKUP_CODE_MISMATCH": 422,
    "ERR_ROUTE_NOT_LOCKABLE": 422,
    "ERR_STOP_WINDOW_PASSED": 422,
    "ERR_DEMAND_CAP_EXCEEDED": 422,
    "ERR_VARIETY_EXPIRED": 422,
    "ERR_DUPLICATE_SEQUENCE": 422,
    "ERR_MIX_PLAN_LOCKED": 409,
}

ERROR_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required and the role must be recognized.",
    "ERR_UNAUTHORIZED": "The acting role is not permitted to perform this operation.",
    "ERR_NOT_FOUND": "A path resource does not exist.",
    "ERR_INVALID_REQUEST": "The request is missing a required field or carries a malformed value.",
    "ERR_INVALID_STATE": "The target resource state does not permit the requested transition.",
    "ERR_STALE_VERSION": "The expected version does not match the current version.",
    "ERR_FRESHNESS_VIOLATION": "The operation breaches a freshness, lead-time, or grace bound.",
    "ERR_WINDOW_OVERLAP": "Temporal windows overlap or are inverted.",
    "ERR_TERRITORY_VIOLATION": "The door territory does not match the supplying hub territory, a THEATER door carries a hub, or a hot-light window targets a non-THEATER door.",
    "ERR_LICENSE_QUOTA_EXCEEDED": "LICENSED varieties exceed 25 percent of the mix plan.",
    "ERR_CAPACITY_EXCEEDED": "A capacity limit would be exceeded.",
    "ERR_CROSS_SCOPE_REFERENCE": "A referenced entity is missing or belongs to a different network or hub scope.",
    "ERR_ALREADY_TERMINAL": "The resource is already in a terminal state.",
    "ERR_LINE_BUSY": "Another batch is RUNNING on the equipment line.",
    "ERR_PICKUP_CODE_MISMATCH": "The pickup code does not match.",
    "ERR_ROUTE_NOT_LOCKABLE": "The route has no stops or its total window span is under 30 minutes.",
    "ERR_STOP_WINDOW_PASSED": "Arrival was attempted after the delivery window closed.",
    "ERR_DEMAND_CAP_EXCEEDED": "The requested extension exceeds the demand-response cap for the current fresh dozens.",
    "ERR_VARIETY_EXPIRED": "A mix plan line references a variety whose selling window has expired for the plan's effective date.",
    "ERR_DUPLICATE_SEQUENCE": "The stop sequence number is duplicated within the route.",
    "ERR_MIX_PLAN_LOCKED": "The mix plan is LOCKED or SUPERSEDED and no longer accepts line upserts.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or ERROR_MESSAGES.get(error_id, "Request failed.")
        super().__init__(self.message)


def err(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.5) — starts at 2026-09-01T00:00:00Z; never falls back
# to wall-clock time.
# ---------------------------------------------------------------------------
CLOCK_START = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = CLOCK_START

    def set(self, iso_value):
        self.now = parse_dt(iso_value, "to_iso8601")


CLOCK = Clock()


def now():
    return CLOCK.now


def today_str():
    return now().date().isoformat()


def iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def iso_min(dt):
    """Render a domain datetime (client-supplied instants and values derived
    from them) without fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def norm_now():
    n = now()
    return n.replace(microsecond=(n.microsecond // 1000) * 1000)


_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_dt(value, field="datetime"):
    if not isinstance(value, str):
        err("ERR_INVALID_REQUEST", "%s must be an ISO 8601 timestamp string." % field)
    try:
        s = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
    except Exception:
        err("ERR_INVALID_REQUEST", "%s is not a valid ISO 8601 instant." % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value, field="date"):
    if not isinstance(value, str) or not _ISO_DATE_RE.match(value):
        err("ERR_INVALID_REQUEST", "%s must be an ISO date (YYYY-MM-DD)." % field)
    return value


def touch(row):
    row["updated_at"] = iso(norm_now())
    row["version"] = int(row.get("version", 0)) + 1


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# In-memory store — empty at boot; nothing seeded.
# ---------------------------------------------------------------------------
TABLES = [
    "networks", "hubs", "doors", "lines", "varieties", "mix_plans",
    "mix_plan_lines", "batches", "routes", "stops", "shipments",
    "stale_credits", "fundraisers", "hot_light_windows",
]


class Store:
    def __init__(self):
        self.tables = {t: {} for t in TABLES}


DB = Store()


def create_row(table, fields, version=1):
    row = dict(fields)
    row["id"] = new_id()
    row["created_at"] = iso(norm_now())
    row["updated_at"] = row["created_at"]
    row["version"] = version
    DB.tables[table][row["id"]] = row
    return row


def table(name):
    return DB.tables[name]


def get(table_name, rid):
    if rid is None:
        return None
    return DB.tables[table_name].get(rid)


def find(table_name, predicate):
    return [r for r in DB.tables[table_name].values() if predicate(r)]


def find_one(table_name, predicate):
    for r in DB.tables[table_name].values():
        if predicate(r):
            return r
    return None


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit/offset; defaults 10/0; limit clamped to 1..100.
# Sort: created_at ascending.
# ---------------------------------------------------------------------------
def pagination_args(args):
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    try:
        limit = 10 if raw_limit in (None, "") else int(raw_limit)
    except (TypeError, ValueError):
        err("ERR_INVALID_REQUEST", "limit must be an integer.")
    try:
        offset = 0 if raw_offset in (None, "") else int(raw_offset)
    except (TypeError, ValueError):
        err("ERR_INVALID_REQUEST", "offset must be an integer.")
    if limit < 1 or limit > 100:
        err("ERR_INVALID_REQUEST", "limit must lie between 1 and 100.")
    if offset < 0:
        err("ERR_INVALID_REQUEST", "offset must be non-negative.")
    return limit, offset


def page(rows, limit, offset):
    rows = sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("id") or ""))
    total = len(rows)
    window = rows[offset:offset + limit]
    has_more = offset + limit < total
    return window, {"limit": limit, "offset": offset, "total_count": total,
                    "has_more": has_more}


def overlapping(a_start, a_end, b_start, b_end):
    """Half-open interval overlap: [a_start, a_end) vs [b_start, b_end)."""
    return a_start < b_end and b_start < a_end

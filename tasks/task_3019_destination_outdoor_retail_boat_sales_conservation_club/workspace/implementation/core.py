"""Core primitives: error catalog, response envelope, logical clock, data store."""
import uuid
import threading
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Error catalog (§1.6 / PRD §5)
# ---------------------------------------------------------------------------
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_STORE_NOT_FOUND": 404,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_PARENT_MISMATCH": 404,
    "ERR_BAY_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_POSTURE_FROZEN": 409,
    "ERR_POSTURE_RESTRICTED": 409,
    "ERR_WAIVER_REQUIRED": 422,
    "ERR_WAIVER_EXPIRED": 422,
    "ERR_LANE_CAPACITY_EXCEEDED": 422,
    "ERR_PERMIT_VERIFICATION_REQUIRED": 422,
    "ERR_RECEIVING_CROSS_CHECK_REQUIRED": 422,
    "ERR_NO_SHOW_STRIKE_LIMIT": 422,
    "ERR_TITLE_STATE_MISMATCH": 422,
    "ERR_SESSION_OVERLAP": 409,
    "ERR_BAY_BOOKING_CONFLICT": 409,
    "ERR_EVENT_VENUE_CONFLICT": 409,
    "ERR_INVALID_SLOT_WINDOW": 422,
    "ERR_DUPLICATE_STOCK_NO": 409,
    "ERR_DUPLICATE_HIN": 409,
    "ERR_DUPLICATE_MEMBER_EMAIL": 409,
    "ERR_FULFILLMENT_BLOCKED": 409,
    "ERR_RIGGING_ALREADY_OPEN": 409,
    "ERR_VENUE_CAPACITY_EXCEEDED": 409,
    "ERR_REGISTRATION_CAP_EXCEEDED": 409,
    "ERR_DWELL_BUDGET_EXCEEDED": 409,
    "ERR_EMPTY_REMIT_WINDOW": 422,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_FUNDING_SHORTFALL": 422,
    "ERR_BALANCE_OUTSTANDING": 422,
    "ERR_CREDIT_LIMIT_BELOW_FLOOR": 422,
    "ERR_INVALID_TERM_DAYS": 422,
    "ERR_OUTSTANDING_DEPOSIT_REQUIRED": 422,
    "ERR_TYPE_IMMUTABLE": 422,
    "ERR_INVALID_REQUEST": 400,
    "ERR_STALE_VERSION": 412,
}

ERROR_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required.",
    "ERR_FORBIDDEN_ROLE": "The acting role is not authorized for this operation.",
    "ERR_STORE_NOT_FOUND": "The named store does not exist.",
    "ERR_RESOURCE_NOT_FOUND": "A referenced resource does not exist.",
    "ERR_PARENT_MISMATCH": "The referenced resource does not belong to the named store.",
    "ERR_BAY_NOT_FOUND": "The bay number falls outside the store's bay range.",
    "ERR_INVALID_STATE": "The resource is not in a state from which this transition is permitted.",
    "ERR_ALREADY_TERMINAL": "The resource is already in a terminal state.",
    "ERR_POSTURE_FROZEN": "The store's attraction posture is FROZEN.",
    "ERR_POSTURE_RESTRICTED": "The store's attraction posture is RESTRICTED.",
    "ERR_WAIVER_REQUIRED": "A matching signed liability waiver is required.",
    "ERR_WAIVER_EXPIRED": "The referenced liability waiver is not live.",
    "ERR_LANE_CAPACITY_EXCEEDED": "The requested lane number exceeds the venue's lane capacity.",
    "ERR_PERMIT_VERIFICATION_REQUIRED": "A lawful-take permit is required.",
    "ERR_RECEIVING_CROSS_CHECK_REQUIRED": "A non-empty receiving-manager cross-check code distinct from the member is required.",
    "ERR_NO_SHOW_STRIKE_LIMIT": "The member's effective no-show strike count has reached the limit.",
    "ERR_TITLE_STATE_MISMATCH": "The filing state does not match the store state, or the lien release is invalid.",
    "ERR_SESSION_OVERLAP": "An overlapping session would push the venue over capacity.",
    "ERR_BAY_BOOKING_CONFLICT": "Another booking overlaps this bay reservation inside the turnover buffer.",
    "ERR_EVENT_VENUE_CONFLICT": "Another published offering overlaps this venue slot.",
    "ERR_INVALID_SLOT_WINDOW": "The slot end instant must be strictly after the slot start instant.",
    "ERR_DUPLICATE_STOCK_NO": "The stock number already exists within this store.",
    "ERR_DUPLICATE_HIN": "The hull identification number already exists within this store.",
    "ERR_DUPLICATE_MEMBER_EMAIL": "The member email already exists within this store.",
    "ERR_FULFILLMENT_BLOCKED": "A linked order fulfillment blocks this operation.",
    "ERR_RIGGING_ALREADY_OPEN": "Another non-terminal rigging order is already open for this deal.",
    "ERR_VENUE_CAPACITY_EXCEEDED": "The venue capacity would be exceeded.",
    "ERR_REGISTRATION_CAP_EXCEEDED": "The offering's registration cap would be exceeded.",
    "ERR_DWELL_BUDGET_EXCEEDED": "Publishing this offering would drive the store's free dwell minutes below zero.",
    "ERR_EMPTY_REMIT_WINDOW": "The remittance window contains no eligible permit sale.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties is violated.",
    "ERR_FUNDING_SHORTFALL": "The recorded funding amount is below the deal's balance due.",
    "ERR_BALANCE_OUTSTANDING": "The deal's balance due must be zero or below before settlement.",
    "ERR_CREDIT_LIMIT_BELOW_FLOOR": "The approved credit limit is below the required floor.",
    "ERR_INVALID_TERM_DAYS": "The permit term length or land access units are invalid.",
    "ERR_OUTSTANDING_DEPOSIT_REQUIRED": "The intake deposit is below the required floor.",
    "ERR_TYPE_IMMUTABLE": "The field is immutable at this stage.",
    "ERR_INVALID_REQUEST": "The request is malformed.",
    "ERR_STALE_VERSION": "The expected version does not match the stored version.",
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
# Logical clock — fixed start instant, only moved by the platform capability
# ---------------------------------------------------------------------------
CLOCK_START = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = CLOCK_START

    def set(self, iso):
        try:
            s = str(iso).replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
        except Exception:
            err("ERR_INVALID_REQUEST", "to_iso8601 is not a valid ISO 8601 instant.")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self.now = dt.astimezone(timezone.utc)


CLOCK = Clock()


def now():
    return CLOCK.now


def iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def norm_now():
    """Current clock instant with millisecond precision, as stored on rows."""
    return now().replace(microsecond=(now().microsecond // 1000) * 1000)


def parse_dt(value, field="datetime"):
    if value is None:
        return None
    try:
        s = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
    except Exception:
        err("ERR_INVALID_REQUEST", "%s is not a valid ISO 8601 instant." % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def days_between(start, end):
    return int((end - start).total_seconds() // 86400)


def touch(row):
    row["updated_at"] = iso(norm_now())
    row["version"] = int(row.get("version", 0)) + 1


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# In-memory store. Starts empty on every boot; nothing is ever seeded.
# ---------------------------------------------------------------------------
TABLES = [
    "stores", "members", "attractions", "sessions", "boat_units", "appraisals",
    "service_orders", "title_filings", "boat_deals", "permit_sales",
    "remit_batches", "club_card_applications", "point_events", "event_offerings",
    "event_registrations", "bay_bookings", "order_fulfillments", "service_intakes",
    "waivers",
]

# point_event store-scoped writes need a lookup from batch id
REVERSE_INDEX_KEYS = {
    "sessions": ["attraction_id", "member_id", "waiver_id"],
    "boat_units": ["store_id"],
    "deals": ["store_id"],
}


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.tables = {t: {} for t in TABLES}
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq


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


def require(table_name, rid, error_id="ERR_RESOURCE_NOT_FOUND"):
    if rid is None:
        return None
    row = DB.tables[table_name].get(rid)
    if row is None:
        err(error_id)
    return row
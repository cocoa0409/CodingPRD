"""Core infrastructure: error catalog, logical clock, ids, timing, in-memory store."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# Error catalog — mirrors PRD section 5 exactly
# ---------------------------------------------------------------------------
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_ORGANIZATION_NOT_FOUND": 404,
    "ERR_USER_NOT_FOUND": 404,
    "ERR_PROPERTY_NOT_FOUND": 404,
    "ERR_ATTRIBUTE_NOT_FOUND": 404,
    "ERR_SOURCE_DOCUMENT_NOT_FOUND": 404,
    "ERR_TRANSACTION_NOT_FOUND": 404,
    "ERR_LISTING_NOT_FOUND": 404,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_SEAT_NOT_FOUND": 404,
    "ERR_ENFORCEMENT_CASE_NOT_FOUND": 404,
    "ERR_PROPERTY_FROZEN": 409,
    "ERR_PROPERTY_RESTRICTED": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_EMPTY_ATTRIBUTE_SET": 409,
    "ERR_ATTRIBUTES_UNRESOLVED": 409,
    "ERR_ATTRIBUTE_DUPLICATE_FIELD": 409,
    "ERR_ATTRIBUTE_MARKET_MISMATCH": 422,
    "ERR_ATTRIBUTE_SOURCE_MISMATCH": 422,
    "ERR_SUBDIVISION_PARENT_INVALID": 422,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_THIRD_PARTY_UNLICENSED": 409,
    "ERR_UNAUTHORIZED_REDISTRIBUTION": 409,
    "ERR_SOURCE_FUTURE_DATED": 409,
    "ERR_LEASE_WINDOW_INVALID": 422,
    "ERR_COMP_TEMPORAL_IMPOSSIBLE": 409,
    "ERR_SALE_PROPERTY_NOT_RESEARCHED": 422,
    "ERR_SALE_PRICE_NOT_POSITIVE": 409,
    "ERR_SUBORDINATION_DEADLINE_PASSED": 409,
    "ERR_SUBSCRIPTION_INACTIVE": 409,
    "ERR_NO_SEATS": 409,
    "ERR_SEAT_CAPACITY_EXCEEDED": 409,
    "ERR_SEAT_MARKET_NOT_LICENSED": 409,
    "ERR_SEAT_ALREADY_ASSIGNED": 409,
    "ERR_USER_INACTIVE": 409,
    "ERR_USER_OUT_OF_SCOPE": 409,
    "ERR_MARKET_ALREADY_LICENSED": 409,
    "ERR_AUTO_RENEW_DISABLED": 409,
    "ERR_RENEWAL_LAPSED": 409,
    "ERR_RENEWAL_TERMINATED": 409,
    "ERR_TERMINATION_WINDOW_CLOSED": 409,
    "ERR_FEE_NOT_POSITIVE": 409,
    "ERR_SUBSCRIPTION_REACH_EXCEEDED": 409,
    "ERR_LISTING_OVERLAP": 409,
    "ERR_LITIGATION_NOT_ESCALATABLE": 409,
    "ERR_LITIGATION_NOT_PERMITTED": 409,
    "ERR_PENALTY_BELOW_LITIGATION_FLOOR": 409,
    "ERR_SETTLEMENT_INSUFFICIENT": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_EMPTY_INDEX_SET": 409,
}

ERROR_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required and must be non-empty.",
    "ERR_UNAUTHORIZED": "The acting role is not permitted for this operation.",
    "ERR_INVALID_REQUEST": "A required input field is absent or fails its declared type or constraint.",
    "ERR_ORGANIZATION_NOT_FOUND": "No organization exists with the given id.",
    "ERR_USER_NOT_FOUND": "No user exists with the given id.",
    "ERR_PROPERTY_NOT_FOUND": "No property exists with the given id.",
    "ERR_ATTRIBUTE_NOT_FOUND": "No attribute exists with the given id for that property.",
    "ERR_SOURCE_DOCUMENT_NOT_FOUND": "No source document exists with the given id for that property.",
    "ERR_TRANSACTION_NOT_FOUND": "No sale transaction exists with the given id.",
    "ERR_LISTING_NOT_FOUND": "No listing exists with the given id.",
    "ERR_CONTRACT_NOT_FOUND": "No licensing contract exists with the given id.",
    "ERR_SEAT_NOT_FOUND": "No seat exists with the given id for that contract.",
    "ERR_ENFORCEMENT_CASE_NOT_FOUND": "No enforcement case exists with the given id.",
    "ERR_PROPERTY_FROZEN": "The property is frozen and cannot accept this operation.",
    "ERR_PROPERTY_RESTRICTED": "The property is restricted and cannot accept this operation.",
    "ERR_INVALID_STATE": "The target resource is not in the state this transition requires.",
    "ERR_EMPTY_ATTRIBUTE_SET": "The property carries no attributes and cannot be finalized.",
    "ERR_ATTRIBUTES_UNRESOLVED": "The property still carries pending attributes.",
    "ERR_ATTRIBUTE_DUPLICATE_FIELD": "An attribute with that field_name already exists on the property.",
    "ERR_ATTRIBUTE_MARKET_MISMATCH": "The attribute market does not equal the property market.",
    "ERR_ATTRIBUTE_SOURCE_MISMATCH": "The named source document belongs to a different property.",
    "ERR_SUBDIVISION_PARENT_INVALID": "Subdivision requires a property still in DRAFT.",
    "ERR_SEGREGATION_OF_DUTIES": "The verifying analyst may not be the attribute's author.",
    "ERR_THIRD_PARTY_UNLICENSED": "A third-party derived claim requires third_party_approved.",
    "ERR_UNAUTHORIZED_REDISTRIBUTION": "The operation breaches the redistribution controls.",
    "ERR_SOURCE_FUTURE_DATED": "The source obtained_at instant is later than the logical clock.",
    "ERR_LEASE_WINDOW_INVALID": "lease_end must be strictly after lease_start.",
    "ERR_COMP_TEMPORAL_IMPOSSIBLE": "The comparable's lease ended before it was recorded.",
    "ERR_SALE_PROPERTY_NOT_RESEARCHED": "A sale may only be recorded on a RESEARCHING or VERIFIED property.",
    "ERR_SALE_PRICE_NOT_POSITIVE": "gross_sale_price_cents must be strictly positive.",
    "ERR_SUBORDINATION_DEADLINE_PASSED": "The subordination deadline has passed.",
    "ERR_SUBSCRIPTION_INACTIVE": "The contract does not hold ACTIVE or GRACE status.",
    "ERR_NO_SEATS": "The contract carries no seats and cannot be activated.",
    "ERR_SEAT_CAPACITY_EXCEEDED": "The contract's seat capacity would be exceeded.",
    "ERR_SEAT_MARKET_NOT_LICENSED": "The seat market is absent from the contract's licensed markets.",
    "ERR_SEAT_ALREADY_ASSIGNED": "The seat already carries an occupant.",
    "ERR_USER_INACTIVE": "The nominated occupant is inactive.",
    "ERR_USER_OUT_OF_SCOPE": "The nominated occupant belongs to a different organization.",
    "ERR_MARKET_ALREADY_LICENSED": "The market is already licensed on this contract.",
    "ERR_AUTO_RENEW_DISABLED": "The contract does not auto-renew.",
    "ERR_RENEWAL_LAPSED": "The renewal window has lapsed.",
    "ERR_RENEWAL_TERMINATED": "A termination decision was already recorded.",
    "ERR_TERMINATION_WINDOW_CLOSED": "The termination window is closed.",
    "ERR_FEE_NOT_POSITIVE": "annual_fee_cents must be strictly positive.",
    "ERR_SUBSCRIPTION_REACH_EXCEEDED": "The subscription exceed the roll-up market reach.",
    "ERR_LISTING_OVERLAP": "Another published listing overlaps that availability interval.",
    "ERR_LITIGATION_NOT_ESCALATABLE": "A LITIGATION case can not be escalated.",
    "ERR_LITIGATION_NOT_PERMITTED": "The contract's audit intensity does not permit litigation.",
    "ERR_PENALTY_BELOW_LITIGATION_FLOOR": "The penalty is below the litigation threshold.",
    "ERR_SETTLEMENT_INSUFFICIENT": "The settlement offer is below the assessed penalty.",
    "ERR_STALE_VERSION": "The supplied expected version does not match the current version.",
    "ERR_EMPTY_INDEX_SET": "The refined comparable set is empty.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http_status = ERROR_CATALOG.get(error_id, 400)
        self.message = message or ERROR_MESSAGES.get(error_id, "Request failed.")
        super().__init__(self.message)


# ---------------------------------------------------------------------------
# Domain constants
# ---------------------------------------------------------------------------
SOURCE_FRESHNESS_DAYS = 180
WEIGHT_VERIFIED_SOURCED = Decimal("1.0")
WEIGHT_VERIFIED_UNSOURCED = Decimal("0.6")
WEIGHT_UNVERIFIED = Decimal("0.0")
WEIGHT_STALE_PENALTY = Decimal("0.1")

INCLUDED_ACTIVE_DAYS = 2
TIER_1_DAILY_RATE_CENTS = 1250
TIER_2_DAILY_RATE_CENTS = 900
TIER_3_DAILY_RATE_CENTS = 600
LICENSED_MARKET_USAGE_LIMIT_BPS = 250
SHARING_IP_THRESHOLD = {"TIER_1": 3, "TIER_2": 5, "TIER_3": 8}

LITIGATION_PENALTY_THRESHOLD_CENTS = 75000000
SUBSTITUTE_INCOME_CENTS = 250000000
MARKET_ADD_BASE_PCT = Decimal("0.08")
BASE_GROWTH_RATE = Decimal("0.015")
MIN_GROWTH_FACTOR = Decimal("0.90")
MAX_GROWTH_FACTOR = Decimal("1.35")
DEFAULT_HORIZON_QUARTERS = 4
OFFICE_INDUSTRIAL_RENT_CAP = Decimal("500.00")
# PRD 3.3: "the server derives subordination_deadline as exactly ten days after
# the close_date".
SUBORDINATION_DEADLINE_DAYS = 10

UTC = timezone.utc
DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
class Clock:
    def __init__(self):
        self.value = DEFAULT_CLOCK

    def now(self):
        return self.value

    def set(self, iso_string):
        self.value = parse_dt(iso_string)


clock = Clock()


# ---------------------------------------------------------------------------
# Identifiers and timestamps
# ---------------------------------------------------------------------------
_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def new_id():
    return str(uuid.uuid4())


def request_id():
    raw = uuid.uuid4().hex.upper()
    return "req_" + raw[:16]


_last_wall = None


def wall_now():
    """Monotonically increasing millisecond-resolution wall clock instant."""
    global _last_wall
    d = datetime.now(UTC).replace(microsecond=(datetime.now(UTC).microsecond // 1000) * 1000)
    if _last_wall is not None and d <= _last_wall:
        d = _last_wall + timedelta(milliseconds=1)
    _last_wall = d
    return d


def fmt_dt(dt):
    """ISO 8601 UTC instant. Derived instants fall on whole seconds and are
    emitted without a fractional part; only sub-second instants (the
    server-generated wall-clock stamps) carry the three fractional digits."""
    dt = dt.astimezone(UTC)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "Expected an ISO 8601 datetime string.")
    text = value.strip()
    if not text:
        raise ApiError("ERR_INVALID_REQUEST", "Expected an ISO 8601 datetime string.")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "Malformed ISO 8601 datetime: %r" % value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


# ---------------------------------------------------------------------------
# In-memory store — always empty at boot
# ---------------------------------------------------------------------------
organizations = {}
users = {}
properties = {}
source_documents = {}
attributes = {}
lease_comparables = {}
sale_transactions = {}
contracts = {}
seats = {}
usage_events = {}
enforcement_cases = {}
analytics_runs = {}
listings = {}

cycle_index = {"value": 0}


def reset_store():
    for table in (
        organizations, users, properties, source_documents, attributes,
        lease_comparables, sale_transactions, contracts, seats, usage_events,
        enforcement_cases, analytics_runs, listings,
    ):
        table.clear()
    cycle_index["value"] = 0
    clock.value = DEFAULT_CLOCK


# ---------------------------------------------------------------------------
# Decimal helpers — round half up, never banker's rounding
# ---------------------------------------------------------------------------
def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places):
    quant = Decimal(1).scaleb(-places)
    return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def to_float(value, places=2):
    if value is None:
        return None
    return float(round_half_up(dec(value), places))


def as_int(value):
    return int(round_half_up(dec(value), 0))


# ---------------------------------------------------------------------------
# Common resource helpers
# ---------------------------------------------------------------------------
def stamp_created(record):
    record["id"] = new_id()
    record["created_at"] = now_iso()
    record["updated_at"] = record["created_at"]
    record["version"] = 1
    return record


def touch(record):
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
    return record


def now_iso():
    return fmt_dt(wall_now())


# ---------------------------------------------------------------------------
# Request parsing helpers
# ---------------------------------------------------------------------------
_TRUE = ("true", "1", "yes")
_FALSE = ("false", "0", "no")


def body_of(request):
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def require_string(payload, field, allow_empty=False):
    if field not in payload or payload[field] is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field '%s'." % field)
    value = payload[field]
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a string." % field)
    if not allow_empty and value == "":
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be non-empty." % field)
    return value


def optional_string(payload, field, default=None):
    if field not in payload or payload[field] is None:
        return default
    value = payload[field]
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a string." % field)
    return value


def require_enum(payload, field, allowed):
    value = require_string(payload, field)
    if value not in allowed:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field '%s' must be one of %s." % (field, ", ".join(sorted(allowed))),
        )
    return value


def optional_enum(payload, field, allowed, default):
    if field not in payload or payload[field] is None:
        return default
    value = payload[field]
    if not isinstance(value, str) or value not in allowed:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field '%s' must be one of %s." % (field, ", ".join(sorted(allowed))),
        )
    return value


def require_int(payload, field):
    if field not in payload or payload[field] is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field '%s'." % field)
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % field)
    return value


def optional_int(payload, field, default):
    if field not in payload or payload[field] is None:
        return default
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % field)
    return value


def optional_number(payload, field, default=None):
    if field not in payload or payload[field] is None:
        return default
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a number." % field)
    return value


def require_bool(payload, field):
    if field not in payload or payload[field] is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field '%s'." % field)
    value = payload[field]
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in _TRUE + _FALSE:
        return value.lower() in _TRUE
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % field)


def optional_bool(payload, field, default):
    if field not in payload or payload[field] is None:
        return default
    value = payload[field]
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in _TRUE + _FALSE:
        return value.lower() in _TRUE
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % field)


def require_datetime(payload, field):
    if field not in payload or payload[field] is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field '%s'." % field)
    return parse_dt(payload[field])


def optional_datetime(payload, field, default=None):
    if field not in payload or payload[field] is None:
        return default
    return parse_dt(payload[field])


def require_string_list(payload, field):
    if field not in payload or payload[field] is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field '%s'." % field)
    value = payload[field]
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be an array of strings." % field)
    return list(value)


def optional_string_list(payload, field, default=None):
    if field not in payload or payload[field] is None:
        return list(default) if default is not None else []
    value = payload[field]
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be an array of strings." % field)
    return list(value)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def pagination_args(request):
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = 10 if raw_limit is None else int(raw_limit)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
    try:
        offset = 0 if raw_offset is None else int(raw_offset)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", "offset must be zero or greater.")
    return limit, offset


def sort_by_created(records):
    return sorted(records, key=lambda r: (r.get("created_at", ""), r.get("id", "")))


def paginate(records, limit, offset):
    ordered = sort_by_created(records)
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return window, total, offset + limit < total


def query_filter(request, field, record_field=None):
    value = request.args.get(field)
    if value is None or value == "":
        return None
    return value
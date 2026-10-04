"""Foundation: logical clock, in-memory store, errors, envelope, auth, schema helpers."""
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps

from flask import g, jsonify, request

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Error catalogue (PRD §5) -- error_id -> HTTP status
# ---------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_VALIDATION": 400,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_TENDER_NOT_OPEN": 409,
    "ERR_PANEL_INCOMPLETE": 409,
    "ERR_BLIND_VIOLATION": 422,
    "ERR_DUAL_SOURCE_REQUIRED": 409,
    "ERR_SKU_CAP_EXCEEDED": 409,
    "ERR_SKU_CAP_BELOW_CURRENT": 409,
    "ERR_DUPLICATE_SKU": 409,
    "ERR_BARCODE_COUNT_INVALID": 422,
    "ERR_SHELF_READY_REQUIRED": 422,
    "ERR_BID_DUPLICATE": 409,
    "ERR_BID_CEILING_EXCEEDED": 422,
    "ERR_SUPPLIER_SUSPENDED": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_FINDS_NO_REPLENISHMENT": 409,
    "ERR_ALLOCATION_INCOMPLETE": 409,
    "ERR_PRODUCT_NOT_ACTIVE": 409,
    "ERR_SALE_WINDOW_CONFLICT": 409,
    "ERR_CLEARANCE_GAP_VIOLATION": 409,
    "ERR_ALLOCATION_EXHAUSTED": 409,
    "ERR_SALE_WINDOW_INACTIVE": 409,
    "ERR_COIN_BALANCE_NEGATIVE": 422,
    "ERR_WINDOW_OVERLAP": 409,
    "ERR_WINDOW_LIMIT_EXCEEDED": 409,
    "ERR_LABOR_BUDGET_EXCEEDED": 422,
    "ERR_CLAIM_WINDOW_EXPIRED": 422,
    "ERR_SHIFT_NOT_OPEN": 409,
    "ERR_CASHIER_ROLE_REQUIRED": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    words = error_id[4:].replace("_", " ").lower() if error_id.startswith("ERR_") else error_id
    return words.capitalize() + "."


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
ROLES = (
    "OperationsAdmin",
    "CategoryManager",
    "ProcurementLead",
    "QualityAssuranceLead",
    "SupplierRep",
    "StoreManager",
    "Cashier",
    "CustomerServiceAgent",
)

HDR_USER = "X-User-ID"
HDR_ROLE = "X-User-Role"


# ---------------------------------------------------------------------------
# Decimal / time helpers
# ---------------------------------------------------------------------------
def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def rhu(value, places):
    """round_half_up to `places` decimal places."""
    quant = Decimal(1).scaleb(-places) if places > 0 else Decimal(1)
    return D(value).quantize(quant, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def fmt_dt(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2})(\.\d+)?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_dt(text):
    """Parse an ISO-8601 datetime to an aware UTC datetime; None when unparseable."""
    if not isinstance(text, str):
        return None
    text = text.strip()
    # A bare ISO date is accepted as midnight UTC of that day.
    md = _DATE_RE.match(text)
    if md:
        try:
            return datetime(int(md.group(1)), int(md.group(2)), int(md.group(3)),
                            tzinfo=UTC)
        except ValueError:
            return None
    m = _DT_RE.match(text)
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7)
    micro = 0
    if frac:
        micro = int(round(float(frac) * 1_000_000))
    tzpart = m.group(8)
    try:
        base = datetime(year, month, day, hour, minute, second, micro, tzinfo=UTC)
    except ValueError:
        return None
    if tzpart and tzpart not in ("Z", "z"):
        sign = 1 if tzpart[0] == "+" else -1
        body_ = tzpart[1:].replace(":", "")
        offset = timedelta(hours=int(body_[:2]), minutes=int(body_[2:4]))
        base = base - sign * offset
    return base


def parse_date(text):
    """Parse a bare ISO date YYYY-MM-DD to a datetime.date; None when unparseable."""
    if not isinstance(text, str):
        return None
    m = _DATE_RE.match(text.strip())
    if not m:
        return None
    try:
        from datetime import date as _date
        return _date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def iso_week_monday(dt):
    """Monday 00:00 UTC of the ISO week containing the given aware datetime."""
    day = dt.date()
    monday = day - timedelta(days=day.weekday())
    return datetime(monday.year, monday.month, monday.day, tzinfo=UTC)


# ---------------------------------------------------------------------------
# In-memory store -- starts EMPTY on every boot; nothing is ever seeded.
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)


class Store(object):
    COLLECTIONS = (
        "categories",
        "suppliers",
        "products",
        "tenders",
        "bids",
        "panels",
        "stores",
        "employees",
        "finds_buys",
        "allocations",
        "cart_coin_events",
        "register_shifts",
        "labor_windows",
        "claims",
    )

    def __init__(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq


db = Store()


def now():
    return db.clock


def new_row(_kind_name, audited=True, **fields):
    row = {
        "_kind": _kind_name,
        "_seq": db.next_seq(),
        "id": str(uuid.uuid4()),
        "created_at": db.clock,
    }
    if audited:
        row["updated_at"] = db.clock
        row["version"] = 1
    row.update(fields)
    return row


def touch(row):
    """Record a mutation: bump version and refresh updated_at."""
    if "version" in row:
        row["version"] += 1
        row["updated_at"] = db.clock
    return row


def sort_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def jsonable(value):
    if isinstance(value, datetime):
        return fmt_dt(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def dump(row, extra=None):
    if row is None:
        return None
    out = {k: jsonable(v) for k, v in row.items() if not k.startswith("_")}
    if extra:
        out.update({k: jsonable(v) for k, v in extra.items()})
    return out


# ---------------------------------------------------------------------------
# Response envelope (PRD §2.2)
# ---------------------------------------------------------------------------
_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"


def _meta():
    token = "".join(secrets.choice(_ALPHABET) for _ in range(16))
    return {
        "api_request_id": "req_" + token,
        "api_request_timestamp": fmt_dt(datetime.now(UTC)),
    }


def respond_object(data, status=200):
    return (
        jsonify({"meta": _meta(), "response_type": "object", "data": jsonable(data)}),
        status,
    )


def respond_list(items, total_count, limit, offset, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return (
        jsonify({"meta": meta, "response_type": "array", "data": jsonable(items)}),
        status,
    )


def respond_error(error_id, message, status):
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": error_id, "message": message},
            }
        ),
        status,
    )


# ---------------------------------------------------------------------------
# Auth (tiers 1 and 2 of the validation precedence, PRD §2.8)
# ---------------------------------------------------------------------------
def endpoint(*roles):
    allowed = set(roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get(HDR_USER)
            role = request.headers.get(HDR_ROLE)
            if not (user_id or "").strip() or not (role or "").strip():
                raise ApiError("ERR_UNAUTHENTICATED")
            if role not in ROLES:
                raise ApiError("ERR_UNAUTHENTICATED")
            if role not in allowed:
                raise ApiError("ERR_FORBIDDEN")
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def forbid_unless(condition):
    if not condition:
        raise ApiError("ERR_FORBIDDEN")


# ---------------------------------------------------------------------------
# Tier 3 -- request-shape validation helpers
# ---------------------------------------------------------------------------
_MISSING = object()


def bad_request(detail):
    raise ApiError("ERR_VALIDATION", detail)


def body():
    """Parse the JSON body. An absent body behaves as an empty object."""
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        bad_request("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        bad_request("Request body must be a JSON object.")
    return parsed


def _fetch(src, key, required):
    if key not in src or src[key] is None:
        if required:
            bad_request("Field '%s' is required." % key)
        return _MISSING
    return src[key]


def f_str(src, key, required=True, allow_empty=False):
    value = _fetch(src, key, required)
    if value is _MISSING:
        return None
    if not isinstance(value, str):
        bad_request("Field '%s' must be a string." % key)
    if not allow_empty and value.strip() == "":
        bad_request("Field '%s' must not be empty." % key)
    return value


def f_enum(src, key, domain, required=True, default=None):
    value = _fetch(src, key, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str) or value not in domain:
        bad_request("Field '%s' must be one of %s." % (key, ", ".join(domain)))
    return value


def f_bool(src, key, required=True, default=None):
    value = _fetch(src, key, required)
    if value is _MISSING:
        return default
    if not isinstance(value, bool):
        bad_request("Field '%s' must be a boolean." % key)
    return value


def f_int(src, key, required=True, default=None, minimum=None, maximum=None):
    value = _fetch(src, key, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        bad_request("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        bad_request("Field '%s' must be at least %s." % (key, minimum))
    if maximum is not None and value > maximum:
        bad_request("Field '%s' must be at most %s." % (key, maximum))
    return value


def f_num(src, key, required=True, default=None, minimum=None, maximum=None):
    value = _fetch(src, key, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        bad_request("Field '%s' must be a number." % key)
    dec = D(value)
    if minimum is not None and dec < D(minimum):
        bad_request("Field '%s' must be at least %s." % (key, minimum))
    if maximum is not None and dec > D(maximum):
        bad_request("Field '%s' must be at most %s." % (key, maximum))
    return dec


def f_dt(src, key, required=True, default=None):
    value = _fetch(src, key, required)
    if value is _MISSING:
        return default
    parsed = parse_dt(value) if isinstance(value, str) else None
    if parsed is None:
        bad_request("Field '%s' must be an ISO-8601 UTC timestamp." % key)
    return parsed


def f_date(src, key, required=True, default=None):
    value = _fetch(src, key, required)
    if value is _MISSING:
        return default
    parsed = parse_date(value) if isinstance(value, str) else None
    if parsed is None:
        bad_request("Field '%s' must be an ISO date (YYYY-MM-DD)." % key)
    return parsed


# ---------------------------------------------------------------------------
# Query-string helpers and pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def q_str(key, default=None):
    if key not in request.args:
        return default
    value = request.args.get(key)
    if value is None or value == "":
        return default
    return value


def q_enum(key, domain, default=None):
    value = q_str(key)
    if value is None:
        return default
    if value not in domain:
        bad_request("Query parameter '%s' must be one of %s." % (key, ", ".join(domain)))
    return value


def q_int(key, default=None, minimum=None, maximum=None):
    value = q_str(key)
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        bad_request("Query parameter '%s' must be an integer." % key)
    if minimum is not None and parsed < minimum:
        bad_request("Query parameter '%s' must be at least %s." % (key, minimum))
    if maximum is not None and parsed > maximum:
        bad_request("Query parameter '%s' must be at most %s." % (key, maximum))
    return parsed


PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def pagination():
    limit = q_int("limit", PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MIN, PAGE_LIMIT_MAX)
    offset = q_int("offset", PAGE_OFFSET_DEFAULT, 0, None)
    return limit, offset


def paginate(rows, dumper=None):
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    dumper = dumper or dump
    return respond_list([dumper(r) for r in page], total, limit, offset)

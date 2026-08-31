"""Core infrastructure: logical clock, in-memory store, envelope, errors."""
import json
import math
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, getcontext

from flask import jsonify

getcontext().prec = 60

UTC = timezone.utc
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

ROLES = ("ShopPlanner", "Machinist", "Inspector", "QualityManager")


# --------------------------------------------------------------------------
# errors
# --------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or _DEFAULT_MESSAGES.get(error_id) or _humanize(error_id)


def _humanize(error_id):
    words = error_id[4:].replace("_", " ").lower() if error_id.startswith("ERR_") else error_id
    return (words[:1].upper() + words[1:] + ".") if words else error_id


_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Missing or invalid authentication headers.",
    "ERR_FORBIDDEN_ROLE": "The acting role may not perform this operation.",
    "ERR_INVALID_REQUEST": "The request body or query string is malformed.",
    "ERR_DUPLICATE_KEY": "A declared unique key already exists.",
    "ERR_INVALID_STATE": "The requested transition is not declared from the current state.",
}

HTTP_BY_ERROR = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_DUPLICATE_KEY": 409,
    "ERR_OPERATOR_NOT_FOUND": 404,
    "ERR_MACHINE_NOT_FOUND": 404,
    "ERR_PART_NOT_FOUND": 404,
    "ERR_CHARACTERISTIC_NOT_FOUND": 404,
    "ERR_GAUGE_NOT_FOUND": 404,
    "ERR_BAR_LOT_NOT_FOUND": 404,
    "ERR_QUOTE_NOT_FOUND": 404,
    "ERR_BLANKET_PO_NOT_FOUND": 404,
    "ERR_RELEASE_NOT_FOUND": 404,
    "ERR_WORK_ORDER_NOT_FOUND": 404,
    "ERR_TOOL_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_SPC_SAMPLE_NOT_FOUND": 404,
    "ERR_ROUTING_STEP_NOT_FOUND": 404,
    "ERR_STALE_PO_VERSION": 412,
    "ERR_STALE_MACHINE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_PO_NOT_ACTIVE": 409,
    "ERR_PO_EXPIRED": 409,
    "ERR_MACHINE_NOT_AVAILABLE": 409,
    "ERR_BAR_LOT_NOT_CERTIFIED": 409,
    "ERR_TOOL_LIFE_EXPIRED": 409,
    "ERR_GAUGE_NOT_IN_SERVICE": 409,
    "ERR_OPERATOR_NOT_CERTIFIED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_BAR_DIAMETER_MISMATCH": 422,
    "ERR_ALLOY_MISMATCH": 422,
    "ERR_LIGHTS_OUT_NOT_PERMITTED": 422,
    "ERR_MACHINE_WINDOW_CONFLICT": 409,
    "ERR_BAR_LOT_FEEDER_CONFLICT": 409,
    "ERR_SUBGROUP_SIZE_MISMATCH": 422,
    "ERR_CHARACTERISTIC_PART_MISMATCH": 422,
    "ERR_GAUGE_TYPE_MISMATCH": 422,
    "ERR_PREDECESSOR_STEP_INVALID": 422,
    "ERR_PO_QTY_EXCEEDED": 409,
    "ERR_RELEASE_QTY_EXCEEDED": 409,
    "ERR_BAR_STOCK_INSUFFICIENT": 409,
    "ERR_QTY_EXCEEDS_ORDERED": 422,
    "ERR_SPC_SAMPLING_INCOMPLETE": 409,
    "ERR_CAPABILITY_BELOW_MINIMUM": 409,
}


def fail(error_id, message=None):
    raise ApiError(error_id, HTTP_BY_ERROR.get(error_id, 400), message)


# --------------------------------------------------------------------------
# numbers / time
# --------------------------------------------------------------------------
def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def rhu(value, places=0):
    """round half up to `places` decimal places, returning a Decimal."""
    q = Decimal(1).scaleb(-places)
    return dec(value).quantize(q, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def ceil_div(numerator, denominator):
    return int(-((-dec(numerator)) / dec(denominator)).to_integral_value(rounding="ROUND_FLOOR"))


def dec_ceil(value):
    return int(dec(value).to_integral_value(rounding="ROUND_CEILING"))


def parse_dt(text):
    """Parse an ISO-8601 instant. Returns an aware UTC datetime or None."""
    if not isinstance(text, str) or not text.strip():
        return None
    raw = text.strip()
    candidate = raw
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def fmt_ts(moment):
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (moment.microsecond // 1000)


def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


# --------------------------------------------------------------------------
# in-memory store (starts empty on every boot; nothing is ever seeded)
# --------------------------------------------------------------------------
COLLECTIONS = (
    "operators",
    "machines",
    "parts",
    "characteristics",
    "gauges",
    "bar_stock_lots",
    "quotes",
    "blanket_pos",
    "kanban_releases",
    "work_orders",
    "tool_assignments",
    "spc_samples",
    "routing_steps",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0
        self.clock = CLOCK_EPOCH

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def now():
    """The logical clock — every temporal comparison in the spec reads from it."""
    return db.clock


def now_iso():
    return fmt_ts(db.clock)


def stamp_new(row):
    row["id"] = new_id()
    row["created_at"] = now_iso()
    row["updated_at"] = now_iso()
    row["version"] = 1
    row["_seq"] = db.next_seq()
    return row


def touch(row):
    row["updated_at"] = now_iso()
    if "version" in row:
        row["version"] = row["version"] + 1
    return row


def public(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def sorted_rows(rows):
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))


# --------------------------------------------------------------------------
# response envelope
# --------------------------------------------------------------------------
class ApiEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            if o == o.to_integral_value():
                return int(o)
            return float(o)
        return json.JSONEncoder.default(self, o)


def _clean(value):
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_ts(datetime.now(UTC)),
    }


def respond_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": _clean(data)}
    return jsonify(body), status


def respond_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": _clean(items)}
    return jsonify(body), 200


def respond_error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status

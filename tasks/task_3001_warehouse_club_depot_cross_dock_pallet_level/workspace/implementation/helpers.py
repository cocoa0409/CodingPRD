"""Shared helpers: envelope, timestamps, ids, rounding, errors, logical clock parsing."""
import re
import uuid
from decimal import Decimal, ROUND_HALF_UP

from db import get_clock

HHMM_RE = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def bad_request(msg):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def validation(msg):
    return ApiError("ERR_VALIDATION", 400, msg)


def not_found(msg):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def invalid_state(msg):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def safety_gate(msg):
    return ApiError("ERR_SAFETY_GATE", 422, msg)


def dept_disabled(msg):
    return ApiError("ERR_DEPARTMENT_DISABLED", 422, msg)


def club_frozen(msg):
    return ApiError("ERR_CLUB_FROZEN", 422, msg)


def appt_conflict(msg):
    return ApiError("ERR_APPOINTMENT_CONFLICT", 409, msg)


def cutoff_passed(msg):
    return ApiError("ERR_CUTOFF_PASSED", 422, msg)


def constraint_violation(msg):
    return ApiError("ERR_CONSTRAINT_VIOLATION", 422, msg)


def same_day_only(msg):
    return ApiError("ERR_SAME_DAY_ONLY", 422, msg)


def member_cap(msg):
    return ApiError("ERR_MEMBER_CAP_EXCEEDED", 422, msg)


def club_capacity(msg):
    return ApiError("ERR_CLUB_CAPACITY_EXCEEDED", 422, msg)


def markdown_rule(msg):
    return ApiError("ERR_MARKDOWN_RULE_VIOLATION", 422, msg)


def inactive_ref(msg):
    return ApiError("ERR_INACTIVE_REFERENCE", 422, msg)


def referential_guard(msg):
    return ApiError("ERR_REFERENTIAL_GUARD", 409, msg)


def stale_run(msg):
    return ApiError("ERR_STALE_RUN_VERSION", 412, msg)


def stale_item(msg):
    return ApiError("ERR_STALE_ITEM_VERSION", 412, msg)


def new_id():
    return str(uuid.uuid4())


def request_id():
    return "req_" + uuid.uuid4().hex[:24]


def now_ts():
    """Current logical timestamp, ISO 8601 UTC with three fractional digits."""
    dt = get_clock()
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def wall_ts():
    """Wall-clock UTC timestamp (for meta.api_request_timestamp), three fractional digits."""
    from datetime import datetime, timezone
    dt = datetime.now(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def current_date():
    return get_clock().date()


def current_date_str():
    return get_clock().strftime("%Y-%m-%d")


def current_time_str():
    return get_clock().strftime("%H:%M")


def round_half_up_int(value):
    """Round a Decimal/numeric to the nearest integer, half-up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def round_half_up_4(value):
    return float(Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def get_body():
    """Parse the request JSON body; ERR_INVALID_REQUEST if malformed."""
    from flask import request
    if request.data is None or len(request.data) == 0:
        return {}
    try:
        body = request.get_json(force=False, silent=False)
    except Exception:
        raise bad_request("Request body is not valid JSON")
    if body is None:
        raise bad_request("Request body is not valid JSON")
    if not isinstance(body, dict):
        raise bad_request("Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise bad_request("Missing required field: %s" % f)


def is_string(v):
    return isinstance(v, str)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def check_hhmm(v, field):
    if not is_string(v) or not HHMM_RE.match(v):
        raise validation("%s must be HH:MM 24h" % field)


def check_date_str(v, field):
    if not is_string(v) or not DATE_RE.match(v):
        raise validation("%s must be YYYY-MM-DD" % field)
    # sanity: real date
    from datetime import date
    try:
        date.fromisoformat(v)
    except ValueError:
        raise validation("%s must be a valid YYYY-MM-DD date" % field)


def hhmm_to_minutes(t):
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def parse_iso8601_utc(s):
    """Parse an ISO8601 UTC instant. Raises ERR_VALIDATION on bad format."""
    from datetime import datetime, timezone
    if not is_string(s):
        raise validation("to_iso8601 must be an ISO8601 string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        raise validation("to_iso8601 must be a valid ISO8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_entity(store_name, entity_id, label=None):
    from db import stores
    ent = stores[store_name].get(entity_id)
    if ent is None:
        raise not_found("%s not found: %s" % (label or store_name, entity_id))
    return ent


def touch(entity):
    """Refresh updated_at and bump version by exactly 1."""
    entity["updated_at"] = now_ts()
    entity["version"] += 1


def new_entity(extra=None):
    ts = now_ts()
    e = {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}
    if extra:
        e.update(extra)
    return e


def paginate(items):
    """Apply limit/offset pagination; returns (page, meta-fields dict)."""
    from flask import request
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise validation("limit must be an integer")
        if limit < 1 or limit > 100:
            raise validation("limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise validation("offset must be an integer")
        if offset < 0:
            raise validation("offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    return page, {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}


def sort_created(items):
    """Default sort: created_at ASC. Ties preserve insertion order (stable sort);
    no id tie-break is applied for business purposes."""
    return sorted(items, key=lambda e: e["created_at"])

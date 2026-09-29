"""Request plumbing: authentication, body validation, filtering, pagination."""

from decimal import Decimal, InvalidOperation

from flask import request

import consts
from errors import ApiError, bad_request, not_found
from util import dec, parse_date, parse_instant
import store


# ---------------------------------------------------------------------------
# authentication / coarse authorization
# ---------------------------------------------------------------------------
def _header(name):
    value = request.headers.get(name)
    if value is None:
        return None
    if value.strip() == "":
        return None
    return value


def actor(roles):
    role = _header("X-User-Role")
    user_id = _header("X-User-ID")
    if role is None or user_id is None:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role are required")
    if role not in consts.ROLES or role not in roles:
        raise ApiError("ERR_FORBIDDEN_ROLE", "role '%s' may not call this endpoint" % role)
    return role, user_id


READ_ROLES = list(consts.ROLES)


# ---------------------------------------------------------------------------
# body parsing
# ---------------------------------------------------------------------------
def body():
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        bad_request("request body is not valid JSON")
    if data is None:
        return {}
    if not isinstance(data, dict):
        bad_request("request body must be a JSON object")
    return data


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _check_string(name, value, spec):
    if not isinstance(value, str):
        bad_request("field '%s' must be a string" % name)
    text = value
    if spec.get("non_blank", True) and text.strip() == "":
        bad_request("field '%s' must not be blank" % name)
    minimum = spec.get("min_len", 1)
    maximum = spec.get("max_len")
    if len(text) < minimum:
        bad_request("field '%s' is too short" % name)
    if maximum is not None and len(text) > maximum:
        bad_request("field '%s' is too long" % name)
    if spec.get("upper_alnum") and not all(c.isdigit() or ("A" <= c <= "Z") for c in text):
        bad_request("field '%s' must be uppercase alphanumeric" % name)
    return text


def _check_integer(name, value, spec):
    if not _is_int(value):
        bad_request("field '%s' must be an integer" % name)
    if "min" in spec and value < spec["min"]:
        bad_request("field '%s' is below the allowed minimum" % name)
    if "max" in spec and value > spec["max"]:
        bad_request("field '%s' is above the allowed maximum" % name)
    return value


def _check_number(name, value, spec):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad_request("field '%s' must be a number" % name)
    try:
        number = dec(value)
    except (InvalidOperation, ValueError):
        bad_request("field '%s' must be a number" % name)
    if "min" in spec and number < dec(spec["min"]):
        bad_request("field '%s' is below the allowed minimum" % name)
    if "max" in spec and number > dec(spec["max"]):
        bad_request("field '%s' is above the allowed maximum" % name)
    return number


def _check_value(name, value, spec):
    kind = spec["kind"]
    if kind == "string":
        return _check_string(name, value, spec)
    if kind == "integer":
        return _check_integer(name, value, spec)
    if kind == "number":
        return _check_number(name, value, spec)
    if kind == "boolean":
        if not isinstance(value, bool):
            bad_request("field '%s' must be a boolean" % name)
        return value
    if kind == "enum":
        if not isinstance(value, str) or value not in spec["values"]:
            bad_request("field '%s' is not a declared enum member" % name)
        return value
    if kind == "datetime":
        if not isinstance(value, str):
            bad_request("field '%s' must be an ISO-8601 UTC instant" % name)
        parsed = parse_instant(value)
        if parsed is None:
            bad_request("field '%s' must be an ISO-8601 UTC instant" % name)
        return parsed
    if kind == "date":
        if not isinstance(value, str):
            bad_request("field '%s' must be a YYYY-MM-DD date" % name)
        parsed = parse_date(value)
        if parsed is None:
            bad_request("field '%s' must be a YYYY-MM-DD date" % name)
        return parsed
    if kind == "enum_array":
        if not isinstance(value, list) or not value:
            bad_request("field '%s' must be a non-empty array" % name)
        seen = []
        for item in value:
            if not isinstance(item, str) or item not in spec["values"]:
                bad_request("field '%s' contains an undeclared value" % name)
            if item in seen:
                bad_request("field '%s' contains duplicates" % name)
            seen.append(item)
        return seen
    if kind == "buckets":
        return _check_buckets(name, value)
    bad_request("field '%s' is invalid" % name)


def _check_buckets(name, value):
    if not isinstance(value, list) or not value:
        bad_request("field '%s' must be a non-empty array" % name)
    out = []
    for item in value:
        if not isinstance(item, dict):
            bad_request("field '%s' entries must be objects" % name)
        for key in ("minutes_before_start", "minutes_before_end", "share_pct"):
            if key not in item or item[key] is None:
                bad_request("bucket field '%s' is required" % key)
        start = _check_integer("minutes_before_start", item["minutes_before_start"], {"min": 0})
        end = _check_integer("minutes_before_end", item["minutes_before_end"], {"min": 0})
        share = _check_number("share_pct", item["share_pct"], {"min": 0, "max": 100})
        out.append(
            {
                "minutes_before_start": start,
                "minutes_before_end": end,
                "share_pct": share,
            }
        )
    return out


def parse_body(spec, data=None):
    """Validate a body against an ordered field specification (ladder rung 3)."""
    if data is None:
        data = body()
    out = {}
    for field in spec:
        name = field["name"]
        present = name in data and data[name] is not None
        if not present:
            if field.get("required"):
                bad_request("field '%s' is required" % name)
            continue
        out[name] = _check_value(name, data[name], field)
    return out


def resolve_fks(values, spec):
    """Resolve body foreign keys in declaration order (ladder rung 5)."""
    out = {}
    for field in spec:
        entity = field.get("fk")
        if not entity:
            continue
        name = field["name"]
        if name not in values:
            continue
        row = store.get(field["collection"], values[name])
        if row is None:
            not_found(entity, values[name])
        out[name] = row
    return out


# ---------------------------------------------------------------------------
# path parameters
# ---------------------------------------------------------------------------
PATH_COLLECTION = {
    "checkpoint": "checkpoints",
    "lane": "lanes",
    "equipment_unit": "equipment_units",
    "officer": "officers",
    "show_up_curve": "show_up_curves",
    "flight_schedule_entry": "flight_schedule_entries",
    "time_band": "time_bands",
    "staffing_plan": "staffing_plans",
    "lane_assignment": "lane_assignments",
    "wait_time_observation": "wait_time_observations",
    "escalation_ticket": "escalation_tickets",
    "screening_referral": "screening_referrals",
    "surge_detail": "surge_details",
}


def load(entity, ident):
    row = store.get(PATH_COLLECTION[entity], ident)
    if row is None:
        not_found(entity, ident)
    return row


# ---------------------------------------------------------------------------
# query parameters
# ---------------------------------------------------------------------------
def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            bad_request("limit must be an integer")
        if limit < 1 or limit > 100:
            bad_request("limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            bad_request("offset must be an integer")
        if offset < 0:
            bad_request("offset must be >= 0")
    return limit, offset


def query_enum(name, values, required=False):
    raw = request.args.get(name)
    if raw is None or raw.strip() == "":
        if required:
            bad_request("query parameter '%s' is required" % name)
        return None
    if raw not in values:
        bad_request("query parameter '%s' is not a declared enum member" % name)
    return raw


def query_instant(name):
    raw = request.args.get(name)
    if raw is None or raw.strip() == "":
        return None
    parsed = parse_instant(raw)
    if parsed is None:
        bad_request("query parameter '%s' must be an ISO-8601 UTC instant" % name)
    return parsed


def query_value(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def filter_rows(rows, filters):
    out = rows
    for field, expected in filters.items():
        if expected is None:
            continue
        out = [r for r in out if r.get(field) == expected]
    return out


def paginate(rows, limit, offset):
    return rows[offset : offset + limit], len(rows)

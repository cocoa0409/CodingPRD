"""Request shape validation (PRD 2.5 / 2.11 step 4)."""
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError, bad_request
from money import decimal_places, dec, q2, q4
import response as resp


def json_body():
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw, parse_float=Decimal)
    except Exception:
        raise bad_request("request body is not valid JSON")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise bad_request("request body must be a JSON object")
    return parsed


def present(body, name):
    return name in body and body[name] is not None


def _require(body, name):
    if name not in body or body[name] is None:
        raise bad_request("field '%s' is required" % name)


# ---------------------------------------------------------------- primitives

def _to_decimal(value, name):
    if isinstance(value, bool):
        raise bad_request("field '%s' must be a number" % name)
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            raise bad_request("field '%s' must be a number" % name)
        try:
            parsed = Decimal(text)
        except (InvalidOperation, ValueError):
            raise bad_request("field '%s' must be a number" % name)
        if not parsed.is_finite():
            raise bad_request("field '%s' must be a finite number" % name)
        return parsed
    raise bad_request("field '%s' must be a number" % name)


def get_str(body, name, required=True, min_len=1, max_len=None, default=None):
    if not present(body, name):
        if required:
            _require(body, name)
        return default
    value = body[name]
    if not isinstance(value, str):
        raise bad_request("field '%s' must be a string" % name)
    if min_len is not None and len(value) < min_len:
        raise bad_request("field '%s' must be at least %d characters" % (name, min_len))
    if max_len is not None and len(value) > max_len:
        raise bad_request("field '%s' must be at most %d characters" % (name, max_len))
    return value


def get_id(body, name, required=True):
    if not present(body, name):
        if required:
            _require(body, name)
        return None
    value = body[name]
    if not isinstance(value, str) or value.strip() == "":
        raise bad_request("field '%s' must be a non-empty string identifier" % name)
    return value


def get_bool(body, name, required=False, default=None):
    if not present(body, name):
        if required:
            _require(body, name)
        return default
    value = body[name]
    if not isinstance(value, bool):
        raise bad_request("field '%s' must be a boolean" % name)
    return value


def get_int(body, name, required=True, minimum=None, default=None):
    if not present(body, name):
        if required:
            _require(body, name)
        return default
    value = body[name]
    if isinstance(value, bool):
        raise bad_request("field '%s' must be an integer" % name)
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, (Decimal, float, str)):
        number = _to_decimal(value, name)
        if number != number.to_integral_value():
            raise bad_request("field '%s' must be an integer" % name)
        parsed = int(number)
    else:
        raise bad_request("field '%s' must be an integer" % name)
    if minimum is not None and parsed < minimum:
        raise bad_request("field '%s' must be >= %s" % (name, minimum))
    return parsed


def get_enum(body, name, allowed, required=True, default=None):
    if not present(body, name):
        if required:
            _require(body, name)
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        raise bad_request(
            "field '%s' must be one of %s" % (name, ", ".join(sorted(allowed)))
        )
    return value


def get_money(body, name, required=True, positive=False, signed=False,
              maximum=None, default=None):
    """Money: at most two decimal places, non-negative unless signed."""
    if not present(body, name):
        if required:
            _require(body, name)
        return default
    number = _to_decimal(body[name], name)
    if decimal_places(number) > 2:
        raise bad_request("field '%s' must carry at most 2 decimal places" % name)
    if not signed and number < 0:
        raise bad_request("field '%s' must not be negative" % name)
    if positive and number <= 0:
        raise bad_request("field '%s' must be greater than zero" % name)
    if maximum is not None and number > maximum:
        raise bad_request("field '%s' must not exceed %s" % (name, maximum))
    return q2(number)


def get_ratio(body, name, required=True, positive=False, signed=True,
              maximum=None, default=None):
    """Ratio: at most four decimal places."""
    if not present(body, name):
        if required:
            _require(body, name)
        return default
    number = _to_decimal(body[name], name)
    if decimal_places(number) > 4:
        raise bad_request("field '%s' must carry at most 4 decimal places" % name)
    if not signed and number < 0:
        raise bad_request("field '%s' must not be negative" % name)
    if positive and number <= 0:
        raise bad_request("field '%s' must be greater than zero" % name)
    if maximum is not None and number > maximum:
        raise bad_request("field '%s' must not exceed %s" % (name, maximum))
    return q4(number)


def get_unit_rate(body, name, required=True, default=None):
    """Unit rate: non-negative, at most four decimal places."""
    return get_ratio(body, name, required=required, signed=False, default=default)


def get_units(body, name, required=True, positive=False, default=None):
    """Unit counts carry at most two decimal places and are non-negative."""
    return get_money(body, name, required=required, positive=positive,
                     default=default)


def get_quantity(body, name, required=True, default=None):
    """A cost line quantity may be signed (offsetting lines are appended)."""
    if not present(body, name):
        if required:
            _require(body, name)
        return default
    return _to_decimal(body[name], name)


def get_datetime(body, name, required=True, default=None):
    if not present(body, name):
        if required:
            _require(body, name)
        return default
    value = body[name]
    if not isinstance(value, str):
        raise bad_request("field '%s' must be an ISO 8601 timestamp" % name)
    return parse_instant(value, name)


def parse_instant(text, name):
    raw = text.strip()
    if raw == "":
        raise bad_request("field '%s' must be an ISO 8601 timestamp" % name)
    candidate = raw
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        try:
            parsed = datetime.strptime(raw, "%Y-%m-%d")
        except ValueError:
            raise bad_request("field '%s' must be an ISO 8601 timestamp" % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def require_before(start, end, start_name, end_name):
    if start is not None and end is not None and not (start < end):
        raise bad_request("'%s' must be strictly before '%s'" % (start_name, end_name))


# ---------------------------------------------------------------- pagination

def pagination():
    args = request.args
    limit = resp.DEFAULT_LIMIT
    offset = resp.DEFAULT_OFFSET
    if "limit" in args and args.get("limit") != "":
        limit = _query_int("limit", args.get("limit"))
        if limit < resp.MIN_LIMIT or limit > resp.MAX_LIMIT:
            raise bad_request(
                "limit must be between %d and %d" % (resp.MIN_LIMIT, resp.MAX_LIMIT)
            )
    if "offset" in args and args.get("offset") != "":
        offset = _query_int("offset", args.get("offset"))
        if offset < 0:
            raise bad_request("offset must not be negative")
    return limit, offset


def _query_int(name, raw):
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        raise bad_request("query parameter '%s' must be an integer" % name)


def query_filter(name, allowed=None):
    args = request.args
    if name not in args:
        return None
    value = args.get(name)
    if value is None or value == "":
        return None
    if allowed is not None and value not in allowed:
        raise bad_request(
            "query parameter '%s' must be one of %s" % (name, ", ".join(sorted(allowed)))
        )
    return value


def paginate(rows, limit, offset):
    return rows[offset:offset + limit], len(rows)

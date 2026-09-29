"""Request-shape validation (PRD 2.6 rung 6 -> ERR_INVALID_REQUEST)."""

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError, bad_request

MISSING = object()

_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?"
    r"(Z|z|[+-]\d{2}:?\d{2})$"
)


def raw_body():
    """Return the parsed JSON object, or {} when no body was supplied."""
    data = request.get_data(cache=True, as_text=True)
    if data is None or data.strip() == "":
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        raise bad_request("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise bad_request("Request body must be a JSON object.")
    return parsed


def get(body, field):
    if field not in body:
        return MISSING
    return body[field]


def _present(body, field, required):
    value = get(body, field)
    if value is MISSING or value is None:
        if required:
            raise bad_request("Field '%s' is required." % field)
        return MISSING
    return value


def field_str(body, field, required=True, min_len=1, max_len=None, pattern=None):
    value = _present(body, field, required)
    if value is MISSING:
        return None
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be a string." % field)
    if min_len is not None and len(value) < min_len:
        raise bad_request("Field '%s' must not be empty." % field)
    if max_len is not None and len(value) > max_len:
        raise bad_request("Field '%s' is too long." % field)
    if pattern is not None and not re.match(pattern, value):
        raise bad_request("Field '%s' has an invalid format." % field)
    return value


def field_bool(body, field, required=True):
    value = _present(body, field, required)
    if value is MISSING:
        return None
    if not isinstance(value, bool):
        raise bad_request("Field '%s' must be a boolean." % field)
    return value


def field_int(body, field, required=True, minimum=None, maximum=None):
    value = _present(body, field, required)
    if value is MISSING:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request("Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        raise bad_request("Field '%s' must be >= %s." % (field, minimum))
    if maximum is not None and value > maximum:
        raise bad_request("Field '%s' must be <= %s." % (field, maximum))
    return value


def field_number(body, field, required=True, minimum=None, maximum=None, max_dp=None):
    value = _present(body, field, required)
    if value is MISSING:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad_request("Field '%s' must be a number." % field)
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        raise bad_request("Field '%s' must be a number." % field)
    if minimum is not None and dec < Decimal(str(minimum)):
        raise bad_request("Field '%s' must be >= %s." % (field, minimum))
    if maximum is not None and dec > Decimal(str(maximum)):
        raise bad_request("Field '%s' must be <= %s." % (field, maximum))
    if max_dp is not None and -dec.as_tuple().exponent > max_dp:
        raise bad_request("Field '%s' allows at most %d decimal places." % (field, max_dp))
    return dec


def field_enum(body, field, allowed, required=True):
    value = _present(body, field, required)
    if value is MISSING:
        return None
    if not isinstance(value, str) or value not in allowed:
        raise bad_request(
            "Field '%s' must be one of %s." % (field, ", ".join(sorted(allowed)))
        )
    return value


def field_array(body, field, required=True, min_len=None, max_len=None):
    value = _present(body, field, required)
    if value is MISSING:
        return None
    if not isinstance(value, list):
        raise bad_request("Field '%s' must be an array." % field)
    if min_len is not None and len(value) < min_len:
        raise bad_request("Field '%s' must hold at least %d elements." % (field, min_len))
    if max_len is not None and len(value) > max_len:
        raise bad_request("Field '%s' must hold at most %d elements." % (field, max_len))
    return value


def parse_instant(value, field):
    if not isinstance(value, str) or not _INSTANT_RE.match(value):
        raise bad_request("Field '%s' must be an ISO 8601 UTC instant." % field)
    text = value.strip()
    if text[-1] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise bad_request("Field '%s' must be an ISO 8601 UTC instant." % field)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def field_instant(body, field, required=True):
    value = _present(body, field, required)
    if value is MISSING:
        return None
    return parse_instant(value, field)


# ---- query parameters -----------------------------------------------------
def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        if not re.match(r"^-?\d+$", limit_raw.strip()):
            raise bad_request("Query parameter 'limit' must be an integer.")
        limit = int(limit_raw)
        if limit < 1 or limit > 100:
            raise bad_request("Query parameter 'limit' must be between 1 and 100.")
    if offset_raw is not None:
        if not re.match(r"^-?\d+$", offset_raw.strip()):
            raise bad_request("Query parameter 'offset' must be an integer.")
        offset = int(offset_raw)
        if offset < 0:
            raise bad_request("Query parameter 'offset' must not be negative.")
    return limit, offset


def query_str(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        raise bad_request("Query parameter '%s' has an invalid value." % name)
    return value


def query_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise bad_request("Query parameter '%s' must be a boolean." % name)


def paginate(rows, limit, offset):
    return rows[offset : offset + limit], len(rows)


def ensure(condition, error_id, message=None):
    if not condition:
        raise ApiError(error_id, message)

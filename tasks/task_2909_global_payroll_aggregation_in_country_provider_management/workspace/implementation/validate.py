"""Request-shape validation. Every failure here is ERR_INVALID_REQUEST (422)
and is evaluated after header auth/role but before any business rule."""
import re
from decimal import Decimal, InvalidOperation

from flask import request

from common import bad_request, parse_date, parse_instant, round2, round6

MISSING = object()

COUNTRY_CODE_RE = re.compile(r"^[A-Z]{2}$")
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


# ---------------------------------------------------------------------------
# Body access
# ---------------------------------------------------------------------------
def json_body(required=True):
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        if required:
            raise bad_request("A JSON object request body is required.")
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise bad_request("The request body is not valid JSON.")
    if not isinstance(data, dict):
        raise bad_request("The request body must be a JSON object.")
    return data


def _present(body, key):
    return key in body and body[key] is not None


def unknown_ok(body):
    return body


# ---------------------------------------------------------------------------
# Scalars
# ---------------------------------------------------------------------------
def req_str(body, key, min_len=1, max_len=None):
    if not _present(body, key):
        raise bad_request("Field '%s' is required." % key)
    return _as_str(body[key], key, min_len, max_len)


def opt_str(body, key, min_len=1, max_len=None, default=None):
    if not _present(body, key):
        return default
    return _as_str(body[key], key, min_len, max_len)


def _as_str(value, key, min_len, max_len):
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be a string." % key)
    if min_len is not None and len(value) < min_len:
        raise bad_request("Field '%s' is too short." % key)
    if max_len is not None and len(value) > max_len:
        raise bad_request("Field '%s' is too long." % key)
    return value


def req_int(body, key, minimum=None, maximum=None):
    if not _present(body, key):
        raise bad_request("Field '%s' is required." % key)
    return _as_int(body[key], key, minimum, maximum)


def opt_int(body, key, minimum=None, maximum=None, default=None):
    if not _present(body, key):
        return default
    return _as_int(body[key], key, minimum, maximum)


def _as_int(value, key, minimum, maximum):
    if isinstance(value, bool):
        raise bad_request("Field '%s' must be an integer." % key)
    if isinstance(value, int):
        out = value
    elif isinstance(value, float) and float(value).is_integer():
        out = int(value)
    else:
        raise bad_request("Field '%s' must be an integer." % key)
    if minimum is not None and out < minimum:
        raise bad_request("Field '%s' is below its minimum." % key)
    if maximum is not None and out > maximum:
        raise bad_request("Field '%s' is above its maximum." % key)
    return out


def req_bool(body, key):
    if not _present(body, key):
        raise bad_request("Field '%s' is required." % key)
    if not isinstance(body[key], bool):
        raise bad_request("Field '%s' must be a boolean." % key)
    return body[key]


def opt_bool(body, key, default=None):
    if not _present(body, key):
        return default
    if not isinstance(body[key], bool):
        raise bad_request("Field '%s' must be a boolean." % key)
    return body[key]


def _to_decimal(value, key):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad_request("Field '%s' must be a number." % key)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise bad_request("Field '%s' must be a number." % key)


def req_pct(body, key, minimum=None, maximum=None):
    """A percentage carried to two decimal places."""
    if not _present(body, key):
        raise bad_request("Field '%s' is required." % key)
    value = round2(_to_decimal(body[key], key))
    if minimum is not None and value < minimum:
        raise bad_request("Field '%s' is below its minimum." % key)
    if maximum is not None and value > maximum:
        raise bad_request("Field '%s' is above its maximum." % key)
    return value


def req_rate(body, key):
    """An exchange rate carried to six decimal places, strictly positive."""
    if not _present(body, key):
        raise bad_request("Field '%s' is required." % key)
    value = round6(_to_decimal(body[key], key))
    if value <= 0:
        raise bad_request("Field '%s' must be strictly positive." % key)
    return value


def req_enum(body, key, allowed):
    value = req_str(body, key, min_len=1, max_len=None)
    if value not in allowed:
        raise bad_request("Field '%s' is not a member of its enumeration." % key)
    return value


def opt_enum(body, key, allowed, default=None):
    if not _present(body, key):
        return default
    value = _as_str(body[key], key, 1, None)
    if value not in allowed:
        raise bad_request("Field '%s' is not a member of its enumeration." % key)
    return value


def req_enum_list(body, key, allowed, min_len=1, max_len=None):
    if not _present(body, key):
        raise bad_request("Field '%s' is required." % key)
    return _as_enum_list(body[key], key, allowed, min_len, max_len)


def opt_enum_list(body, key, allowed, min_len=0, max_len=None, default=None):
    if not _present(body, key):
        return list(default) if default is not None else None
    return _as_enum_list(body[key], key, allowed, min_len, max_len)


def _as_enum_list(value, key, allowed, min_len, max_len):
    if not isinstance(value, list):
        raise bad_request("Field '%s' must be an array." % key)
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            raise bad_request("Field '%s' holds a value outside its enumeration." % key)
    if len(set(value)) != len(value):
        raise bad_request("Field '%s' must hold distinct values." % key)
    if min_len is not None and len(value) < min_len:
        raise bad_request("Field '%s' has too few entries." % key)
    if max_len is not None and len(value) > max_len:
        raise bad_request("Field '%s' has too many entries." % key)
    return list(value)


def req_date(body, key):
    if not _present(body, key):
        raise bad_request("Field '%s' is required." % key)
    return _as_date(body[key], key)


def opt_date(body, key, default=None):
    if not _present(body, key):
        return default
    return _as_date(body[key], key)


def _as_date(value, key):
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be a YYYY-MM-DD date string." % key)
    parsed = parse_date(value)
    if parsed is None:
        raise bad_request("Field '%s' is not a valid ISO 8601 date." % key)
    return parsed


def req_instant(body, key):
    if not _present(body, key):
        raise bad_request("Field '%s' is required." % key)
    return _as_instant(body[key], key)


def opt_instant(body, key, default=None):
    if not _present(body, key):
        return default
    return _as_instant(body[key], key)


def _as_instant(value, key):
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be an ISO 8601 instant string." % key)
    parsed = parse_instant(value)
    if parsed is None:
        raise bad_request("Field '%s' is not a valid ISO 8601 instant." % key)
    return parsed


def req_date_list(body, key, min_len=0, max_len=None):
    if not _present(body, key):
        raise bad_request("Field '%s' is required." % key)
    return _as_date_list(body[key], key, min_len, max_len)


def opt_date_list(body, key, min_len=0, max_len=None, default=None):
    if not _present(body, key):
        return list(default) if default is not None else None
    return _as_date_list(body[key], key, min_len, max_len)


def _as_date_list(value, key, min_len, max_len):
    if not isinstance(value, list):
        raise bad_request("Field '%s' must be an array." % key)
    out = []
    for item in value:
        parsed = _as_date(item, key)
        out.append(item)
    if len(set(out)) != len(out):
        raise bad_request("Field '%s' must hold distinct dates." % key)
    if min_len is not None and len(out) < min_len:
        raise bad_request("Field '%s' has too few entries." % key)
    if max_len is not None and len(out) > max_len:
        raise bad_request("Field '%s' has too many entries." % key)
    return out


def req_str_map(body, key):
    if not _present(body, key):
        raise bad_request("Field '%s' is required." % key)
    value = body[key]
    if not isinstance(value, dict):
        raise bad_request("Field '%s' must be an object." % key)
    for mk, mv in value.items():
        if not isinstance(mk, str) or not isinstance(mv, str):
            raise bad_request("Field '%s' must map strings to strings." % key)
    return dict(value)


def req_country_code(body, key):
    value = req_str(body, key, 2, 2)
    if not COUNTRY_CODE_RE.match(value):
        raise bad_request("Field '%s' must be two uppercase letters." % key)
    return value


def req_currency(body, key):
    value = req_str(body, key, 3, 3)
    if not CURRENCY_RE.match(value):
        raise bad_request("Field '%s' must be three uppercase letters." % key)
    return value


def req_id(body, key):
    """A foreign-key reference: must be a non-empty string."""
    return req_str(body, key, 1, None)


def opt_id(body, key):
    if key not in body or body[key] is None:
        return None
    return _as_str(body[key], key, 1, None)


# ---------------------------------------------------------------------------
# Query parameters
# ---------------------------------------------------------------------------
def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise bad_request("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            raise bad_request("Query parameter 'limit' must be between 1 and 100.")
    raw = raw_offset
    if raw is not None and raw != "":
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise bad_request("Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise bad_request("Query parameter 'offset' may not be negative.")
    return limit, offset


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in allowed:
        raise bad_request("Query parameter '%s' is not a member of its enumeration." % name)
    return value


def query_value(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value

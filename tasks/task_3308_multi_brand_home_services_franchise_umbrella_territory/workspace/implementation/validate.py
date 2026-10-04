"""PRD 2.5 rung 3: request-body schema validation, plus pagination parsing.

Every failure here yields ERR_INVALID_REQUEST (400) unless the transition
declares a more specific identifier (ERR_AUDITOR_REQUIRED, ERR_APPROVER_REQUIRED).
"""
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from store import parse_instant

_MISSING = object()


def bad(message="The request is malformed."):
    return ApiError("ERR_INVALID_REQUEST", message)


def body():
    """The JSON body as a dict; a missing body is treated as {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise bad("The request body must be a JSON object.")
    return data


def reject_unknown(b, allowed):
    """No field outside the endpoint's declared input list may be supplied."""
    allowed = set(allowed)
    for key in b:
        if key not in allowed:
            raise bad("Field '%s' is not accepted by this endpoint." % key)


def present(b, key):
    return key in b and b[key] is not None


# ---------------------------------------------------------------------------
# strings
# ---------------------------------------------------------------------------
def req_str(b, key, min_len=1, max_len=None):
    v = b.get(key, _MISSING)
    if v is _MISSING or v is None:
        raise bad("Field '%s' is required." % key)
    if not isinstance(v, str):
        raise bad("Field '%s' must be a string." % key)
    if len(v) < min_len:
        raise bad("Field '%s' must be at least %d characters." % (key, min_len))
    if max_len is not None and len(v) > max_len:
        raise bad("Field '%s' may be at most %d characters." % (key, max_len))
    return v


def opt_str(b, key, default=None, min_len=0, max_len=None):
    if not present(b, key):
        return default
    return req_str(b, key, min_len=min_len, max_len=max_len)


def req_id(b, key):
    """A referenced identifier: must be a non-empty string when supplied."""
    return req_str(b, key)


def opt_id(b, key, default=None):
    if key not in b or b[key] is None:
        return default
    v = b[key]
    if not isinstance(v, str) or not v:
        raise bad("Field '%s' must be a non-empty string identifier." % key)
    return v


def opt_id_list(b, key, default=None):
    if key not in b or b[key] is None:
        return list(default) if default is not None else []
    v = b[key]
    if not isinstance(v, list):
        raise bad("Field '%s' must be an array of identifiers." % key)
    out = []
    for item in v:
        if not isinstance(item, str) or not item:
            raise bad("Field '%s' must contain only non-empty string identifiers." % key)
        out.append(item)
    return out


def req_str_list(b, key, min_items=1):
    v = b.get(key, _MISSING)
    if v is _MISSING or v is None:
        raise bad("Field '%s' is required." % key)
    if not isinstance(v, list):
        raise bad("Field '%s' must be an array." % key)
    out = []
    for item in v:
        if not isinstance(item, str) or not item:
            raise bad("Field '%s' must contain only non-empty strings." % key)
        out.append(item)
    if len(out) < min_items:
        raise bad("Field '%s' must contain at least %d item(s)." % (key, min_items))
    return out


# ---------------------------------------------------------------------------
# integers
# ---------------------------------------------------------------------------
def _as_int(key, v):
    if isinstance(v, bool) or not isinstance(v, int):
        raise bad("Field '%s' must be an integer." % key)
    return v


def req_int(b, key, minimum=None, maximum=None):
    v = b.get(key, _MISSING)
    if v is _MISSING or v is None:
        raise bad("Field '%s' is required." % key)
    v = _as_int(key, v)
    if minimum is not None and v < minimum:
        raise bad("Field '%s' must be at least %d." % (key, minimum))
    if maximum is not None and v > maximum:
        raise bad("Field '%s' may be at most %d." % (key, maximum))
    return v


def opt_int(b, key, default=None, minimum=None, maximum=None):
    if not present(b, key):
        return default
    return req_int(b, key, minimum=minimum, maximum=maximum)


def req_money(b, key, minimum=0):
    """Integer money fields are whole cents and at least `minimum`."""
    return req_int(b, key, minimum=minimum)


def opt_money(b, key, default=0, minimum=0):
    return opt_int(b, key, default=default, minimum=minimum)


# ---------------------------------------------------------------------------
# booleans
# ---------------------------------------------------------------------------
def opt_bool(b, key, default=False):
    if not present(b, key):
        return default
    v = b[key]
    if not isinstance(v, bool):
        raise bad("Field '%s' must be a boolean." % key)
    return v


# ---------------------------------------------------------------------------
# decimals / rates
# ---------------------------------------------------------------------------
def as_decimal(key, v):
    if isinstance(v, bool):
        raise bad("Field '%s' must be a number." % key)
    if isinstance(v, str):
        raise bad("Field '%s' must be a number." % key)
    if not isinstance(v, (int, float, Decimal)):
        raise bad("Field '%s' must be a number." % key)
    try:
        return Decimal(str(v)) if not isinstance(v, Decimal) else v
    except (InvalidOperation, ValueError):
        raise bad("Field '%s' must be a number." % key)


def req_decimal(b, key, minimum=None, maximum=None):
    v = b.get(key, _MISSING)
    if v is _MISSING or v is None:
        raise bad("Field '%s' is required." % key)
    d = as_decimal(key, v)
    if minimum is not None and d < minimum:
        raise bad("Field '%s' is out of range." % key)
    if maximum is not None and d > maximum:
        raise bad("Field '%s' is out of range." % key)
    return d


def opt_decimal(b, key, default=None, minimum=None, maximum=None):
    if not present(b, key):
        return default
    return req_decimal(b, key, minimum=minimum, maximum=maximum)


def req_rate(b, key):
    """royalty_rate / national_ad_fund_rate: closed unit interval."""
    return req_decimal(b, key, minimum=Decimal("0"), maximum=Decimal("1"))


def opt_rate(b, key, default=None):
    return opt_decimal(b, key, default=default, minimum=Decimal("0"), maximum=Decimal("1"))


# ---------------------------------------------------------------------------
# enums and instants
# ---------------------------------------------------------------------------
def req_enum(b, key, allowed):
    v = req_str(b, key)
    if v not in allowed:
        raise bad("Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return v


def opt_enum(b, key, allowed, default=None):
    if not present(b, key):
        return default
    return req_enum(b, key, allowed)


def req_datetime(b, key):
    v = req_str(b, key)
    parsed = parse_instant(v)
    if parsed is None:
        raise bad("Field '%s' must be an ISO 8601 UTC instant." % key)
    return parsed


def opt_datetime(b, key, default=None):
    if not present(b, key):
        return default
    return req_datetime(b, key)


def req_object(b, key):
    v = b.get(key, _MISSING)
    if v is _MISSING or v is None:
        raise bad("Field '%s' is required." % key)
    if not isinstance(v, dict):
        raise bad("Field '%s' must be an object." % key)
    return v


def opt_object(b, key, default=None):
    if not present(b, key):
        return default
    return req_object(b, key)


# ---------------------------------------------------------------------------
# pagination (SCAFFOLD response_envelope.pagination_defaults / PRD 2.3)
# ---------------------------------------------------------------------------
def pagination():
    from response import DEFAULT_LIMIT, DEFAULT_OFFSET, MAX_LIMIT, MIN_LIMIT

    args = request.args
    limit = DEFAULT_LIMIT
    offset = DEFAULT_OFFSET
    raw = args.get("limit")
    if raw is not None and raw != "":
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise bad("Query parameter 'limit' must be an integer.")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise bad("Query parameter 'limit' must lie within 1 through 100.")
    raw = args.get("offset")
    if raw is not None and raw != "":
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise bad("Query parameter 'offset' may not be negative.")
    return limit, offset


def filters(*names):
    """The subset of the declared filter parameters that were supplied."""
    out = {}
    for name in names:
        raw = request.args.get(name)
        if raw is not None and raw != "":
            out[name] = raw
    return out


def match(record, supplied):
    for key, raw in supplied.items():
        value = record.get(key)
        if isinstance(value, bool):
            want = raw.lower()
            if want in ("true", "1"):
                if value is not True:
                    return False
            elif want in ("false", "0"):
                if value is not False:
                    return False
            else:
                return False
        elif isinstance(value, list):
            if raw not in value:
                return False
        elif isinstance(value, int):
            try:
                if value != int(raw):
                    return False
            except (TypeError, ValueError):
                return False
        else:
            if value is None or str(value) != raw:
                return False
    return True
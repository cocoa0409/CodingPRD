"""Band 4 of PRD 2.6: request-body schema validation and pagination parsing."""
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError

_MISSING = object()


def bad(message="The request is malformed."):
    return ApiError("ERR_INVALID_REQUEST", message)


def body():
    """The JSON body as a dict; a missing body is treated as {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise bad("Request body must be a JSON object.")
    return data


def present(b, key):
    return key in b and b[key] is not None


# --------------------------------------------------------------------------
# strings
# --------------------------------------------------------------------------
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


# --------------------------------------------------------------------------
# integers
# --------------------------------------------------------------------------
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


def req_money(b, key):
    """Integer money fields are at least 0."""
    return req_int(b, key, minimum=0)


# --------------------------------------------------------------------------
# booleans
# --------------------------------------------------------------------------
def opt_bool(b, key, default=False):
    if not present(b, key):
        return default
    v = b[key]
    if not isinstance(v, bool):
        raise bad("Field '%s' must be a boolean." % key)
    return v


# --------------------------------------------------------------------------
# decimals / geometry
# --------------------------------------------------------------------------
def _as_decimal(key, v):
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise bad("Field '%s' must be a number." % key)
    if isinstance(v, str):
        raise bad("Field '%s' must be a number." % key)
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        raise bad("Field '%s' must be a number." % key)


def req_decimal(b, key, minimum=None, maximum=None):
    v = b.get(key, _MISSING)
    if v is _MISSING or v is None:
        raise bad("Field '%s' is required." % key)
    d = _as_decimal(key, v)
    if minimum is not None and d < minimum:
        raise bad("Field '%s' is out of range." % key)
    if maximum is not None and d > maximum:
        raise bad("Field '%s' is out of range." % key)
    return d


def opt_decimal(b, key, default=None, minimum=None, maximum=None):
    if not present(b, key):
        return default
    return req_decimal(b, key, minimum=minimum, maximum=maximum)


def req_lat(b, key):
    return req_decimal(b, key, minimum=Decimal("-90"), maximum=Decimal("90"))


def req_lng(b, key):
    return req_decimal(b, key, minimum=Decimal("-180"), maximum=Decimal("180"))


def req_radius(b, key):
    """protected_radius_km / requested_radius_km: > 0, accepted 0.5 .. 50.0."""
    d = req_decimal(b, key, minimum=Decimal("0.5"), maximum=Decimal("50.0"))
    if d <= 0:
        raise bad("Field '%s' must be greater than 0." % key)
    return d


# --------------------------------------------------------------------------
# enums and dates
# --------------------------------------------------------------------------
def req_enum(b, key, allowed):
    v = req_str(b, key)
    if v not in allowed:
        raise bad("Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return v


def opt_enum(b, key, allowed, default=None):
    if not present(b, key):
        return default
    return req_enum(b, key, allowed)


def _valid_date_str(v):
    if len(v) != 10 or v[4] != "-" or v[7] != "-":
        return False
    if not (v[0:4].isdigit() and v[5:7].isdigit() and v[8:10].isdigit()):
        return False
    import datetime as _dt
    try:
        _dt.date(int(v[0:4]), int(v[5:7]), int(v[8:10]))
    except ValueError:
        return False
    return True


def req_date(b, key):
    v = req_str(b, key)
    if not _valid_date_str(v):
        raise bad("Field '%s' must be a YYYY-MM-DD date." % key)
    return v


def opt_date(b, key, default=None):
    if not present(b, key):
        return default
    return req_date(b, key)


def req_month(b, key):
    v = req_str(b, key)
    if len(v) != 7 or v[4] != "-" or not (v[0:4].isdigit() and v[5:7].isdigit()):
        raise bad("Field '%s' must be a YYYY-MM period." % key)
    if not 1 <= int(v[5:7]) <= 12:
        raise bad("Field '%s' must be a YYYY-MM period." % key)
    return v


def req_id(b, key):
    """A referenced identifier: must be a non-empty string when supplied."""
    return req_str(b, key)


def opt_id(b, key, default=None):
    if key not in b or b[key] is None:
        return default
    v = b[key]
    if not isinstance(v, str) or not v:
        raise bad("Field '%s' must be a string identifier." % key)
    return v


def req_datetime(b, key):
    v = req_str(b, key)
    import datetime as _dt
    raw = v[:-1] + "+00:00" if v.endswith("Z") else v
    try:
        parsed = _dt.datetime.fromisoformat(raw)
    except ValueError:
        raise bad("Field '%s' must be an ISO 8601 UTC instant." % key)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed.astimezone(_dt.timezone.utc)


# --------------------------------------------------------------------------
# pagination (PRD 2.3)
# --------------------------------------------------------------------------
def pagination():
    args = request.args
    limit = 10
    offset = 0
    raw = args.get("limit")
    if raw is not None and raw != "":
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise bad("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
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
    """Returns the subset of the declared filter params that were supplied."""
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

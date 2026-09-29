"""Request shape validation (PRD 2.8 priority 3) and numeric/temporal helpers."""

import json
import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from flask import request

import errors
from errors import fail

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.(\d{1,9}))?"
    r"([Zz]|[+-]\d{2}:?\d{2})$"
)


# --------------------------------------------------------------------------
# body / query access
# --------------------------------------------------------------------------
def body():
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw, parse_float=Decimal)
    except Exception:
        fail(errors.ERR_INVALID_REQUEST, "Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return parsed


def present(payload, field):
    return field in payload and payload[field] is not None


# --------------------------------------------------------------------------
# scalar validators
# --------------------------------------------------------------------------
def req_field(payload, field):
    if not present(payload, field):
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' is required." % field)
    return payload[field]


def opt_string(payload, field, min_len=1, max_len=None, default=None,
               allow_null=False):
    if field not in payload:
        return default
    value = payload[field]
    if value is None:
        if allow_null:
            return None
        return default
    return _check_string(field, value, min_len, max_len)


def req_string(payload, field, min_len=1, max_len=None):
    value = req_field(payload, field)
    return _check_string(field, value, min_len, max_len)


def _check_string(field, value, min_len, max_len):
    if not isinstance(value, str):
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be a string." % field)
    if min_len is not None and min_len >= 1 and value.strip() == "":
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must not be blank." % field)
    if min_len is not None and len(value) < min_len:
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' is too short." % field)
    if max_len is not None and len(value) > max_len:
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' is too long." % field)
    return value


def req_enum(payload, field, allowed):
    value = req_field(payload, field)
    return _check_enum(field, value, allowed)


def opt_enum(payload, field, allowed, default=None):
    if field not in payload or payload[field] is None:
        return default
    return _check_enum(field, payload[field], allowed)


def _check_enum(field, value, allowed):
    if not isinstance(value, str) or value not in allowed:
        fail(errors.ERR_INVALID_REQUEST,
             "Field '%s' must be one of %s." % (field, ", ".join(sorted(allowed))))
    return value


def req_int(payload, field, minimum=None, maximum=None):
    value = req_field(payload, field)
    return _check_int(field, value, minimum, maximum)


def opt_int(payload, field, minimum=None, maximum=None, default=None):
    if field not in payload or payload[field] is None:
        return default
    return _check_int(field, payload[field], minimum, maximum)


def _check_int(field, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' is below its minimum." % field)
    if maximum is not None and value > maximum:
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' is above its maximum." % field)
    return value


def req_bool(payload, field):
    value = req_field(payload, field)
    if not isinstance(value, bool):
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be a boolean." % field)
    return value


def opt_bool(payload, field, default=None):
    if field not in payload or payload[field] is None:
        return default
    value = payload[field]
    if not isinstance(value, bool):
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be a boolean." % field)
    return value


def req_decimal(payload, field, places=2, minimum=None, maximum=None):
    value = req_field(payload, field)
    return _check_decimal(field, value, places, minimum, maximum)


def opt_decimal(payload, field, places=2, minimum=None, maximum=None,
                default=None):
    if field not in payload or payload[field] is None:
        return default
    return _check_decimal(field, payload[field], places, minimum, maximum)


def _check_decimal(field, value, places, minimum, maximum):
    if isinstance(value, bool):
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be a number." % field)
    if isinstance(value, int):
        dec = Decimal(value)
    elif isinstance(value, Decimal):
        dec = value
    elif isinstance(value, float):
        dec = Decimal(repr(value))
    elif isinstance(value, str):
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be a number." % field)
    else:
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be a number." % field)
    if not dec.is_finite():
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be a finite number." % field)
    exponent = dec.as_tuple().exponent
    if isinstance(exponent, int) and -exponent > places:
        fail(errors.ERR_INVALID_REQUEST,
             "Field '%s' allows at most %d decimal places." % (field, places))
    if minimum is not None and dec < minimum:
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' is below its minimum." % field)
    if maximum is not None and dec > maximum:
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' is above its maximum." % field)
    return quantize(dec, places)


def req_semver(payload, field):
    value = req_string(payload, field, 1, 64)
    if not SEMVER_RE.match(value):
        fail(errors.ERR_INVALID_REQUEST,
             "Field '%s' must be a three-part dotted numeric version." % field)
    return value


def req_datetime(payload, field):
    value = req_field(payload, field)
    return parse_instant(field, value)


def opt_datetime(payload, field, default=None):
    if field not in payload or payload[field] is None:
        return default
    return parse_instant(field, payload[field])


def parse_instant(field, value):
    if not isinstance(value, str):
        fail(errors.ERR_INVALID_REQUEST,
             "Field '%s' must be an ISO 8601 UTC instant." % field)
    match = _ISO_RE.match(value.strip())
    if not match:
        fail(errors.ERR_INVALID_REQUEST,
             "Field '%s' must be an ISO 8601 UTC instant." % field)
    offset = match.group(9)
    if offset not in ("Z", "z"):
        normalised = offset.replace(":", "")
        if normalised not in ("+0000", "-0000"):
            fail(errors.ERR_INVALID_REQUEST,
                 "Field '%s' must be expressed in UTC." % field)
    frac = match.group(8) or "0"
    micro = int((frac + "000000")[:6])
    try:
        return datetime(
            int(match.group(1)), int(match.group(2)), int(match.group(3)),
            int(match.group(4)), int(match.group(5)), int(match.group(6)),
            micro, tzinfo=timezone.utc,
        )
    except ValueError:
        fail(errors.ERR_INVALID_REQUEST,
             "Field '%s' must be a valid ISO 8601 UTC instant." % field)


# --------------------------------------------------------------------------
# query parameters
# --------------------------------------------------------------------------
def query_enum(field, allowed, default=None):
    raw = request.args.get(field)
    if raw is None or raw == "":
        return default
    if raw not in allowed:
        fail(errors.ERR_INVALID_REQUEST,
             "Query field '%s' must be one of %s." % (field, ", ".join(sorted(allowed))))
    return raw


def query_string(field, default=None):
    raw = request.args.get(field)
    if raw is None or raw == "":
        return default
    return raw


def query_int(field, default=None, minimum=None, maximum=None):
    raw = request.args.get(field)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        fail(errors.ERR_INVALID_REQUEST, "Query field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        fail(errors.ERR_INVALID_REQUEST, "Query field '%s' is out of range." % field)
    if maximum is not None and value > maximum:
        fail(errors.ERR_INVALID_REQUEST, "Query field '%s' is out of range." % field)
    return value


def pagination():
    limit = query_int("limit", default=10, minimum=1, maximum=100)
    offset = query_int("offset", default=0, minimum=0)
    return limit, offset


# --------------------------------------------------------------------------
# numeric helpers
# --------------------------------------------------------------------------
def quantize(value, places=2):
    exp = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(exp, rounding=ROUND_HALF_UP)


def dec2(value):
    return quantize(value, 2)


def dec4(value):
    return quantize(value, 4)

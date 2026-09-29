"""Request-shape validation (PRD 2.9 step 8) and value coercion helpers."""

import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import request

from errors import ApiError

MISSING = object()


def bad(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def parse_body():
    """Parse the JSON body preserving decimal literals exactly.

    A malformed body is reported through the returned flag so the caller can
    raise ERR_INVALID_REQUEST at the request-shape step of the ladder rather
    than before the auth and existence steps.
    """
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}, False
    try:
        parsed = json.loads(raw, parse_float=Decimal)
    except Exception:
        return {}, True
    if not isinstance(parsed, dict):
        return {}, True
    return parsed, False


def field(body, name):
    if not isinstance(body, dict):
        return MISSING
    return body.get(name, MISSING)


def require_present(body, names):
    for name in names:
        if field(body, name) is MISSING or body.get(name) is None:
            raise bad("Field '%s' is required." % name)


def as_string(value, name, min_len=1, max_len=None):
    if not isinstance(value, str):
        raise bad("Field '%s' must be a string." % name)
    if len(value) < min_len:
        raise bad("Field '%s' must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        raise bad("Field '%s' must be at most %d characters." % (name, max_len))
    return value


def as_bool(value, name):
    if not isinstance(value, bool):
        raise bad("Field '%s' must be a boolean." % name)
    return value


def as_int(value, name, minimum=None, maximum=None):
    if isinstance(value, bool):
        raise bad("Field '%s' must be an integer." % name)
    if isinstance(value, int):
        out = value
    elif isinstance(value, Decimal):
        if value != value.to_integral_value():
            raise bad("Field '%s' must be an integer." % name)
        out = int(value)
    elif isinstance(value, float):
        if float(value).is_integer():
            out = int(value)
        else:
            raise bad("Field '%s' must be an integer." % name)
    elif isinstance(value, str):
        try:
            dec = Decimal(value.strip())
        except (InvalidOperation, ValueError):
            raise bad("Field '%s' must be an integer." % name)
        if dec != dec.to_integral_value():
            raise bad("Field '%s' must be an integer." % name)
        out = int(dec)
    else:
        raise bad("Field '%s' must be an integer." % name)
    if minimum is not None and out < minimum:
        raise bad("Field '%s' must be at least %d." % (name, minimum))
    if maximum is not None and out > maximum:
        raise bad("Field '%s' must be at most %d." % (name, maximum))
    return out


def as_decimal(value, name, minimum=None, maximum=None, exclusive_min=False,
               max_decimals=4):
    if isinstance(value, bool):
        raise bad("Field '%s' must be a number." % name)
    if isinstance(value, Decimal):
        dec = value
    elif isinstance(value, int):
        dec = Decimal(value)
    elif isinstance(value, float):
        dec = Decimal(repr(value))
    elif isinstance(value, str):
        try:
            dec = Decimal(value.strip())
        except (InvalidOperation, ValueError):
            raise bad("Field '%s' must be a number." % name)
    else:
        raise bad("Field '%s' must be a number." % name)
    if not dec.is_finite():
        raise bad("Field '%s' must be a finite number." % name)
    if max_decimals is not None and -dec.as_tuple().exponent > max_decimals:
        raise bad("Field '%s' carries more than %d decimal places." % (name, max_decimals))
    if minimum is not None:
        if exclusive_min and dec <= minimum:
            raise bad("Field '%s' must be greater than %s." % (name, minimum))
        if not exclusive_min and dec < minimum:
            raise bad("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and dec > maximum:
        raise bad("Field '%s' must be at most %s." % (name, maximum))
    return dec


def as_enum(value, name, members):
    if not isinstance(value, str) or value not in members:
        raise bad("Field '%s' must be one of %s." % (name, ", ".join(sorted(members))))
    return value


_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([Tt ].*)?$")


def as_instant(value, name):
    """Parse an ISO 8601 instant; a naive instant is read as UTC."""
    if not isinstance(value, str) or not _ISO_RE.match(value.strip()):
        raise bad("Field '%s' must be an ISO 8601 instant." % name)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    text = text.replace(" ", "T", 1) if (" " in text and "T" not in text) else text
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise bad("Field '%s' must be an ISO 8601 instant." % name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def round_half_up(value, places):
    quant = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def round_cents(value):
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


HEX64 = re.compile(r"^[0-9a-f]{64}$")
STATE_CODE = re.compile(r"^[A-Z]{2}$")
MCC = re.compile(r"^[0-9]{4}$")

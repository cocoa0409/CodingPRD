"""Request-shape validation (PRD 2.6 stage 5).

Every failure in this module is ERR_INVALID_REQUEST (400).  Cross-field pairing
rules (stage 6) live with their workflows and raise
ERR_FIELD_COMBINATION_INVALID (422) instead.
"""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from flask import request

from errors import invalid_request

INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?Z$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
GRID_REF_RE = re.compile(r"^[A-J](10|[1-9])$")
LICENSE_NUMBER_RE = re.compile(r"^[A-Z]{2}-[0-9]{5}$")
STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")
FUM_PERMIT_RE = re.compile(r"^FUM-[0-9]{6}$")
EPA_RE = re.compile(r"^[0-9]{3,5}-[0-9]{2,4}$")


def body():
    """The request body as a dict.  An absent body reads as an empty object."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None or not isinstance(parsed, dict):
        raise invalid_request("request body must be a JSON object")
    return parsed


def present(payload, name):
    return name in payload and payload[name] is not None


def has_key(payload, name):
    return name in payload


def _missing(name):
    return invalid_request("%s is required and must be non-null" % name)


def get_string(payload, name, required=True, default=None, min_len=1, max_len=None,
               pattern=None, non_blank=True):
    if not present(payload, name):
        if required:
            raise _missing(name)
        return default
    value = payload[name]
    if not isinstance(value, str):
        raise invalid_request("%s must be a string" % name)
    if non_blank and value.strip() == "":
        raise invalid_request("%s must not be blank" % name)
    if min_len is not None and len(value) < min_len:
        raise invalid_request("%s must be at least %d characters" % (name, min_len))
    if max_len is not None and len(value) > max_len:
        raise invalid_request("%s must be at most %d characters" % (name, max_len))
    if pattern is not None and not pattern.match(value):
        raise invalid_request("%s is malformed" % name)
    return value


def get_enum(payload, name, allowed, required=True, default=None):
    if not present(payload, name):
        if required:
            raise _missing(name)
        return default
    value = payload[name]
    if not isinstance(value, str):
        raise invalid_request("%s must be a string" % name)
    if value not in allowed:
        raise invalid_request("%s must be one of %s" % (name, ", ".join(sorted(allowed))))
    return value


def get_int(payload, name, required=True, default=None, minimum=None, maximum=None):
    if not present(payload, name):
        if required:
            raise _missing(name)
        return default
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid_request("%s must be an integer" % name)
    if minimum is not None and value < minimum:
        raise invalid_request("%s must be >= %d" % (name, minimum))
    if maximum is not None and value > maximum:
        raise invalid_request("%s must be <= %d" % (name, maximum))
    return value


def get_bool(payload, name, required=True, default=None):
    if not present(payload, name):
        if required:
            raise _missing(name)
        return default
    value = payload[name]
    if not isinstance(value, bool):
        raise invalid_request("%s must be a boolean" % name)
    return value


def get_money(payload, name, required=True, default=None, minimum=None, maximum=None,
              decimals=2):
    """A JSON number, at least zero, with at most `decimals` decimal places."""
    if not present(payload, name):
        if required:
            raise _missing(name)
        return default
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid_request("%s must be a JSON number" % name)
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        raise invalid_request("%s must be a JSON number" % name)
    if dec < 0:
        raise invalid_request("%s must be >= 0" % name)
    exponent = dec.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -decimals:
        raise invalid_request("%s must carry at most %d decimal places" % (name, decimals))
    if minimum is not None and dec < Decimal(str(minimum)):
        raise invalid_request("%s must be >= %s" % (name, minimum))
    if maximum is not None and dec > Decimal(str(maximum)):
        raise invalid_request("%s must be <= %s" % (name, maximum))
    return dec


def get_instant(payload, name, required=True, default=None):
    if not present(payload, name):
        if required:
            raise _missing(name)
        return default
    value = payload[name]
    if not isinstance(value, str) or not INSTANT_RE.match(value):
        raise invalid_request("%s must be an RFC 3339 UTC instant ending in Z" % name)
    head = value[:-1]
    try:
        if "." in head:
            base, frac = head.split(".", 1)
            frac = (frac + "000000")[:6]
            parsed = datetime.strptime(base, "%Y-%m-%dT%H:%M:%S").replace(
                microsecond=int(frac))
        else:
            parsed = datetime.strptime(head, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        raise invalid_request("%s is not a valid instant" % name)
    return parsed


def get_date(payload, name, required=True, default=None):
    if not present(payload, name):
        if required:
            raise _missing(name)
        return default
    value = payload[name]
    if not isinstance(value, str) or not DATE_RE.match(value):
        raise invalid_request("%s must be a YYYY-MM-DD calendar date" % name)
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise invalid_request("%s is not a valid calendar date" % name)
    return parsed


def get_enum_array(payload, name, allowed, required=True, default=None,
                   min_items=None, max_items=None, distinct=True):
    if not present(payload, name):
        if required:
            raise _missing(name)
        return list(default) if default is not None else None
    value = payload[name]
    if not isinstance(value, list):
        raise invalid_request("%s must be an array" % name)
    for member in value:
        if not isinstance(member, str) or member not in allowed:
            raise invalid_request("%s members must be one of %s"
                                  % (name, ", ".join(sorted(allowed))))
    if distinct and len(set(value)) != len(value):
        raise invalid_request("%s members must be distinct" % name)
    if min_items is not None and len(value) < min_items:
        raise invalid_request("%s must carry at least %d members" % (name, min_items))
    if max_items is not None and len(value) > max_items:
        raise invalid_request("%s must carry at most %d members" % (name, max_items))
    return value


def query_enum(name, allowed):
    """Filter values are exact-match equality tests; unknown values match nothing."""
    if name not in request.args:
        return None
    return request.args.get(name)


def query_str(name):
    if name not in request.args:
        return None
    return request.args.get(name)


def query_bool(name):
    if name not in request.args:
        return None
    raw = request.args.get(name, "").strip().lower()
    if raw in ("true", "1"):
        return True
    if raw in ("false", "0"):
        return False
    return "__no_match__"

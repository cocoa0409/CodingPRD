"""Request-body shape validation (PRD 2.10 step 4 -> ERR_INVALID_REQUEST 400).

Every constraint here comes from SCAFFOLD.yaml section 1.1 field `constraints`
and the PRD section 3 narratives: string lengths, enum membership, at-most-two
decimal numerics inside declared ranges, non-empty arrays, duplicate-free
arrays and the literal `https://` prefix on URL fields.
"""

import re
from decimal import Decimal, InvalidOperation

from flask import request

from core import D, fail, parse_iso

CODE_RE = re.compile(r"^[A-Z0-9_]+$")
COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


def bad(message=None):
    fail("ERR_INVALID_REQUEST", 400, message)


def body_or_empty():
    """Parse the JSON body leniently -- used by the ownership pre-check that
    PRD 2.10 places ahead of body-shape validation."""
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        return {}
    if isinstance(data, dict):
        return data
    return {}


def read_body(allowed, required=()):
    """Parse and screen the body: valid JSON object, no unknown fields, every
    required field present."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        data = {}
    else:
        try:
            data = request.get_json(force=True, silent=False)
        except Exception:
            bad("Request body is not valid JSON.")
        if data is None:
            data = {}
    if not isinstance(data, dict):
        bad("Request body must be a JSON object.")
    for key in data.keys():
        if key not in allowed:
            bad("Unknown field: %s" % key)
    for key in required:
        if key not in data or data[key] is None:
            bad("Missing required field: %s" % key)
    return data


def _is_bool(value):
    return isinstance(value, bool)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    return (isinstance(value, int) or isinstance(value, float)) and not isinstance(value, bool)


def v_string(data, key, min_len, max_len, required=True, default=None, nullable=False):
    if key not in data:
        return default
    value = data[key]
    if value is None:
        if nullable:
            return None
        if required:
            bad("%s must be a string." % key)
        return default
    if not isinstance(value, str):
        bad("%s must be a string." % key)
    if len(value) < min_len or len(value) > max_len:
        bad("%s must be between %d and %d characters." % (key, min_len, max_len))
    return value


def v_enum(data, key, values, required=True, default=None):
    if key not in data or data[key] is None:
        if required:
            bad("%s is required." % key)
        return default
    value = data[key]
    if not isinstance(value, str) or value not in values:
        bad("%s must be one of %s." % (key, ", ".join(sorted(values))))
    return value


def v_bool(data, key, default=None):
    if key not in data or data[key] is None:
        return default
    value = data[key]
    if not _is_bool(value):
        bad("%s must be a boolean." % key)
    return value


def v_int(data, key, minimum, maximum, default=None):
    if key not in data or data[key] is None:
        return default
    value = data[key]
    if not _is_int(value):
        bad("%s must be an integer." % key)
    if minimum is not None and value < minimum:
        bad("%s must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be <= %s." % (key, maximum))
    return value


def v_decimal2(data, key, minimum, maximum, default=None):
    """A decimal carried to at most 2 places inside [minimum, maximum]."""
    if key not in data or data[key] is None:
        return default
    value = data[key]
    if not _is_number(value):
        bad("%s must be a number." % key)
    try:
        dec = D(repr(value) if isinstance(value, float) else value)
    except (InvalidOperation, ValueError):
        bad("%s must be a number." % key)
    exponent = dec.normalize().as_tuple().exponent
    if exponent < -2:
        bad("%s must carry at most 2 decimal places." % key)
    if minimum is not None and dec < D(minimum):
        bad("%s must be >= %s." % (key, minimum))
    if maximum is not None and dec > D(maximum):
        bad("%s must be <= %s." % (key, maximum))
    return dec


def v_datetime(data, key, required=True, default=None):
    if key not in data or data[key] is None:
        if required:
            bad("%s is required." % key)
        return default
    value = data[key]
    if not isinstance(value, str):
        bad("%s must be an ISO 8601 UTC instant." % key)
    parsed = parse_iso(value)
    if parsed is None:
        bad("%s must be an ISO 8601 UTC instant." % key)
    return parsed


def v_array(data, key, required=True, default=None, non_empty=True,
            no_duplicates=True, element=None, min_len=None, max_len=None):
    """element: a callable taking (value, key) that validates one element."""
    if key not in data or data[key] is None:
        if required:
            bad("%s is required." % key)
        return default
    value = data[key]
    if not isinstance(value, list):
        bad("%s must be an array." % key)
    if non_empty and len(value) == 0:
        bad("%s must be a non-empty array." % key)
    if min_len is not None and len(value) < min_len:
        bad("%s is too short." % key)
    if max_len is not None and len(value) > max_len:
        bad("%s is too long." % key)
    if element is not None:
        for item in value:
            element(item, key)
    if no_duplicates and len(set(map(_hashable, value))) != len(value):
        bad("%s must not contain duplicate elements." % key)
    return value


def _hashable(value):
    if isinstance(value, (dict, list)):
        return repr(value)
    return value


def el_country(value, key):
    if not isinstance(value, str) or not COUNTRY_RE.match(value):
        bad("%s elements must be two uppercase letters." % key)


def el_policy_code(value, key):
    if not isinstance(value, str) or len(value) < 1 or len(value) > 40:
        bad("%s elements must be policy codes of 1..40 characters." % key)


def el_enum(values):
    def check(value, key):
        if not isinstance(value, str) or value not in values:
            bad("%s elements must be one of %s." % (key, ", ".join(sorted(values))))
    return check


def v_policy_code(data, key):
    value = v_string(data, key, 1, 40)
    if value is None or not CODE_RE.match(value):
        bad("%s must contain only uppercase letters, digits and underscores." % key)
    return value


def v_country(data, key, required=True, default=None):
    if key not in data or data[key] is None:
        if required:
            bad("%s is required." % key)
        return default
    value = data[key]
    if not isinstance(value, str) or not COUNTRY_RE.match(value):
        bad("%s must be exactly two uppercase letters." % key)
    return value


def v_url(data, key, required=True, default=None):
    if key not in data or data[key] is None:
        if required:
            bad("%s is required." % key)
        return default
    value = data[key]
    if not isinstance(value, str):
        bad("%s must be a string." % key)
    if not value.startswith("https://"):
        bad("%s must start with https://." % key)
    remainder = value[len("https://"):]
    host = remainder.split("/", 1)[0]
    if host.strip() == "":
        bad("%s must contain a host segment." % key)
    return value


def v_id(data, key, required=True, default=None):
    if key not in data or data[key] is None:
        if required:
            bad("%s is required." % key)
        return default
    value = data[key]
    if not isinstance(value, str) or value.strip() == "":
        bad("%s must be a non-empty string identifier." % key)
    return value

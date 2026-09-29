"""Body parsing and field validation (PRD section 2.8 step 6).

Every failure in this module is ERR_INVALID_REQUEST (HTTP 400).
"""
from decimal import Decimal, InvalidOperation

from flask import request

import clock
import num
from errors import invalid

_ABSENT = object()


def body_dict():
    """The request body as a dict; an absent or empty body reads as {}."""
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() in (b"", b"null"):
        return {}
    parsed = request.get_json(silent=True, force=True)
    if parsed is None:
        raise invalid("the request body must be a valid JSON object")
    if not isinstance(parsed, dict):
        raise invalid("the request body must be a JSON object")
    return parsed


def _raw(body, name):
    if not isinstance(body, dict):
        raise invalid("the request body must be a JSON object")
    if name not in body:
        return _ABSENT
    value = body[name]
    if value is None:
        return _ABSENT
    return value


def _require_present(value, name, required, default):
    if value is _ABSENT:
        if required:
            raise invalid("'%s' is required" % name)
        return default
    return value


def str_field(body, name, required=True, min_len=1, max_len=None, default=None,
              non_blank=True):
    value = _raw(body, name)
    if value is _ABSENT:
        return _require_present(value, name, required, default)
    if not isinstance(value, str):
        raise invalid("'%s' must be a string" % name)
    if non_blank and value.strip() == "":
        raise invalid("'%s' must not be blank" % name)
    if min_len is not None and len(value) < min_len:
        raise invalid("'%s' must be at least %d characters" % (name, min_len))
    if max_len is not None and len(value) > max_len:
        raise invalid("'%s' must be at most %d characters" % (name, max_len))
    return value


def int_field(body, name, required=True, minimum=None, maximum=None, default=None):
    value = _raw(body, name)
    if value is _ABSENT:
        return _require_present(value, name, required, default)
    if isinstance(value, bool):
        raise invalid("'%s' must be an integer" % name)
    if isinstance(value, int):
        result = value
    else:
        try:
            parsed = num.dec(value)
        except (InvalidOperation, ValueError, ArithmeticError, TypeError):
            raise invalid("'%s' must be an integer" % name)
        if parsed != parsed.to_integral_value():
            raise invalid("'%s' must be an integer" % name)
        result = int(parsed)
    if minimum is not None and result < minimum:
        raise invalid("'%s' must be at least %s" % (name, minimum))
    if maximum is not None and result > maximum:
        raise invalid("'%s' must be at most %s" % (name, maximum))
    return result


def num_field(body, name, required=True, minimum=None, maximum=None, default=None,
              exclusive_minimum=None, places=2):
    """A decimal quantity carried to `places` decimal places, rounded half up."""
    value = _raw(body, name)
    if value is _ABSENT:
        return _require_present(value, name, required, default)
    if isinstance(value, bool):
        raise invalid("'%s' must be a number" % name)
    if not isinstance(value, (int, float, str, Decimal)):
        raise invalid("'%s' must be a number" % name)
    try:
        parsed = num.dec(value)
    except (InvalidOperation, ValueError, ArithmeticError, TypeError):
        raise invalid("'%s' must be a number" % name)
    if not parsed.is_finite():
        raise invalid("'%s' must be a finite number" % name)
    parsed = num.round2(parsed) if places == 2 else num.round4(parsed)
    if exclusive_minimum is not None and parsed <= num.dec(exclusive_minimum):
        raise invalid("'%s' must be greater than %s" % (name, exclusive_minimum))
    if minimum is not None and parsed < num.dec(minimum):
        raise invalid("'%s' must be at least %s" % (name, minimum))
    if maximum is not None and parsed > num.dec(maximum):
        raise invalid("'%s' must be at most %s" % (name, maximum))
    return parsed


def enum_field(body, name, allowed, required=True, default=None):
    value = _raw(body, name)
    if value is _ABSENT:
        return _require_present(value, name, required, default)
    if not isinstance(value, str) or value not in allowed:
        raise invalid("'%s' must be one of %s" % (name, ", ".join(sorted(allowed))))
    return value


def instant_field(body, name, required=True, default=None):
    value = _raw(body, name)
    if value is _ABSENT:
        return _require_present(value, name, required, default)
    if not isinstance(value, str):
        raise invalid("'%s' must be an ISO 8601 timestamp string" % name)
    parsed = clock.parse_instant(value)
    if parsed is None:
        raise invalid("'%s' must be a valid ISO 8601 timestamp" % name)
    return parsed


def id_field(body, name, required=True, default=None):
    value = _raw(body, name)
    if value is _ABSENT:
        return _require_present(value, name, required, default)
    if not isinstance(value, str) or value.strip() == "":
        raise invalid("'%s' must be a non-empty identifier string" % name)
    return value


def version_field(body, name):
    """A required optimistic-concurrency stamp (PRD section 2.5)."""
    return int_field(body, name, required=True, minimum=0)


def year_field(body, name, required=True, default=None):
    return int_field(body, name, required=required, minimum=1900, maximum=2100,
                     default=default)


# ---------------------------------------------------------------------------
# Query-string filters
# ---------------------------------------------------------------------------
def q_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def q_enum(name, allowed):
    value = q_str(name)
    if value is None:
        return None
    if value not in allowed:
        raise invalid("'%s' must be one of %s" % (name, ", ".join(sorted(allowed))))
    return value


def q_int(name, minimum=None, maximum=None):
    value = q_str(name)
    if value is None:
        return None
    try:
        parsed = num.dec(value)
    except (InvalidOperation, ValueError, ArithmeticError, TypeError):
        raise invalid("'%s' must be an integer" % name)
    if parsed != parsed.to_integral_value():
        raise invalid("'%s' must be an integer" % name)
    result = int(parsed)
    if minimum is not None and result < minimum:
        raise invalid("'%s' must be at least %s" % (name, minimum))
    if maximum is not None and result > maximum:
        raise invalid("'%s' must be at most %s" % (name, maximum))
    return result


def q_num(name):
    value = q_str(name)
    if value is None:
        return None
    try:
        return num.round2(num.dec(value))
    except (InvalidOperation, ValueError, ArithmeticError, TypeError):
        raise invalid("'%s' must be a number" % name)

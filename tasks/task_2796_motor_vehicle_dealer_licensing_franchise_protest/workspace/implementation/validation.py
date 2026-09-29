"""Request-body validity checks -- stage 5 of the precedence pipeline (PRD 2.10)."""

import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError

_MISSING = object()


def _bad(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def read_body():
    """Parse the JSON body leniently. An absent body is an empty object."""
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        raise _bad("Request body is not valid JSON")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise _bad("Request body must be a JSON object")
    return parsed


def peek_body():
    """Body for pre-validity ownership scoping; never raises on shape."""
    try:
        parsed = request.get_json(force=True, silent=True)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _present(body, name):
    return name in body and body[name] is not None


def opt_present(body, name):
    return _present(body, name)


def req_string(body, name, min_len=1, max_len=None, pattern=None):
    if not _present(body, name):
        raise _bad("%s is required" % name)
    return _string_value(body[name], name, min_len, max_len, pattern)


def opt_string(body, name, min_len=1, max_len=None, pattern=None, default=None):
    if not _present(body, name):
        return default
    return _string_value(body[name], name, min_len, max_len, pattern)


def _string_value(value, name, min_len, max_len, pattern):
    if not isinstance(value, str):
        raise _bad("%s must be a string" % name)
    if min_len is not None and len(value) < min_len:
        raise _bad("%s is shorter than %d characters" % (name, min_len))
    if max_len is not None and len(value) > max_len:
        raise _bad("%s is longer than %d characters" % (name, max_len))
    if pattern is not None and re.match(pattern, value) is None:
        raise _bad("%s does not match the required pattern" % name)
    return value


def req_enum(body, name, allowed):
    if not _present(body, name):
        raise _bad("%s is required" % name)
    return _enum_value(body[name], name, allowed)


def opt_enum(body, name, allowed, default=None):
    if not _present(body, name):
        return default
    return _enum_value(body[name], name, allowed)


def _enum_value(value, name, allowed):
    if not isinstance(value, str):
        raise _bad("%s must be a string" % name)
    if value not in allowed:
        raise _bad("%s must be one of %s" % (name, ", ".join(sorted(allowed))))
    return value


def req_int(body, name, minimum=None, maximum=None):
    if not _present(body, name):
        raise _bad("%s is required" % name)
    return _int_value(body[name], name, minimum, maximum)


def opt_int(body, name, minimum=None, maximum=None, default=None):
    if not _present(body, name):
        return default
    return _int_value(body[name], name, minimum, maximum)


def _int_value(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        raise _bad("%s must be an integer" % name)
    if minimum is not None and value < minimum:
        raise _bad("%s must be at least %d" % (name, minimum))
    if maximum is not None and value > maximum:
        raise _bad("%s must be at most %d" % (name, maximum))
    return value


def req_bool(body, name):
    if not _present(body, name):
        raise _bad("%s is required" % name)
    return _bool_value(body[name], name)


def opt_bool(body, name, default=None):
    if not _present(body, name):
        return default
    return _bool_value(body[name], name)


def _bool_value(value, name):
    if not isinstance(value, bool):
        raise _bad("%s must be a boolean" % name)
    return value


def req_decimal(body, name, minimum=None, maximum=None, places=2, exclusive_min=None):
    if not _present(body, name):
        raise _bad("%s is required" % name)
    return _decimal_value(body[name], name, minimum, maximum, places, exclusive_min)


def opt_decimal(body, name, minimum=None, maximum=None, places=2, default=None, exclusive_min=None):
    if not _present(body, name):
        return default
    return _decimal_value(body[name], name, minimum, maximum, places, exclusive_min)


def _decimal_value(value, name, minimum, maximum, places, exclusive_min):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _bad("%s must be a number" % name)
    try:
        parsed = Decimal(repr(value)) if isinstance(value, float) else Decimal(value)
    except (InvalidOperation, ValueError):
        raise _bad("%s must be a number" % name)
    exponent = parsed.as_tuple().exponent
    if places is not None and isinstance(exponent, int) and exponent < -places:
        raise _bad("%s carries more than %d decimal places" % (name, places))
    if minimum is not None and parsed < Decimal(str(minimum)):
        raise _bad("%s must be at least %s" % (name, minimum))
    if exclusive_min is not None and parsed <= Decimal(str(exclusive_min)):
        raise _bad("%s must be greater than %s" % (name, exclusive_min))
    if maximum is not None and parsed > Decimal(str(maximum)):
        raise _bad("%s must be at most %s" % (name, maximum))
    return parsed


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def req_date(body, name):
    if not _present(body, name):
        raise _bad("%s is required" % name)
    return _date_value(body[name], name)


def opt_date(body, name, default=None):
    if not _present(body, name):
        return default
    return _date_value(body[name], name)


def _date_value(value, name):
    if not isinstance(value, str) or _DATE_RE.match(value) is None:
        raise _bad("%s must be an ISO 8601 calendar date (YYYY-MM-DD)" % name)
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        raise _bad("%s is not a real calendar date" % name)


def req_instant(body, name):
    if not _present(body, name):
        raise _bad("%s is required" % name)
    return _instant_value(body[name], name)


def opt_instant(body, name, default=None):
    if not _present(body, name):
        return default
    return _instant_value(body[name], name)


def _instant_value(value, name):
    if not isinstance(value, str) or value.strip() == "":
        raise _bad("%s must be an ISO 8601 UTC instant" % name)
    text = value.strip()
    normalised = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalised)
    except ValueError:
        raise _bad("%s must be an ISO 8601 UTC instant" % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def req_list(body, name, min_len=1, max_len=None):
    if not _present(body, name):
        raise _bad("%s is required" % name)
    return _list_value(body[name], name, min_len, max_len)


def opt_list(body, name, min_len=0, max_len=None, default=None):
    if not _present(body, name):
        return default
    return _list_value(body[name], name, min_len, max_len)


def _list_value(value, name, min_len, max_len):
    if not isinstance(value, list):
        raise _bad("%s must be an array" % name)
    if min_len is not None and len(value) < min_len:
        raise _bad("%s must carry at least %d element(s)" % (name, min_len))
    if max_len is not None and len(value) > max_len:
        raise _bad("%s must carry at most %d element(s)" % (name, max_len))
    return value


def query_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in allowed:
        raise _bad("%s must be one of %s" % (name, ", ".join(sorted(allowed))))
    return raw


def query_string(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw

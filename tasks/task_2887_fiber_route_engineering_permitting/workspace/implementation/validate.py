"""Body-shape validation (PRD section 2.9 priority 3).

Every check in this module reports ERR_INVALID_REQUEST / HTTP 400.  Shape is
evaluated before path-parameter existence and before body foreign-key
existence, per the normative precedence ordering.
"""

import json
import re
from datetime import datetime, date

from flask import request

from errors import ApiError

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INSTANT_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(\.\d{1,6})?Z$")

_SENTINEL = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        bad("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        bad("Request body must be a JSON object.")
    return parsed


def no_unknown(payload, allowed):
    for key in payload.keys():
        if key not in allowed:
            bad("Unknown body field '%s'." % key)


def check_body(payload, allowed):
    """Reject unknown body fields; `allowed` is the declared input field set."""
    no_unknown(payload, allowed)


def _present(payload, name):
    return name in payload and payload[name] is not None


# --------------------------------------------------------------------------
# scalars
# --------------------------------------------------------------------------

def req_str(payload, name, min_len=1, max_len=None):
    if name not in payload:
        bad("Missing required field '%s'." % name)
    value = payload[name]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % name)
    if len(value.strip()) < min_len:
        bad("Field '%s' must not be blank." % name)
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' must be at most %d characters." % (name, max_len))
    return value


def opt_str(payload, name, default=None):
    if not _present(payload, name):
        return default
    value = payload[name]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % name)
    return value


def req_nonblank_str(payload, name):
    return req_str(payload, name, min_len=1)


def req_int(payload, name, minimum=None, maximum=None):
    if name not in payload:
        bad("Missing required field '%s'." % name)
    return _as_int(payload[name], name, minimum, maximum)


def opt_int(payload, name, default=None, minimum=None, maximum=None):
    if not _present(payload, name):
        return default
    return _as_int(payload[name], name, minimum, maximum)


def _as_int(value, name, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be at most %d." % (name, maximum))
    return value


def req_bool(payload, name):
    if name not in payload:
        bad("Missing required field '%s'." % name)
    value = payload[name]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % name)
    return value


def opt_bool(payload, name, default=False):
    if not _present(payload, name):
        return default
    value = payload[name]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % name)
    return value


def req_enum(payload, name, allowed):
    if name not in payload:
        bad("Missing required field '%s'." % name)
    value = payload[name]
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def opt_enum(payload, name, allowed, default=None):
    if not _present(payload, name):
        return default
    value = payload[name]
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def req_int_in(payload, name, allowed):
    value = req_int(payload, name)
    if value not in allowed:
        bad("Field '%s' must be one of %s." % (name, ", ".join(str(v) for v in sorted(allowed))))
    return value


# --------------------------------------------------------------------------
# calendar dates and instants
# --------------------------------------------------------------------------

def parse_date(value, name):
    if not isinstance(value, str) or not DATE_RE.match(value):
        bad("Field '%s' must be a calendar date of the form YYYY-MM-DD." % name)
    try:
        parts = [int(p) for p in value.split("-")]
        date(parts[0], parts[1], parts[2])
    except Exception:
        bad("Field '%s' must be a calendar date of the form YYYY-MM-DD." % name)
    return value


def req_date(payload, name):
    if name not in payload:
        bad("Missing required field '%s'." % name)
    return parse_date(payload[name], name)


def opt_date(payload, name, default=None):
    if not _present(payload, name):
        return default
    return parse_date(payload[name], name)


def req_instant(payload, name):
    if name not in payload:
        bad("Missing required field '%s'." % name)
    value = payload[name]
    if not isinstance(value, str):
        bad("Field '%s' must be an ISO 8601 UTC instant." % name)
    match = INSTANT_RE.match(value)
    if not match:
        bad("Field '%s' must be an ISO 8601 UTC instant such as 2026-09-24T00:00:00Z." % name)
    try:
        parsed = datetime(
            int(match.group(1)), int(match.group(2)), int(match.group(3)),
            int(match.group(4)), int(match.group(5)), int(match.group(6)),
        )
    except Exception:
        bad("Field '%s' must be an ISO 8601 UTC instant such as 2026-09-24T00:00:00Z." % name)
    return parsed


def req_id(payload, name):
    if name not in payload:
        bad("Missing required field '%s'." % name)
    value = payload[name]
    if not isinstance(value, str) or value.strip() == "":
        bad("Field '%s' must be a non-blank identifier string." % name)
    return value


def opt_id(payload, name, default=None):
    if not _present(payload, name):
        return default
    value = payload[name]
    if not isinstance(value, str) or value.strip() == "":
        bad("Field '%s' must be a non-blank identifier string." % name)
    return value


def order_dates(earlier, later, earlier_name, later_name):
    if later < earlier:
        bad("Field '%s' must fall on or after '%s'." % (later_name, earlier_name))


def is_blank(value):
    return value is None or not isinstance(value, str) or value.strip() == ""

"""Request-body shape validation -- PRD section 2.9 check 5 (ERR_VALIDATION, 400)."""

import re
import uuid
from datetime import date, datetime, timezone

from flask import request

from errors import ApiError

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


def bad(message):
    raise ApiError("ERR_VALIDATION", message)


def body():
    """The JSON body as a dict; a missing body is treated as an empty object."""
    if not request.data:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        bad("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        bad("Request body must be a JSON object.")
    return parsed


def is_uuid(value):
    if not isinstance(value, str):
        return False
    try:
        uuid.UUID(value.strip())
    except Exception:
        return False
    return True


def path_uuid(value):
    """A malformed identifier is a request-shape failure (PRD section 2.4)."""
    if not is_uuid(value):
        bad("Identifier '%s' is not a well-formed UUID." % value)
    return value


def opt_present(data, field):
    return field in data and data[field] is not None


def req_id(data, field, required=True):
    if field not in data or data[field] is None:
        if required:
            bad("Field '%s' is required." % field)
        return None
    value = data[field]
    if not isinstance(value, str):
        bad("Field '%s' must be a string identifier." % field)
    if not is_uuid(value):
        bad("Field '%s' is not a well-formed UUID." % field)
    return value


def req_str(data, field, required=True, min_len=None, max_len=None):
    if field not in data or data[field] is None:
        if required:
            bad("Field '%s' is required." % field)
        return None
    value = data[field]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % field)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' must be at least %d characters." % (field, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' may be at most %d characters." % (field, max_len))
    return value


def req_int(data, field, required=True, minimum=None, maximum=None):
    if field not in data or data[field] is None:
        if required:
            bad("Field '%s' is required." % field)
        return None
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        bad("Field '%s' may not be below %d." % (field, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' may not exceed %d." % (field, maximum))
    return value


def req_cents(data, field, required=True, maximum=None):
    """Any *_cents field is an integer of at least zero; the single declared
    exception is an attrition event's signed mrr_delta_cents."""
    return req_int(data, field, required=required, minimum=0, maximum=maximum)


def req_enum(data, field, allowed, required=True):
    if field not in data or data[field] is None:
        if required:
            bad("Field '%s' is required." % field)
        return None
    value = data[field]
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (field, ", ".join(sorted(allowed))))
    return value


def req_bool(data, field, required=True):
    if field not in data or data[field] is None:
        if required:
            bad("Field '%s' is required." % field)
        return None
    value = data[field]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % field)
    return value


def req_date(data, field, required=True):
    if field not in data or data[field] is None:
        if required:
            bad("Field '%s' is required." % field)
        return None
    value = data[field]
    if not isinstance(value, str) or not _DATE_RE.match(value):
        bad("Field '%s' must be a YYYY-MM-DD date." % field)
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        bad("Field '%s' must be a YYYY-MM-DD date." % field)


def req_month(data, field, required=True):
    if field not in data or data[field] is None:
        if required:
            bad("Field '%s' is required." % field)
        return None
    value = data[field]
    if not isinstance(value, str) or not _MONTH_RE.match(value):
        bad("Field '%s' must be a YYYY-MM month label." % field)
    month = int(value[5:7])
    if month < 1 or month > 12:
        bad("Field '%s' must be a YYYY-MM month label." % field)
    return value


def req_instant(data, field, required=True):
    if field not in data or data[field] is None:
        if required:
            bad("Field '%s' is required." % field)
        return None
    value = data[field]
    if not isinstance(value, str):
        bad("Field '%s' must be an ISO 8601 UTC instant." % field)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        bad("Field '%s' must be an ISO 8601 UTC instant." % field)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def req_str_array(data, field, required=True, item_pattern=None, min_items=0,
                  allowed=None, unique=False):
    if field not in data or data[field] is None:
        if required:
            bad("Field '%s' is required." % field)
        return None
    value = data[field]
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % field)
    if len(value) < min_items:
        bad("Field '%s' must hold at least %d entries." % (field, min_items))
    for item in value:
        if not isinstance(item, str):
            bad("Every entry of '%s' must be a string." % field)
        if item_pattern is not None and not re.match(item_pattern, item):
            bad("Entry '%s' of '%s' is not well formed." % (item, field))
        if allowed is not None and item not in allowed:
            bad("Entry '%s' of '%s' is outside the declared set." % (item, field))
    if unique and len(set(value)) != len(value):
        bad("Field '%s' may not repeat an entry." % field)
    return value

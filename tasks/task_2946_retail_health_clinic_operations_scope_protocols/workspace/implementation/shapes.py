"""Request-shape validation (PRD 2.5 rung 5 -> ERR_VALIDATION / 400)."""

import re
from datetime import datetime, timezone

from flask import request

from errors import ERR_VALIDATION, raise_error

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_STATE_RE = re.compile(r"^[A-Z]{2}$")
_NPI_RE = re.compile(r"^\d{10}$")

MISSING = object()


def bad(message):
    raise_error(ERR_VALIDATION, message)


def json_body(required=False):
    """Return the request body as a dict, or {} when absent."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        if required:
            bad("A JSON request body is required.")
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        bad("The request body is not valid JSON.")
    if parsed is None:
        if required:
            bad("A JSON request body is required.")
        return {}
    if not isinstance(parsed, dict):
        bad("The request body must be a JSON object.")
    return parsed


def reject_unknown(body, allowed):
    for key in body.keys():
        if key not in allowed:
            bad("Unknown field '%s'." % key)


def present(body, name):
    return name in body and body[name] is not None


# --- scalar readers ---------------------------------------------------------

def _get(body, name, required):
    if name not in body or body[name] is None:
        if required:
            bad("Field '%s' is required." % name)
        return MISSING
    return body[name]


def read_string(body, name, required=True, non_empty=True):
    value = _get(body, name, required)
    if value is MISSING:
        return None
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % name)
    if non_empty and value.strip() == "":
        bad("Field '%s' must not be empty." % name)
    return value


def read_int(body, name, required=True, minimum=None, maximum=None):
    value = _get(body, name, required)
    if value is MISSING:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be <= %s." % (name, maximum))
    return value


def read_number(body, name, required=True, minimum=None, maximum=None):
    value = _get(body, name, required)
    if value is MISSING:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be a number." % name)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be <= %s." % (name, maximum))
    return value


def read_bool(body, name, required=True, default=None):
    value = _get(body, name, required)
    if value is MISSING:
        return default
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % name)
    return value


def read_enum(body, name, allowed, required=True):
    value = _get(body, name, required)
    if value is MISSING:
        return None
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (name, sorted(allowed)))
    return value


def read_string_array(body, name, required=True, default=None, non_empty=False):
    value = _get(body, name, required)
    if value is MISSING:
        return default if default is not None else None
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % name)
    for item in value:
        if not isinstance(item, str):
            bad("Field '%s' must be an array of strings." % name)
    if non_empty and len(value) == 0:
        bad("Field '%s' must not be empty." % name)
    return list(value)


def read_enum_array(body, name, allowed, required=True, default=None,
                    non_empty=False):
    value = read_string_array(body, name, required=required, default=None,
                              non_empty=non_empty)
    if value is None:
        return default if default is not None else None
    for item in value:
        if item not in allowed:
            bad("Field '%s' contains an invalid member '%s'." % (name, item))
    return value


def read_state_code(body, name, required=True):
    value = read_string(body, name, required=required)
    if value is None:
        return None
    if not _STATE_RE.match(value):
        bad("Field '%s' must be exactly two uppercase letters." % name)
    return value


def read_state_code_array(body, name, required=True, non_empty=True):
    value = read_string_array(body, name, required=required,
                              non_empty=non_empty)
    if value is None:
        return None
    for item in value:
        if not _STATE_RE.match(item):
            bad("Field '%s' must contain two-letter uppercase state codes."
                % name)
    return value


def read_npi(body, name, required=True):
    value = read_string(body, name, required=required)
    if value is None:
        return None
    if not _NPI_RE.match(value):
        bad("Field '%s' must be exactly ten digits." % name)
    return value


def parse_instant_string(text, name):
    if not isinstance(text, str):
        bad("Field '%s' must be an ISO 8601 UTC instant." % name)
    raw = text.strip()
    candidate = raw
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except Exception:
        bad("Field '%s' must be an ISO 8601 UTC instant." % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def read_instant(body, name, required=True):
    value = _get(body, name, required)
    if value is MISSING:
        return None
    return parse_instant_string(value, name)


def read_date(body, name, required=True):
    value = read_string(body, name, required=required)
    if value is None:
        return None
    if not _DATE_RE.match(value):
        bad("Field '%s' must be an ISO calendar date (YYYY-MM-DD)." % name)
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except Exception:
        bad("Field '%s' must be a real calendar date." % name)
    return value


# --- query parameters -------------------------------------------------------

def read_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        if raw is None or not re.match(r"^-?\d+$", raw.strip()):
            bad("Query parameter 'limit' must be an integer.")
        limit = int(raw.strip())
        if limit < 1 or limit > 100:
            bad("Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        if raw is None or not re.match(r"^-?\d+$", raw.strip()):
            bad("Query parameter 'offset' must be an integer.")
        offset = int(raw.strip())
        if offset < 0:
            bad("Query parameter 'offset' must be 0 or greater.")
    return limit, offset


def query_string(name):
    if name not in request.args:
        return None
    return request.args.get(name)


def query_enum(name, allowed):
    value = query_string(name)
    if value is None:
        return None
    if value not in allowed:
        bad("Query parameter '%s' must be one of %s." % (name, sorted(allowed)))
    return value


def query_bool(name):
    value = query_string(name)
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    bad("Query parameter '%s' must be a boolean." % name)

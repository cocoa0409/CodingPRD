"""Request-shape validation helpers (PRD 2.6 priority 2 -> ERR_VALIDATION 400).

Everything here runs before role authorization, existence, ownership, or any
state/business check. Also houses the shared enum tables and pagination
parsing.
"""

from datetime import datetime
from decimal import Decimal

from flask import request

from clock import parse_iso, fmt_iso
from errors import api_error

GOV_TYPES = ("CITY", "COUNTY", "STATE_GOV", "SPECIAL_DISTRICT")
POP_BANDS = ("SMALL", "MEDIUM", "LARGE")
PROGRAM_TYPES = ("FINANCIAL_REPORTING", "BUDGET_PRESENTATION")
DOC_TYPES = ("POLICY", "FINANCIAL_PLAN", "COMMUNICATION")
SEVERITIES = ("MAJOR", "MINOR")
REVIEWER_STATUSES = ("APPLICANT", "TRAINED", "ELIGIBLE", "SUSPENDED", "RETIRED")
RESOLUTIONS = ("ACCEPTED", "REVISED", "REJECTED")
PROGRAM_LABELS = ("SCHOLARSHIP", "TECHNICAL_ASSISTANCE")
PURPOSES = ("CONFERENCE_SCHOLARSHIP", "TECHNICAL_ASSISTANCE")
ALLOCATION_POLICIES = ("FLAT_CAP", "PRO_RATA")


def _err(msg):
    raise api_error("ERR_VALIDATION", msg)


def get_body():
    """Parse the JSON body leniently; absent body means {} (many actions take
    no input). A present-but-malformed or non-object body is ERR_VALIDATION."""
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        _err("request body is not valid JSON")
    if not isinstance(data, dict):
        _err("request body must be a JSON object")
    return data


def _present(body, name):
    return name in body and body[name] is not None


def req_str(body, name):
    if not _present(body, name) or not isinstance(body[name], str):
        _err("field '%s' is required and must be a string" % name)
    return body[name]


def opt_str(body, name, default=None):
    if not _present(body, name):
        return default
    if not isinstance(body[name], str):
        _err("field '%s' must be a string" % name)
    return body[name]


def req_enum(body, name, allowed):
    value = req_str(body, name)
    if value not in allowed:
        _err("field '%s' must be one of %s" % (name, ", ".join(allowed)))
    return value


def opt_enum(body, name, allowed, default=None):
    if not _present(body, name):
        return default
    return req_enum(body, name, allowed)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_int(body, name):
    if not _present(body, name) or not _is_int(body[name]):
        _err("field '%s' is required and must be an integer" % name)
    return body[name]


def req_pos_int(body, name):
    value = req_int(body, name)
    if value <= 0:
        _err("field '%s' must be positive" % name)
    return value


def opt_bool(body, name, default=False):
    if not _present(body, name):
        return default
    if not isinstance(body[name], bool):
        _err("field '%s' must be a boolean" % name)
    return body[name]


def req_list(body, name):
    if not _present(body, name) or not isinstance(body[name], list):
        _err("field '%s' is required and must be a list" % name)
    return body[name]


def opt_list(body, name):
    if not _present(body, name):
        return []
    if not isinstance(body[name], list):
        _err("field '%s' must be a list" % name)
    return body[name]


def req_str_list(body, name):
    values = req_list(body, name)
    for v in values:
        if not isinstance(v, str):
            _err("field '%s' must be a list of strings" % name)
    return values


def opt_str_list(body, name):
    if not _present(body, name):
        return []
    return req_str_list(body, name)


def to_decimal(value, field_desc):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _err("%s must be a number" % field_desc)
    try:
        return Decimal(str(value))
    except Exception:
        _err("%s must be a number" % field_desc)


def req_number(body, name):
    if not _present(body, name):
        _err("field '%s' is required and must be a number" % name)
    return to_decimal(body[name], "field '%s'" % name)


def score_decimal(value):
    """Per-criterion score: 0..100 inclusive, at most 2 decimal places (PRD 2.9)."""
    d = to_decimal(value, "criterion score")
    if d < 0 or d > 100:
        _err("criterion score must lie between 0 and 100 inclusive")
    if -d.as_tuple().exponent > 2:
        _err("criterion score must carry at most 2 decimal places")
    return d


def req_datetime(body, name):
    """Required ISO 8601 datetime; stored canonically with 3 fractional digits."""
    raw = req_str(body, name)
    try:
        return fmt_iso(parse_iso(raw))
    except ValueError:
        _err("field '%s' must be an ISO 8601 datetime" % name)


def opt_datetime(body, name, default=None):
    if not _present(body, name):
        return default
    return req_datetime(body, name)


def parse_date(value, field_desc):
    """Unavailability-window dates: YYYY-MM-DD calendar dates."""
    if not isinstance(value, str):
        _err("%s must be a YYYY-MM-DD date string" % field_desc)
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        _err("%s must be a YYYY-MM-DD date string" % field_desc)


def pagination():
    """limit/offset query params; defaults 10/0, limit clamped to [1, 100]."""
    args = request.args

    def _int_or(value, default):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    limit = _int_or(args.get("limit"), 10)
    offset = _int_or(args.get("offset"), 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def query_filter(name):
    return request.args.get(name)

"""Authentication, authorization, request-shape and pagination validation.

Precedence follows PRD section 2.5 exactly: authentication, authorization,
role identity, request shape, pagination shape, path existence, body
reference existence, ownership, optimistic concurrency, then the business
bands 11 through 17.
"""
import re

from flask import request

from core import (
    D,
    db,
    fail,
    parse_date,
    parse_instant,
)

ROLES = (
    "DocsLead",
    "Writer",
    "Reviewer",
    "LocalizationCoordinator",
    "SupportAnalyst",
    "Reader",
)


class Caller(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role
        self.writer = None
        self.reviewer = None


def authenticate(allowed_roles):
    """Bands 1-3 of PRD section 2.5."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id == "" or role is None or role == "":
        fail("ERR_UNAUTHENTICATED", "Both X-User-ID and X-User-Role headers are required.")
    if role not in ROLES:
        fail("ERR_UNAUTHORIZED", "Role '%s' is not recognized." % role)
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "Role '%s' may not call this endpoint." % role)
    caller = Caller(user_id, role)
    if role == "Writer":
        caller.writer = db.writers.get(user_id)
        if caller.writer is None:
            fail("ERR_ROLE_IDENTITY_MISMATCH",
                 "X-User-ID does not resolve to a writer record.")
    elif role == "Reviewer":
        caller.reviewer = db.reviewers.get(user_id)
        if caller.reviewer is None:
            fail("ERR_ROLE_IDENTITY_MISMATCH",
                 "X-User-ID does not resolve to a reviewer record.")
    return caller


# ---------------------------------------------------------------------------
# Band 4: request shape
# ---------------------------------------------------------------------------
def bad(message):
    fail("ERR_INVALID_REQUEST", message)


def body():
    """Parsed JSON object body; malformed or non-object bodies are shape errors."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        bad("Request body is not valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        bad("Request body must be a JSON object.")
    return payload


def present(data, name):
    return name in data and data[name] is not None


def _require(data, name, required):
    if not present(data, name):
        if required:
            bad("Field '%s' is required." % name)
        return False
    return True


def v_str(data, name, min_len, max_len, required=True, charset=None, lower=False):
    if not _require(data, name, required):
        return None
    value = data[name]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % name)
    if len(value) < min_len or len(value) > max_len:
        bad("Field '%s' must be between %d and %d characters." % (name, min_len, max_len))
    if charset is not None and not re.match(charset, value):
        bad("Field '%s' has an invalid format." % name)
    if lower and value != value.lower():
        bad("Field '%s' must be lowercase." % name)
    return value


def v_id(data, name, required=True):
    if not _require(data, name, required):
        return None
    value = data[name]
    if not isinstance(value, str) or value == "":
        bad("Field '%s' must be a non-empty string identifier." % name)
    return value


def v_int(data, name, low=None, high=None, required=True):
    if not _require(data, name, required):
        return None
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % name)
    if low is not None and value < low:
        bad("Field '%s' must be at least %d." % (name, low))
    if high is not None and value > high:
        bad("Field '%s' must be at most %d." % (name, high))
    return value


def v_num(data, name, low=None, high=None, required=True, exclusive_low=False):
    if not _require(data, name, required):
        return None
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be a number." % name)
    number = D(value)
    if low is not None:
        if exclusive_low and number <= D(low):
            bad("Field '%s' must be greater than %s." % (name, low))
        if not exclusive_low and number < D(low):
            bad("Field '%s' must be at least %s." % (name, low))
    if high is not None and number > D(high):
        bad("Field '%s' must be at most %s." % (name, high))
    return number


def v_enum(data, name, choices, required=True):
    if not _require(data, name, required):
        return None
    value = data[name]
    if not isinstance(value, str) or value not in choices:
        bad("Field '%s' must be one of: %s." % (name, ", ".join(choices)))
    return value


def v_date(data, name, required=True):
    if not _require(data, name, required):
        return None
    value = data[name]
    if not isinstance(value, str):
        bad("Field '%s' must be a YYYY-MM-DD calendar date." % name)
    parsed = parse_date(value)
    if parsed is None:
        bad("Field '%s' must be a YYYY-MM-DD calendar date." % name)
    return parsed


def v_instant(data, name, required=True):
    if not _require(data, name, required):
        return None
    value = data[name]
    if not isinstance(value, str):
        bad("Field '%s' must be an ISO 8601 UTC instant ending in Z." % name)
    parsed = parse_instant(value)
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 UTC instant ending in Z." % name)
    return parsed


def v_str_array(data, name, min_items, max_items, item_min, item_max, required=True):
    if not _require(data, name, required):
        return None
    value = data[name]
    if not isinstance(value, list):
        bad("Field '%s' must be an array of strings." % name)
    if len(value) < min_items or len(value) > max_items:
        bad("Field '%s' must contain between %d and %d entries." % (name, min_items, max_items))
    for entry in value:
        if not isinstance(entry, str):
            bad("Field '%s' must contain only strings." % name)
        if len(entry) < item_min or len(entry) > item_max:
            bad("Entries of '%s' must be between %d and %d characters." % (name, item_min, item_max))
    return list(value)


# ---------------------------------------------------------------------------
# Band 5: pagination shape
# ---------------------------------------------------------------------------
INT_RE = re.compile(r"^[+-]?\d+$")


def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        if not INT_RE.match(raw_limit.strip()):
            fail("ERR_INVALID_PAGINATION", "limit must be an integer.")
        limit = int(raw_limit.strip())
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_PAGINATION", "limit must be between 1 and 100.")
    if raw_offset is not None:
        if not INT_RE.match(raw_offset.strip()):
            fail("ERR_INVALID_PAGINATION", "offset must be an integer.")
        offset = int(raw_offset.strip())
        if offset < 0:
            fail("ERR_INVALID_PAGINATION", "offset may not be negative.")
    return limit, offset


def filters(*names):
    return {name: request.args.get(name) for name in names}

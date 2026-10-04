# inputs.py — request body access and tiered input helpers.
#
# Tier placement (PRD §2.6): foreign-key *existence* resolves at tier 3, so a
# present, string-typed id is looked up early; a missing or mistyped id cannot
# be resolved and is deferred to tier 10, where ERR_INVALID_REQUEST (missing
# field / wrong type / invalid enum) is raised. Checkers for tiers 5-9 simply
# skip any check whose inputs are not yet known-valid.
import re

from flask import request

from errors import ApiError
from timeutil import parse_iso

LANG_RE = re.compile(r"^[a-z]{3}$")


def get_body():
    """Return the JSON object body; anything else behaves as an empty object
    (unknown/malformed bodies are reported at tier 10 as ERR_INVALID_REQUEST).
    Unknown body fields are ignored, never rejected (PRD §2.1/§2.6)."""
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return {}


def invalid(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def fk(body, name):
    """Tier-3 view of a foreign-key field: the string value, else None."""
    v = body.get(name)
    return v if isinstance(v, str) else None


# --------------------------------------------------------------------------
# Tier-10 shape validators (raise ERR_INVALID_REQUEST, HTTP 400)
# --------------------------------------------------------------------------

def req_str(body, name):
    v = body.get(name)
    if not isinstance(v, str):
        invalid("field '%s' is required and must be a string" % name)
    return v


def opt_str(body, name):
    v = body.get(name)
    if v is None:
        return None
    if not isinstance(v, str):
        invalid("field '%s' must be a string" % name)
    return v


def req_int(body, name, min_v=None, max_v=None):
    v = body.get(name)
    if not is_int(v):
        invalid("field '%s' is required and must be an integer" % name)
    if min_v is not None and v < min_v:
        invalid("field '%s' must be >= %d" % (name, min_v))
    if max_v is not None and v > max_v:
        invalid("field '%s' must be <= %d" % (name, max_v))
    return v


def opt_bool(body, name, default=None):
    v = body.get(name)
    if v is None:
        return default
    if not isinstance(v, bool):
        invalid("field '%s' must be a boolean" % name)
    return v


def req_enum(body, name, allowed):
    v = body.get(name)
    if not isinstance(v, str) or v not in allowed:
        invalid("field '%s' must be one of %s" % (name, list(allowed)))
    return v


def req_lang(body, name):
    v = body.get(name)
    if not isinstance(v, str) or not LANG_RE.match(v):
        invalid("field '%s' must be an ISO 639-2/T lowercase 3-letter code"
                % name)
    return v


def req_lang_list(body, name):
    v = body.get(name)
    if (not isinstance(v, list) or len(v) == 0
            or any(not isinstance(x, str) or not LANG_RE.match(x) for x in v)):
        invalid("field '%s' must be a non-empty array of ISO 639-2/T "
                "lowercase 3-letter codes" % name)
    return v


def req_datetime(body, name):
    v = body.get(name)
    dt = parse_iso(v)
    if dt is None:
        invalid("field '%s' is required and must be an ISO 8601 timestamp"
                % name)
    return dt


def req_version(body, name="expected_case_version"):
    v = body.get(name)
    if not is_int(v):
        invalid("field '%s' is required and must be an integer" % name)
    return v


# --------------------------------------------------------------------------
# Pagination query parameters (PRD §2.3)
# --------------------------------------------------------------------------

def pagination_params():
    from constants import (PAGE_DEFAULT_LIMIT, PAGE_MIN_LIMIT, PAGE_MAX_LIMIT,
                           PAGE_DEFAULT_OFFSET)
    limit = PAGE_DEFAULT_LIMIT
    offset = PAGE_DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            invalid("query parameter 'limit' must be an integer")
        if limit < PAGE_MIN_LIMIT or limit > PAGE_MAX_LIMIT:
            invalid("query parameter 'limit' must be between %d and %d"
                    % (PAGE_MIN_LIMIT, PAGE_MAX_LIMIT))
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            invalid("query parameter 'offset' must be an integer")
        if offset < 0:
            invalid("query parameter 'offset' must be >= 0")
    return limit, offset


def filter_param(name):
    """Exact-match list filter; unknown values simply match nothing."""
    return request.args.get(name)


def sorted_page(records, limit, offset):
    """All lists sort by created_at ascending (PRD §2.3); _seq is the stable
    secondary order for same-instant creations under the logical clock."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    return ordered[offset:offset + limit], len(ordered)

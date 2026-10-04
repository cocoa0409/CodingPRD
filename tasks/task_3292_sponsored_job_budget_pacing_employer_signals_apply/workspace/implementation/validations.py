"""Tier-3 existence resolution, request shape checks, pagination and filter parsing.

Guard order follows PRD 2.8: auth -> ownership -> existence -> state -> fraud ->
constraint -> clock -> fiscal -> referential -> concurrency -> shape.
"""

from flask import request

import errors as E
from db import store

NOT_FOUND = {
    "employer": E.ERR_EMPLOYER_NOT_FOUND,
    "job_seeker": E.ERR_JOB_SEEKER_NOT_FOUND,
    "campaign": E.ERR_CAMPAIGN_NOT_FOUND,
    "sponsored_job": E.ERR_SPONSORED_JOB_NOT_FOUND,
    "job_posting": E.ERR_JOB_POSTING_NOT_FOUND,
    "application": E.ERR_APPLICATION_NOT_FOUND,
    "assessment": E.ERR_ASSESSMENT_NOT_FOUND,
    "sponsor_event": E.ERR_SPONSOR_EVENT_NOT_FOUND,
}

TABLES = {
    "employer": "employers",
    "job_seeker": "job_seekers",
    "campaign": "campaigns",
    "sponsored_job": "sponsored_jobs",
    "job_posting": "job_postings",
    "application": "applications",
    "assessment": "assessments",
    "sponsor_event": "sponsor_events",
    "pacing_hold": "pacing_holds",
    "job_posting_version": "job_posting_versions",
}


def get(kind, row_id):
    """Resolve one identifier or fail with that entity's not-found error."""
    if row_id is None or not isinstance(row_id, str) or row_id == "":
        E.fail(NOT_FOUND[kind], "No %s exists with that id." % kind)
    row = getattr(store, TABLES[kind]).get(row_id)
    if row is None:
        E.fail(NOT_FOUND[kind], "No %s exists with id %s." % (kind, row_id))
    return row


# --------------------------------------------------------------------------- body

def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        E.fail(E.ERR_INVALID_REQUEST, "The request body must be a JSON object.")
    return data


def require_object(data):
    if not isinstance(data, dict):
        E.fail(E.ERR_INVALID_REQUEST, "The request body must be a JSON object.")
    return data


def reject_unknown(data, allowed):
    for key in data:
        if key not in allowed:
            E.fail(E.ERR_INVALID_REQUEST, "Unexpected field %s in the request body." % key)


def require_fields(data, names):
    for name in names:
        if name not in data or data[name] is None:
            E.fail(E.ERR_INVALID_REQUEST, "Field %s is required." % name)


def require_string(data, name):
    value = data.get(name)
    if not isinstance(value, str) or value.strip() == "":
        E.fail(E.ERR_INVALID_REQUEST, "Field %s must be a non-empty string." % name)
    return value.strip()


def optional_string(data, name):
    if name not in data or data[name] is None:
        return None
    value = data[name]
    if not isinstance(value, str):
        E.fail(E.ERR_INVALID_REQUEST, "Field %s must be a string." % name)
    return value


def require_int(data, name):
    value = data.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        E.fail(E.ERR_INVALID_REQUEST, "Field %s must be an integer." % name)
    return value


def optional_bool(data, name, default=False):
    if name not in data or data[name] is None:
        return default
    value = data[name]
    if not isinstance(value, bool):
        E.fail(E.ERR_INVALID_REQUEST, "Field %s must be a boolean." % name)
    return value


def require_enum(data, name, allowed):
    value = require_string(data, name)
    if value not in allowed:
        E.fail(E.ERR_INVALID_REQUEST,
               "Field %s must be one of %s." % (name, ", ".join(allowed)))
    return value


def strict_enum(data, name, allowed):
    """Validate a supplied optional enum member."""
    if name not in data or data[name] is None:
        return None
    value = data[name]
    if not isinstance(value, str) or value not in allowed:
        E.fail(E.ERR_INVALID_REQUEST,
               "Field %s must be one of %s." % (name, ", ".join(allowed)))
    return value


def require_array(data, name):
    value = data.get(name)
    if not isinstance(value, list):
        E.fail(E.ERR_INVALID_REQUEST, "Field %s must be an array." % name)
    return value


# ----------------------------------------------------------------- query params

PAGINATION_DEFAULTS = {"limit": 10, "min": 1, "max": 100, "offset": 0}
DEFAULT_LIMIT = PAGINATION_DEFAULTS["limit"]
MAX_LIMIT = PAGINATION_DEFAULTS["max"]
DEFAULT_OFFSET = PAGINATION_DEFAULTS["offset"]


def _int_param(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        E.fail(E.ERR_INVALID_REQUEST, "Query parameter %s must be an integer." % name)
    return value


def pagination():
    """limit/offset with the declared bounds; out-of-range values are invalid."""
    limit = _int_param("limit", DEFAULT_LIMIT)
    offset = _int_param("offset", DEFAULT_OFFSET)
    if limit < PAGINATION_DEFAULTS["min"] or limit > MAX_LIMIT:
        E.fail(E.ERR_INVALID_REQUEST,
               "limit must be between %d and %d." % (PAGINATION_DEFAULTS["min"], MAX_LIMIT))
    if offset < 0:
        E.fail(E.ERR_INVALID_REQUEST, "offset must be zero or greater.")
    return limit, offset


def reject_unknown_query(allowed):
    for name in request.args.keys():
        if name not in allowed:
            E.fail(E.ERR_INVALID_REQUEST, "Unexpected query parameter %s." % name)


def enum_filter(name, allowed):
    """Optional query filter constrained to an enumeration."""
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        E.fail(E.ERR_INVALID_REQUEST,
               "Query parameter %s must be one of %s." % (name, ", ".join(allowed)))
    return raw


def str_filter(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def sort_newest(items):
    """Default list ordering: creation timestamp ascending.

    The logical clock is frozen between advances, so ties are resolved by the
    insertion sequence (the order in which the rows were created).
    """
    return sorted(items, key=lambda row: (row["created_at"], row.get("_seq", 0)))
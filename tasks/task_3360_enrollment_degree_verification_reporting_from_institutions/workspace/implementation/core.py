"""Core primitives: error catalog, response envelope, date handling, validation.

All structural names here come verbatim from SCAFFOLD.yaml §1.0/§1.6 and
PRD.md §2.2/§2.3/§5.
"""
import re
import uuid
from datetime import datetime, timezone

from flask import jsonify, request

# ---------------------------------------------------------------------------
# Error catalog (SCAFFOLD §1.6 / PRD §5) — exact error_id -> HTTP status
# ---------------------------------------------------------------------------
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_UNAUTHORIZED = ("ERR_UNAUTHORIZED", 403)
ERR_CROSS_INSTITUTION_ACCESS = ("ERR_CROSS_INSTITUTION_ACCESS", 403)
ERR_REQUESTER_NOT_VETTED = ("ERR_REQUESTER_NOT_VETTED", 403)
ERR_PURPOSE_NOT_PERMITTED = ("ERR_PURPOSE_NOT_PERMITTED", 422)
ERR_VALIDATION = ("ERR_VALIDATION", 400)
ERR_INSTITUTION_NOT_FOUND = ("ERR_INSTITUTION_NOT_FOUND", 404)
ERR_PERIOD_NOT_FOUND = ("ERR_PERIOD_NOT_FOUND", 404)
ERR_STUDENT_NOT_FOUND = ("ERR_STUDENT_NOT_FOUND", 404)
ERR_FILE_NOT_FOUND = ("ERR_FILE_NOT_FOUND", 404)
ERR_ENTRY_NOT_FOUND = ("ERR_ENTRY_NOT_FOUND", 404)
ERR_CASE_NOT_FOUND = ("ERR_CASE_NOT_FOUND", 404)
ERR_DEGREE_NOT_FOUND = ("ERR_DEGREE_NOT_FOUND", 404)
ERR_REQUESTER_NOT_FOUND = ("ERR_REQUESTER_NOT_FOUND", 404)
ERR_REQUEST_NOT_FOUND = ("ERR_REQUEST_NOT_FOUND", 404)
ERR_NOTIFICATION_NOT_FOUND = ("ERR_NOTIFICATION_NOT_FOUND", 404)
ERR_DATASET_NOT_FOUND = ("ERR_DATASET_NOT_FOUND", 404)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_INSTITUTION_SUSPENDED = ("ERR_INSTITUTION_SUSPENDED", 409)
ERR_ENTRY_SUPERSEDED = ("ERR_ENTRY_SUPERSEDED", 409)
ERR_QUOTE_EXPIRED = ("ERR_QUOTE_EXPIRED", 409)
ERR_AGREEMENT_LAPSED = ("ERR_AGREEMENT_LAPSED", 409)
ERR_PERIOD_NOT_OPEN = ("ERR_PERIOD_NOT_OPEN", 409)
ERR_PRIVACY_BLOCKED = ("ERR_PRIVACY_BLOCKED", 422)
ERR_CONSENT_REQUIRED = ("ERR_CONSENT_REQUIRED", 422)
ERR_INSTITUTION_NON_COMPLIANT = ("ERR_INSTITUTION_NON_COMPLIANT", 422)
ERR_COHORT_TOO_SMALL = ("ERR_COHORT_TOO_SMALL", 422)
ERR_AGREEMENT_OVERLAP = ("ERR_AGREEMENT_OVERLAP", 409)
ERR_PERIOD_OVERLAP = ("ERR_PERIOD_OVERLAP", 409)
ERR_OPEN_CORRECTION_EXISTS = ("ERR_OPEN_CORRECTION_EXISTS", 409)
ERR_DUPLICATE_REQUEST = ("ERR_DUPLICATE_REQUEST", 409)
ERR_SEGREGATION_OF_DUTIES = ("ERR_SEGREGATION_OF_DUTIES", 403)
ERR_UNRESOLVED_ROWS = ("ERR_UNRESOLVED_ROWS", 409)
ERR_MAX_ACTIVE_TRANSCRIPTS = ("ERR_MAX_ACTIVE_TRANSCRIPTS", 409)
ERR_DIRECTIVE_WINDOW_INVALID = ("ERR_DIRECTIVE_WINDOW_INVALID", 422)
ERR_INSUFFICIENT_CREDIT = ("ERR_INSUFFICIENT_CREDIT", 402)


class ApiError(Exception):
    def __init__(self, spec, message):
        self.error_id, self.http_status = spec
        super().__init__(message)
        self.message = message


def raise_err(spec, message):
    raise ApiError(spec, message)


# ---------------------------------------------------------------------------
# Date handling — PRD §2.4: date-valued fields mean midnight UTC (T00:00:00Z)
# ---------------------------------------------------------------------------
_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def fmt_dt(dt):
    """ISO 8601 UTC with three fractional digits (PRD §2.5 created_at/updated_at
    and §2.2 api_request_timestamp)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_dt_sec(dt):
    """ISO 8601 UTC at whole-second granularity — the notation the PRD itself
    uses for every other instant (clock default 2026-09-01T00:00:00Z in §2.4,
    date-valued fields as T00:00:00Z in §2.5, grace/quote/artifact arithmetic
    at whole-day granularity in §2.7)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def try_parse_dt(value):
    """Parse a date or datetime string to an aware UTC datetime; None on failure."""
    if not isinstance(value, str):
        return None
    v = value.strip()
    try:
        if _DATE_ONLY.match(v):
            return datetime.fromisoformat(v).replace(tzinfo=timezone.utc)
        dt = datetime.fromisoformat(v.replace("Z", "+00:00").replace("z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def parse_dt(value, field):
    dt = try_parse_dt(value)
    if dt is None:
        raise_err(ERR_VALIDATION, "field '%s' is not a valid ISO8601 date" % field)
    return dt


# ---------------------------------------------------------------------------
# Response envelope (SCAFFOLD §1.0 / PRD §2.2) — meta/response_type/data
# ---------------------------------------------------------------------------
def _meta():
    import db  # lazy: logical clock lives in db

    return {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": fmt_dt(db.now()),
    }


def ok_object(data, code=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), code


def ok_list(items, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Pagination (SCAFFOLD §1.0 / PRD §2.3): limit/offset, default 10/0, 1..100
# ---------------------------------------------------------------------------
def get_pagination():
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except (TypeError, ValueError):
        raise_err(ERR_VALIDATION, "limit and offset must be integers")
    if limit < 1 or limit > 100:
        raise_err(ERR_VALIDATION, "limit must be between 1 and 100")
    if offset < 0:
        raise_err(ERR_VALIDATION, "offset must be >= 0")
    return limit, offset


def list_response(sorted_items, serialize):
    limit, offset = get_pagination()
    total = len(sorted_items)
    page = sorted_items[offset : offset + limit]
    return ok_list([serialize(i) for i in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Request body helpers — malformed payloads -> ERR_VALIDATION (PRD §2.8)
# ---------------------------------------------------------------------------
def get_body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise_err(ERR_VALIDATION, "request body must be a JSON object")
    return data


def req_field(data, name):
    if name not in data or data[name] is None:
        raise_err(ERR_VALIDATION, "missing required field '%s'" % name)
    return data[name]


def req_str(data, name):
    v = req_field(data, name)
    if not isinstance(v, str) or v == "":
        raise_err(ERR_VALIDATION, "field '%s' must be a non-empty string" % name)
    return v


def req_enum(data, name, allowed):
    v = req_field(data, name)
    if not isinstance(v, str) or v not in allowed:
        raise_err(ERR_VALIDATION, "field '%s' must be one of %s" % (name, list(allowed)))
    return v


def req_int(data, name):
    v = req_field(data, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err(ERR_VALIDATION, "field '%s' must be an integer" % name)
    return v


def req_date(data, name):
    return parse_dt(req_field(data, name), name)


def opt_bool(data, name, default=False):
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if not isinstance(v, bool):
        raise_err(ERR_VALIDATION, "field '%s' must be a boolean" % name)
    return v

"""Response envelope (§1.0) and request-shape helpers (validations 23/24)."""

import random
import string

from flask import jsonify, request

from db import DB, iso, parse_dt
from errors import (ApiError, Err, invalid_value, missing_field)


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

def _request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(12))


def success(data, response_type, pagination=None):
    """{ "meta": {...}, "response_type": "object"|"array", "data": ... }"""
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(DB.now()),
    }
    if pagination is not None:
        meta.update(pagination)
    return jsonify({"meta": meta, "response_type": response_type, "data": data})


def ok_obj(data):
    return success(data, "object"), 200


def created_obj(data):
    return success(data, "object"), 201


def ok_list(rows, limit, offset, total):
    page = rows[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return success(page, "array", pagination), 200


def error_response(err):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(DB.now()),
    }
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------

def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise invalid_value("The request body must be a JSON object.")
    return data


def ensure_known(data, allowed, optional=()):
    """Reject undeclared keys; require every non-optional declared key.

    An absent required field is ERR_MISSING_REQUIRED_FIELD (HTTP 400), which
    PRD §2.11 places in the earliest validation group rather than deferring it
    to a state check.
    """
    for key in data:
        if key not in allowed:
            raise invalid_value("Unknown field %s." % key)
    for key in allowed:
        if key in optional:
            continue
        if key not in data or data[key] is None:
            raise missing_field(key)


def has(data, key):
    return key in data and data[key] is not None


def as_str(data, key, default=None, required=False):
    value = data.get(key)
    if value is None:
        if required:
            raise missing_field(key)
        return default
    if not isinstance(value, str) or value == "":
        raise invalid_value("Field %s must be a non-empty string." % key)
    return value


def as_int(data, key, default=None, required=False):
    value = data.get(key)
    if value is None:
        if required:
            raise missing_field(key)
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid_value("Field %s must be an integer." % key)
    if isinstance(value, float) and value != int(value):
        raise invalid_value("Field %s must be an integer." % key)
    return int(value)


def as_num(data, key, default=None, required=False):
    value = data.get(key)
    if value is None:
        if required:
            raise missing_field(key)
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid_value("Field %s must be a number." % key)
    return float(value)


def as_bool(data, key, default=False, required=False):
    value = data.get(key)
    if value is None:
        if required:
            raise missing_field(key)
        return default
    if not isinstance(value, bool):
        raise invalid_value("Field %s must be a boolean." % key)
    return value


def as_enum(data, key, allowed, default=None, required=True):
    value = data.get(key)
    if value is None:
        if required:
            raise missing_field(key)
        return default
    if not isinstance(value, str) or value not in allowed:
        raise invalid_value("Field %s is outside its constraint set." % key)
    return value


def as_list(data, key, default=None, required=False):
    value = data.get(key)
    if value is None:
        if required:
            raise missing_field(key)
        return default
    if not isinstance(value, list):
        raise invalid_value("Field %s must be an array." % key)
    return value


def as_instant(data, key, default=None, required=False):
    value = data.get(key)
    if value is None:
        if required:
            raise missing_field(key)
        return default
    if isinstance(value, bool) or not isinstance(value, (str,)):
        raise invalid_value("Field %s must be an ISO 8601 instant." % key)
    instant = parse_dt(value)
    if instant is None:
        raise invalid_value("Field %s must be an ISO 8601 instant." % key)
    return instant


# ---------------------------------------------------------------------------
# Pagination (§2.3): limit defaults to 10, min 1, max 100; offset >= 0.
# ---------------------------------------------------------------------------

def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid_value("limit must be an integer.")
        if limit < 1 or limit > 100:
            raise invalid_value("limit must fall between 1 and 100.")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid_value("offset must be an integer.")
        if offset < 0:
            raise invalid_value("offset must not be negative.")
    return limit, offset


def sorted_by_created(rows):
    """Lists are ordered by created_at ascending, stably (PRD §2.3)."""
    rows = list(rows)
    rows.sort(key=lambda row: (row.get("created_at") or "", row.get("id") or ""))
    return rows


def query_filter(rows, name, field=None, caster=None):
    raw = request.args.get(name)
    if raw is None:
        return rows
    field = field or name
    if caster is not None:
        try:
            value = caster(raw)
        except (TypeError, ValueError):
            raise invalid_value("%s has an unusable value." % name)
        return [row for row in rows if row.get(field) == value]
    return [row for row in rows if str(row.get(field)) == raw]


def page(rows, filters=()):
    """Apply filters, order by created_at, then paginate."""
    limit, offset = pagination()
    for name, field, caster in filters:
        rows = query_filter(rows, name, field, caster)
    rows = sorted_by_created(rows)
    return ok_list(rows, limit, offset, len(rows))
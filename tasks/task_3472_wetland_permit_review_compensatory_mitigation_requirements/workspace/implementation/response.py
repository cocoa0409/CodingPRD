"""Standard response envelope helpers (PRD §2.2, §2.3; SCAFFOLD §1.0).

Success: { "meta": {api_request_id, api_request_timestamp[, pagination]},
           "response_type": "object"|"array", "data": ... }
Error:   { "meta": {api_request_id, api_request_timestamp},
           "response_type": "error", "data": {error_id, message} }
Pagination fields: limit / offset / total_count / has_more in meta.
"""

import secrets
import string

from flask import jsonify, request

from db import wall_now_iso
from errors import api_err

_PAGINATION_DEFAULT_LIMIT = 10
_PAGINATION_MIN_LIMIT = 1
_PAGINATION_MAX_LIMIT = 100
_PAGINATION_DEFAULT_OFFSET = 0


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _meta(pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": wall_now_iso(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success_obj(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, total_count, limit, offset, status=200):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(error):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error.error_id, "message": error.message},
    }
    return jsonify(body), error.http_status


def _parse_int_param(raw, name):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise api_err("ERR_INVALID_REQUEST",
                      "Query parameter %s must be an integer" % name)
    # Reject float-strings like "1.5" that int() would never parse anyway,
    # and bool-ish values; int(str) already rejects those. Nothing more.
    return value


def parse_pagination():
    """Parse limit/offset query params per SCAFFOLD §1.0 defaults.

    limit: default 10, must be in 1..100; offset: default 0, must be >= 0.
    Violations are ERR_INVALID_REQUEST (400).
    """
    args = request.args
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = _PAGINATION_DEFAULT_LIMIT
    else:
        limit = _parse_int_param(raw_limit, "limit")
        if limit < _PAGINATION_MIN_LIMIT or limit > _PAGINATION_MAX_LIMIT:
            raise api_err("ERR_INVALID_REQUEST",
                          "limit must be between 1 and 100")
    if raw_offset is None:
        offset = _PAGINATION_DEFAULT_OFFSET
    else:
        offset = _parse_int_param(raw_offset, "offset")
        if offset < 0:
            raise api_err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def list_response(entities, serializer, sort=None):
    """Sort, paginate and serialize a list of entities."""
    if sort is None:
        from db import sort_key
        sort = sort_key
    ordered = sorted(entities, key=sort)
    total = len(ordered)
    limit, offset = parse_pagination()
    page = ordered[offset:offset + limit]
    return success_list([serializer(e) for e in page], total, limit, offset)


def apply_filters(entities, filter_map):
    """Exact-match query filters.

    filter_map: {query_param_name: entity_field_or_callable}. A param present
    in the query string filters entities whose field equals the param value
    (string compare for strings, direct equality otherwise). A callable
    receives (entity, raw_value) and returns bool.
    """
    args = request.args
    result = list(entities)
    for param, field in filter_map.items():
        raw = args.get(param)
        if raw is None:
            continue
        if callable(field):
            result = [e for e in result if field(e, raw)]
        else:
            result = [e for e in result
                      if e.get(field) is not None and str(e.get(field)) == raw]
    return result

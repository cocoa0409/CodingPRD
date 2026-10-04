"""Response envelope helpers (PRD section 2.2 / SCAFFOLD section 1.0).

Success: { "meta": {...}, "response_type": "object" | "array", "data": ... }
Error:   { "meta": {...}, "response_type": "error", "data": { error_id, message } }

Pagination fields live inside `meta` and are `limit`, `offset`, `total_count`,
`has_more` with defaults limit=10, min=1, max=100, offset=0.
"""

import random
import string

from db import format_utc_millis, store

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

_ALPHANUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(16))


def _request_timestamp():
    return format_utc_millis(store.now())


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }
    if extra:
        meta.update(extra)
    return meta


def success_object(data, status=200):
    """A single-resource (or empty-object) success envelope."""
    return {"meta": _meta(), "response_type": "object", "data": data}, status


def success_array(items, limit=None, offset=None, total_count=None):
    """A list success envelope carrying the pagination fields in `meta`."""
    if limit is None:
        limit = PAGINATION_DEFAULT_LIMIT
    if offset is None:
        offset = PAGINATION_DEFAULT_OFFSET
    if total_count is None:
        total_count = len(items)
    meta = _meta(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + len(items) < total_count,
        }
    )
    return {"meta": meta, "response_type": "array", "data": items}, 200


def error_body(error_id, message):
    """The error envelope; `meta` carries only the two request fields."""
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def paginate(rows, params):
    """Apply limit/offset to an already-filtered, already-ordered row list.

    Returns (page, limit, offset, total_count).  `limit` is clamped into
    [1, 100]; `offset` floors at 0.
    """
    limit = _parse_int(params.get("limit"), PAGINATION_DEFAULT_LIMIT)
    offset = _parse_int(params.get("offset"), PAGINATION_DEFAULT_OFFSET)
    limit = max(PAGINATION_MIN_LIMIT, min(PAGINATION_MAX_LIMIT, limit))
    offset = max(0, offset)
    total = len(rows)
    return rows[offset : offset + limit], limit, offset, total


def _parse_int(raw, default):
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def filter_rows(rows, params, mapping):
    """Narrow rows by the documented query filters before pagination.

    `mapping` maps a query parameter name to the row field it constrains.
    String comparisons are exact; boolean filters accept true/false spellings.
    """
    selected = rows
    for param, field in mapping.items():
        raw = params.get(param)
        if raw is None or raw == "":
            continue
        if isinstance(raw, bool):
            wanted = raw
        elif str(raw).lower() in ("true", "false"):
            wanted = str(raw).lower() == "true"
        else:
            wanted = raw
        selected = [row for row in selected if row.get(field) == wanted]
    return selected
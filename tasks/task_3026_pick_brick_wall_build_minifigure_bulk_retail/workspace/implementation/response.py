"""Response envelope helpers (SCAFFOLD.yaml §1.5, PRD §2.2).

Success: { "meta": {...}, "response_type": "object"|"array", "data": {...} }
Error:   { "meta": {...}, "response_type": "error", "data": {error_id, message} }

Pagination fields (limit, offset, total_count, has_more) live in `meta` and are
present for list responses only.
"""

import random
import string
import sys
import traceback

from flask import jsonify, request

from db import format_iso

_ALPHABET = string.ascii_uppercase + string.digits


def _request_id():
    suffix = "".join(random.choice(_ALPHABET) for _ in range(12))
    return "req_" + suffix


def _timestamp():
    # The wire timestamp is the logical clock, so replays are identical.
    from db import now
    return format_iso(now())


def _meta(pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _timestamp(),
    }
    if pagination:
        meta.update(pagination)
    return meta


def envelope(data, response_type="object", status=200, pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def error_envelope(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def paginate(items, params):
    """Apply limit/offset over an already-sorted list.

    Defaults and bounds come from response_envelope.pagination_defaults:
    limit defaults to 10, min 1, max 100, offset defaults to 0.
    """
    from db import DEFAULT_LIMIT, MIN_LIMIT, MAX_LIMIT

    raw_limit = params.get("limit")
    limit = DEFAULT_LIMIT if raw_limit in (None, "") else int(raw_limit)
    limit = max(MIN_LIMIT, min(MAX_LIMIT, limit))

    raw_offset = params.get("offset")
    offset = 0 if raw_offset in (None, "") else max(0, int(raw_offset))

    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, pagination


def register_error_handlers(app):
    """Turn framework-level failures into the standard error envelope."""

    @app.errorhandler(404)
    def _not_found(_exc):
        from errors import ERROR_HTTP
        return error_envelope(
            "ERR_NOT_FOUND",
            "The requested resource does not exist.",
            ERROR_HTTP["ERR_NOT_FOUND"],
        )

    @app.errorhandler(405)
    def _method_not_allowed(_exc):
        from errors import ERROR_HTTP
        return error_envelope(
            "ERR_NOT_FOUND",
            "The requested resource does not exist.",
            ERROR_HTTP["ERR_NOT_FOUND"],
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):
        from errors import ApiError, ERROR_HTTP
        if isinstance(exc, ApiError):
            return error_envelope(exc.error_id, exc.message, exc.http_status)
        traceback.print_exc(file=sys.stderr)
        return error_envelope(
            "ERR_CONSTRAINT_VIOLATION",
            "The request could not be processed.",
            ERROR_HTTP["ERR_CONSTRAINT_VIOLATION"],
        )
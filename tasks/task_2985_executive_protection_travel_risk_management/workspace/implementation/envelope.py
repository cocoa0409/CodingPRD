"""Response envelopes -- PRD 2.2 and 2.3."""

from flask import Response

from store import store
from util import dumps, fmt_instant, new_request_id


def _meta():
    return {
        "api_request_id": new_request_id(),
        # PRD 2.2: a server-generated ISO 8601 UTC timestamp with three
        # fractional digits.  The envelope timestamp is the logical clock, which
        # PRD 2.5 makes the service's only source of time.
        "api_request_timestamp": fmt_instant(store.now()),
    }


def _respond(body, status):
    return Response(
        dumps(body),
        status=status,
        mimetype="application/json",
    )


def object_response(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return _respond(body, status)


def list_response(rows, limit, offset, total_count, has_more, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = has_more
    body = {
        "meta": meta,
        "response_type": "array",
        "data": rows,
    }
    return _respond(body, status)


def error_response(error_id, message, status):
    body = {
        # PRD 2.2: the meta object for error responses contains only
        # api_request_id and api_request_timestamp.
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _respond(body, status)

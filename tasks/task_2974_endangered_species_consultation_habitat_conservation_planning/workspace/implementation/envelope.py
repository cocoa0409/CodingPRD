"""The response envelope of PRD 2.2."""
from flask import Response

import store
import util

NULL_PAGINATION = {
    "limit": None,
    "offset": None,
    "total_count": None,
    "has_more": None,
}


def _meta(pagination=None):
    meta = {
        "api_request_id": util.new_request_id(),
        # The envelope timestamp reads the logical clock like everything else.
        "api_request_timestamp": util.fmt_instant(store.now()),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def _send(body, status):
    return Response(
        util.dumps(body) + "\n", status=status, mimetype="application/json"
    )


def obj(data, status=200):
    return _send(
        {"meta": _meta(), "response_type": "object", "data": data}, status
    )


def created(data):
    return obj(data, 201)


def paginated(rows, limit, offset, total):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(rows)) < total,
    }
    return _send(
        {"meta": _meta(pagination), "response_type": "array", "data": rows}, 200
    )


def unpaginated(rows):
    """Every list except the two paginated ones: complete collection, and a
    null pagination block rather than counters (PRD 2.3)."""
    return _send(
        {
            "meta": _meta(dict(NULL_PAGINATION)),
            "response_type": "array",
            "data": rows,
        },
        200,
    )


def failure(err):
    return _send(
        {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": err.error_id, "message": err.message},
        },
        err.http_status,
    )

"""Standard response envelope helpers matching SCAFFOLD.yaml 1.0 / PRD 2.2.

Success envelope:
  { "meta": { "api_request_id": ..., "api_request_timestamp": ... },
    "response_type": "object" | "array", "data": ... }
  For list responses the meta object additionally carries:
    limit, offset, total_count, has_more

Error envelope:
  { "meta": { "api_request_id": ..., "api_request_timestamp": ... },
    "response_type": "error",
    "data": { "error_id": ..., "message": ... } }
"""

import uuid
from datetime import datetime, timezone

from flask import jsonify


def _iso_now():
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    return (
        datetime.now(timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%S.")
        + f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"
    )


def _meta_base():
    """Build the meta block shared by success and error envelopes."""
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": _iso_now(),
    }


def success(data, response_type="object", status_code=200, meta_extra=None):
    """Return a standard success envelope.

    Parameters
    ----------
    data : dict | list | None
        The payload placed in the ``data`` field.
    response_type : str
        "object" for a single resource, "array" for a list.
    status_code : int
        HTTP status code (201 for creates, 200 for everything else).
    meta_extra : dict | None
        Additional fields merged into ``meta`` (pagination keys for lists).
    """
    meta = _meta_base()
    if meta_extra:
        meta.update(meta_extra)
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    return jsonify(body), status_code


def error(error_id, message, http_status):
    """Return a standard error envelope."""
    meta = _meta_base()
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status

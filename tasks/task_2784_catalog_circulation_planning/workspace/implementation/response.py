"""Response envelope helpers (meta / response_type / data)."""

from datetime import datetime

from flask import jsonify

from util import fmt_dt, request_id, utcnow


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_dt(utcnow()),
    }


def serialize(row):
    """Project an internal row into its wire form (internal `_` keys are hidden)."""
    if row is None:
        return None
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        if isinstance(value, datetime):
            out[key] = fmt_dt(value)
        else:
            out[key] = value
    return out


def object_response(data, status=200):
    return (
        jsonify({"meta": _meta(), "response_type": "object", "data": data}),
        status,
    )


def entity_response(row, status=200):
    return object_response(serialize(row), status)


def list_response(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    return (
        jsonify(
            {
                "meta": meta,
                "response_type": "array",
                "data": [serialize(r) for r in rows],
            }
        ),
        200,
    )


def error_response(error_id, message, status):
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": error_id, "message": message},
            }
        ),
        status,
    )

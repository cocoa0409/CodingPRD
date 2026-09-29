"""Response envelope helpers (PRD 2.2 / 2.3)."""

from datetime import date, datetime
from decimal import Decimal

from flask import jsonify

import util


def _meta():
    return {
        "api_request_id": util.new_request_id(),
        "api_request_timestamp": util.fmt_instant(util.clock.now()),
    }


def serialize(row):
    """Public projection of a stored row.  Internal bookkeeping keys are
    prefixed with an underscore and never leave the process."""
    if row is None:
        return None
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        out[key] = _coerce(value)
    return out


def _coerce(value):
    if isinstance(value, datetime):
        return util.fmt_instant(value)
    if isinstance(value, date):
        # PRD 2.9: calendar dates are carried as YYYY-MM-DD, never as instants.
        return util.fmt_date(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return dict((k, _coerce(v)) for k, v in value.items())
    if isinstance(value, list):
        return [_coerce(v) for v in value]
    return value


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": _coerce(data) if data is not None else {},
    }
    return jsonify(body), status


def ok_row(row, status=200):
    return ok(serialize(row), status)


def ok_list(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serialize(r) for r in rows],
    }
    return jsonify(body), 200


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status

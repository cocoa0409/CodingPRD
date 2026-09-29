"""Response envelope, serialisation and pagination (PRD sections 2.2 and 2.3)."""
import uuid
from datetime import datetime
from decimal import Decimal

from flask import jsonify

import store


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": store.fmt(store.now()),
    }


def _scalar(value):
    if isinstance(value, datetime):
        return store.fmt(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_scalar(v) for v in value]
    if isinstance(value, dict):
        return {k: _scalar(v) for k, v in value.items()}
    return value


def serialize(row):
    """Public projection of a stored row: internal keys are prefixed with '_'."""
    if row is None:
        return None
    return {k: _scalar(v) for k, v in row.items() if not k.startswith("_")}


def obj(row, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": serialize(row)}
    return jsonify(body), code


def raw(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": _scalar(data)}
    return jsonify(body), code


def collection(rows, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serialize(r) for r in page],
    }
    return jsonify(body), 200


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# --- orderings ---------------------------------------------------------------
def order_default(rows):
    """PRD 2.3 default: created_at ASC, insertion order as the stable tie-break."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def order_created_desc_id_asc(rows):
    """Service categories: created_at DESC then id ASC."""
    by_id = sorted(rows, key=lambda r: r["id"])
    return sorted(by_id, key=lambda r: r["created_at"], reverse=True)


def order_scorecard_events(rows):
    """occurred_at ASC then created_at ASC."""
    return sorted(rows, key=lambda r: (r["occurred_at"], r["created_at"], r["_seq"]))

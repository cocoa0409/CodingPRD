"""Response envelope helpers (PRD 2.2 / 2.3) and the per-request mutation ledger."""

from flask import g, jsonify

from errors import ApiError
from util import fmt_dt, new_request_id, now_wall

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_dt(now_wall()),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(rows, limit, offset):
    total = len(rows)
    window = rows[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(window)) < total
    body = {"meta": meta, "response_type": "array", "data": window}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# ---------------------------------------------------------------------------
# mutation ledger: a row advances its version by exactly 1 per request (PRD 2.4)
# ---------------------------------------------------------------------------

def _ledger():
    if not hasattr(g, "_touched"):
        g._touched = set()
    return g._touched


def mark_new(row):
    """A freshly created row is already at version 1 for this request."""
    _ledger().add(row["id"])
    return row


def touch(row):
    """Bump version/updated_at once per request for this row."""
    ledger = _ledger()
    if row["id"] in ledger:
        return row
    ledger.add(row["id"])
    row["version"] += 1
    row["updated_at"] = now_wall()
    return row


def parse_pagination(args):
    limit = args.get("limit")
    offset = args.get("offset")
    if limit is None or limit == "":
        limit_value = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit_value = int(str(limit))
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit_value < PAGINATION_MIN_LIMIT or limit_value > PAGINATION_MAX_LIMIT:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if offset is None or offset == "":
        offset_value = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset_value = int(str(offset))
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset_value < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset may not be negative.")
    return limit_value, offset_value

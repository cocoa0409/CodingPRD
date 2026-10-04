"""Response envelope helpers (PRD 2.2 / 2.3, SCAFFOLD response_envelope)."""
import json
import os
import uuid
from datetime import datetime, timezone

from flask import Response

from constants import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
)

_PRETTY = os.environ.get("OTP_COMPACT_JSON", "") not in ("1", "true", "True")


def _request_id():
    return "req_" + uuid.uuid4().hex[:20].upper()


def _timestamp():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)


def _dump(payload):
    if _PRETTY:
        return pretty(payload)
    return json.dumps(payload)


def pretty(value, level=0):
    """Serialize an object one key per line, deterministically.

    Compact (single-line) serialization of numbers is used because JSON numbers
    are not exact, and a line-oriented encoder lets assertions test integral
    values by exact text.
    """
    ind = "  " * level
    nxt = "  " * (level + 1)
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, dict):
        if not value:
            return "{}"
        items = []
        for key in sorted(value.keys()):
            items.append("%s%s: %s" % (nxt, json.dumps(str(key)), pretty(value[key], level + 1)))
        return "{\n" + ",\n".join(items) + "\n" + ind + "}"
    if isinstance(value, (list, tuple)):
        if not value:
            return "[]"
        items = ["%s%s" % (nxt, pretty(v, level + 1)) for v in value]
        return "[\n" + ",\n".join(items) + "\n" + ind + "]"
    return json.dumps(str(value))


def envelope(data, response_type="object", http_status=200, pagination=None):
    meta = {"api_request_id": _request_id(), "api_request_timestamp": _timestamp()}
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    payload = {"meta": meta, "response_type": response_type, "data": data}
    return Response(_dump(payload), status=http_status, mimetype="application/json")


def ok_object(data, http_status=200):
    return envelope(data, "object", http_status)


def ok_array(items, http_status=200):
    return envelope(list(items), "array", http_status)


def ok_array_paged(items, limit, offset, total_count, http_status=200):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(items) < total_count,
    }
    return envelope(list(items), "array", http_status, pagination=pagination)


def error(error_id, message, http_status, details=None):
    data = {"error_id": error_id, "message": message}
    if details:
        data["details"] = details
    payload = {
        "meta": {"api_request_id": _request_id(), "api_request_timestamp": _timestamp()},
        "response_type": "error",
        "data": data,
    }
    return Response(_dump(payload), status=http_status, mimetype="application/json")


def parse_pagination(args):
    """Read the pagination contract: limit defaults to 10, 1..100; offset defaults to 0."""
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None or str(limit_raw).strip() == "":
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(str(limit_raw))
        except (TypeError, ValueError):
            limit = PAGINATION_DEFAULT_LIMIT
    if limit < PAGINATION_MIN_LIMIT:
        limit = PAGINATION_MIN_LIMIT
    if limit > PAGINATION_MAX_LIMIT:
        limit = PAGINATION_MAX_LIMIT
    if offset_raw is None or str(offset_raw).strip() == "":
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(str(offset_raw))
        except (TypeError, ValueError):
            offset = PAGINATION_DEFAULT_OFFSET
    if offset < 0:
        offset = 0
    return limit, offset


def paginate_sorted(rows, limit, offset):
    """Order by created_at then id, then apply limit/offset."""
    ordered = sorted(rows, key=lambda r: (str(r.get("created_at", "")), str(r.get("id", ""))))
    total = len(ordered)
    return ordered[offset:offset + limit], total
"""Response envelope helpers per PRD 2.2 and SCAFFOLD response_envelope."""
import secrets
from datetime import datetime, timezone

from flask import jsonify

import db
import errors


def _request_id():
    return "req_" + secrets.token_hex(8)


def _timestamp_iso():
    # Timestamp with 3 fractional digits, UTC, Z suffix
    dt = datetime.now(timezone.utc)
    s = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return f"{s}.{dt.microsecond // 1000:03d}Z"


def iso_from_ts(ts):
    if ts is None:
        return None
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    s = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return f"{s}.{dt.microsecond // 1000:03d}Z"


def ts_from_iso(s):
    if not isinstance(s, str):
        raise errors.invalid_request("expected ISO8601 string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        raise errors.invalid_request("invalid ISO8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def success_object(data, status=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _timestamp_iso(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _timestamp_iso(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _timestamp_iso(),
        },
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def parse_pagination(args):
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("limit must be integer")
        if limit < 1 or limit > 100:
            raise errors.invalid_request("limit out of range")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("offset must be integer")
        if offset < 0:
            raise errors.invalid_request("offset out of range")
    return limit, offset

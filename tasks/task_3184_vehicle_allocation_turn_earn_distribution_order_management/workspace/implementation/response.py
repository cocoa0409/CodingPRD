"""Response envelope helpers (PRD §2.2, §2.3)."""
import secrets
import string

from flask import request

from db import now_iso


def _request_id() -> str:
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _meta() -> dict:
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }


def success_object(data: dict, status: int = 200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return body, status


def _parse_int(value, default, minimum, maximum):
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if parsed < minimum:
        return minimum
    if parsed > maximum:
        return maximum
    return parsed


def success_list(rows: list, status: int = 200):
    args = request.args
    limit = _parse_int(args.get("limit"), 10, 1, 100)
    offset = _parse_int(args.get("offset"), 0, 0, 10**12)
    total_count = len(rows)
    window = rows[offset:offset + limit]
    meta = _meta()
    meta.update({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(window)) < total_count,
    })
    body = {"meta": meta, "response_type": "array", "data": window}
    return body, status


def error_response(error_id: str, http_status: int, message: str):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return body, http_status

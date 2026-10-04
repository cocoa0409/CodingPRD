"""Standard response envelope helpers (PRD §2.2, §2.3)."""
from __future__ import annotations

import random
import string

from flask import jsonify

from errors import fail
from util import fmt_ts, now

_ALPHABET = string.ascii_uppercase + string.digits


def request_id() -> str:
    return "req_" + "".join(random.choices(_ALPHABET, k=16))


def _meta(extra: dict | None = None) -> dict:
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_ts(now()),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status: int = 200, pagination: dict | None = None):
    body = {
        "meta": _meta(pagination),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), status


def err_response(error_id: str, status: int | None = None, message: str | None = None):
    exc = fail(error_id, message)
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": exc.error_id, "message": exc.message},
    }
    return jsonify(body), (status if status is not None else exc.status)


def paginate(items: list, limit, offset) -> tuple[list, dict]:
    """Apply the pagination contract of PRD §2.3 over already-sorted items."""
    limit = _int_param("limit", limit, 10, 1, 100)
    offset = _int_param("offset", offset, 0, 0, None)
    total = len(items)
    window = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
    return window, meta


def _int_param(name: str, raw, default: int, minimum, maximum):
    if raw is None or raw == "":
        return default
    if isinstance(raw, bool):
        raise fail("ERR_INVALID_REQUEST", f"{name} must be an integer.")
    if isinstance(raw, int):
        value = raw
    elif isinstance(raw, str):
        try:
            value = int(raw.strip())
        except ValueError:
            raise fail("ERR_INVALID_REQUEST", f"{name} must be an integer.")
    else:
        raise fail("ERR_INVALID_REQUEST", f"{name} must be an integer.")
    if minimum is not None and value < minimum:
        raise fail("ERR_INVALID_REQUEST", f"{name} must be at least {minimum}.")
    if maximum is not None and value > maximum:
        raise fail("ERR_INVALID_REQUEST", f"{name} must not exceed {maximum}.")
    return value
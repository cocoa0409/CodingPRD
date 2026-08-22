"""Standard success / error envelopes (PRD section 2.2)."""

import json
import random
import string
from datetime import datetime
from decimal import Decimal

from flask import Response

import clock

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.fmt(clock.now()),
    }


def jsonable(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return clock.fmt(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def _emit(body, status):
    return Response(
        json.dumps(body, ensure_ascii=False),
        status=status,
        mimetype="application/json",
    )


def object_response(record, status=200):
    body = {
        "meta": _base_meta(),
        "response_type": "object",
        "data": jsonable(record) if record is not None else {},
    }
    return _emit(body, status)


def empty_response(status=200):
    body = {"meta": _base_meta(), "response_type": "object", "data": {}}
    return _emit(body, status)


def no_content_response():
    return Response("", status=204)


def list_response(rows, limit, offset, total_count, status=200):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [jsonable(r) for r in rows],
    }
    return _emit(body, status)


def error_response(error_id, message, status):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _emit(body, status)

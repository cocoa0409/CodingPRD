"""Response envelope (PRD 2.2) and pagination window (PRD 2.3)."""
import json
import random
import string
from datetime import date, datetime
from decimal import Decimal

from flask import Response

from helpers import UTC, fmt_instant

ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(ALNUM) for _ in range(20))


def meta(extra=None):
    body = {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_instant(datetime.now(UTC)),
    }
    if extra:
        body.update(extra)
    return body


def _json_default(value):
    """Decimals leave the process as JSON numbers, never strings (PRD 2.6)."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return fmt_instant(value)
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError("cannot serialise %r" % (value,))


def _response(payload, status):
    return Response(
        json.dumps(payload, allow_nan=False, default=_json_default),
        status=status,
        mimetype="application/json",
    )


def obj(data, status=200):
    return _response({"meta": meta(), "response_type": "object", "data": data or {}}, status)


def empty(status=200):
    return obj({}, status)


def collection(rows, limit, offset, total):
    page = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(rows)) < total,
    }
    return _response(
        {"meta": meta(page), "response_type": "array", "data": rows}, 200
    )


def error(error_id, message, status):
    return _response(
        {
            "meta": meta(),
            "response_type": "error",
            "data": {"error_id": error_id, "message": message},
        },
        status,
    )

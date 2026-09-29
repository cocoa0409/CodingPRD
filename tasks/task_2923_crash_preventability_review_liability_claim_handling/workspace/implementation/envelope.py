"""Response envelope helpers (PRD 2.2) and timestamp / number formatting."""

import random
import string
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone

from flask import jsonify

from store import db

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def fmt_dt(value):
    """ISO 8601 UTC instant with exactly three fractional digits."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    dt = value.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def rhu(value, places):
    """Round half up to `places` decimal places, returning a Decimal."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quant = Decimal(1).scaleb(-places)
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def rhu_int(value):
    """Round half up to a whole unit (cents), returning an int."""
    return int(rhu(value, 0))


def num(value):
    """Render a Decimal as a JSON number."""
    if value is None:
        return None
    return float(value)


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_dt(db.now),
    }


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }

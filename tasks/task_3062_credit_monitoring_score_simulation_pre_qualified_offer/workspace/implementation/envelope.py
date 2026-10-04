"""Response envelope, pagination and small numeric helpers."""

from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify

PAGINATION_DEFAULTS = {"limit": 10, "min": 1, "max": 100, "offset": 0}


def timestamp(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + "%03d" % (moment.microsecond // 1000) + "Z"


def plain_timestamp(moment):
    """Domain instants are reported without fractional digits (PRD 2.10 keeps the
    three-digit form for created_at/updated_at; other dated fields echo the
    whole-second instants the platform stores)."""
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def req_id():
    import uuid
    return "req_" + uuid.uuid4().hex[:20].upper()


def meta(moment, pagination=None):
    m = {"api_request_id": req_id(), "api_request_timestamp": timestamp(moment)}
    if pagination is not None:
        m.update(pagination)
    return m


def ok(data, moment, status=200, pagination=None):
    body = {"meta": meta(moment, pagination), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, moment, pagination=None):
    body = {"meta": meta(moment, pagination), "response_type": "array", "data": items}
    return jsonify(body), 200


def error_body(error_id, message, moment):
    return {"meta": meta(moment), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}


def limited(items, args):
    raw_limit = args.get("limit", None)
    raw_offset = args.get("offset", None)
    try:
        limit = int(raw_limit) if raw_limit not in (None, "") else PAGINATION_DEFAULTS["limit"]
    except (TypeError, ValueError):
        limit = PAGINATION_DEFAULTS["limit"]
    try:
        offset = int(raw_offset) if raw_offset not in (None, "") else PAGINATION_DEFAULTS["offset"]
    except (TypeError, ValueError):
        offset = PAGINATION_DEFAULTS["offset"]
    if limit < PAGINATION_DEFAULTS["min"]:
        limit = PAGINATION_DEFAULTS["min"]
    if limit > PAGINATION_DEFAULTS["max"]:
        limit = PAGINATION_DEFAULTS["max"]
    if offset < 0:
        offset = 0
    total = len(items)
    window = items[offset:offset + limit]
    pagination = {"limit": limit, "offset": offset, "total_count": total,
                  "has_more": (offset + limit) < total}
    return window, pagination


def rhu(value, places):
    """Round half up to `places` decimal places, returning a float."""
    if value is None:
        return None
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))
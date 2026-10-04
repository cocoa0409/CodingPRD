"""Response envelope helpers: meta / response_type / data."""
import random
import string

import clock

_ALPHABET = string.ascii_uppercase + string.digits


def request_id():
    suffix = "".join(random.choice(_ALPHABET) for _ in range(12))
    return "req_" + suffix


def meta(extra=None):
    body = {
        "api_request_id": request_id(),
        "api_request_timestamp": clock.now().strftime("%Y-%m-%dT%H:%M:%S.")
        + "%03dZ" % (clock.now().microsecond // 1000),
    }
    if extra:
        body.update(extra)
    return body


def success(data, response_type="object", pagination=None):
    return {
        "meta": meta(pagination),
        "response_type": response_type,
        "data": data,
    }


def list_response(rows, total_count, limit, offset):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + limit) < total_count,
    }
    return success(rows, "array", pagination)


def error(error_id, message):
    return {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
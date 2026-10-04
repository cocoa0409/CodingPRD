import secrets
import string

from util import fmt_iso
from clock import now as clock_now


def _request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def meta_base():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_iso(clock_now()),
    }


def success_object(data, status=200):
    body = {
        "meta": meta_base(),
        "response_type": "object",
        "data": data,
    }
    return body, status


def success_list(items, limit, offset, total_count):
    m = meta_base()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total_count
    m["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": m,
        "response_type": "array",
        "data": items,
    }
    return body, 200


def error_body(err):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {
            "error_id": err.error_id,
            "message": err.message,
        },
    }
    return body, err.http_status

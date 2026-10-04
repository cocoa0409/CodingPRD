"""Response envelope helpers matching PRD section 2.2 and 2.3."""

import random
import string
from datetime import timezone

from errors import fmt
from db import DB

ALPHANUM = string.ascii_letters + string.digits


def request_id():
    return "req_" + "".join(random.choice(ALPHANUM) for _ in range(18))


def meta(extra=None):
    body = {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt(DB.now),
    }
    if extra:
        body.update(extra)
    return body


def success(data, response_type="object", pagination=None, status=200):
    body = {"meta": meta(pagination), "response_type": response_type, "data": data}
    return body, status


def object_response(data, status=200):
    return success(data, "object", None, status)


def list_response(items, limit, offset, status=200, total_count=None):
    """`items` is already the page the caller wants to publish.

    `total_count`, when supplied, is the number of matching rows across all pages
    — it drives `has_more` and is reported verbatim, but it never re-slices the
    page the caller handed over.
    """
    total = len(items) if total_count is None else total_count
    page = items
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(items) < total,
    }
    return success(page, "array", pagination, status)


def error_body(error_id, message):
    return {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
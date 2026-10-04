"""Standard response envelope (PRD section 2.2 / scaffold response_envelope)."""

import random
import string

from . import clock
from .errors import ApiError, fail

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(16))


def meta(extra=None):
    payload = {
        "api_request_id": request_id(),
        "api_request_timestamp": clock.fmt(clock.now()),
    }
    if extra:
        payload.update(extra)
    return payload


class Result(object):
    """A handler's return value: status + payload + envelope shape."""

    def __init__(self, status, data, response_type="object", pagination=None):
        self.status = status
        self.data = data
        self.response_type = response_type
        self.pagination = pagination


def ok(data, response_type="object", pagination=None):
    body = {
        "meta": meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return body


def ok_list(items, limit, offset, total_count):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return ok(items, response_type="array", pagination=pagination)


def error(error_id, message):
    return {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def parse_pagination(args):
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    if raw_limit is not None and str(raw_limit) != "":
        try:
            limit = int(str(raw_limit))
        except ValueError:
            fail("ERR_INVALID_ENUM_VALUE", "limit must be an integer between 1 and 100")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            fail("ERR_INVALID_ENUM_VALUE", "limit must lie between 1 and 100 inclusive")
    if raw_offset is not None and str(raw_offset) != "":
        try:
            offset = int(str(raw_offset))
        except ValueError:
            fail("ERR_INVALID_ENUM_VALUE", "offset must be a non-negative integer")
        if offset < 0:
            fail("ERR_INVALID_ENUM_VALUE", "offset must be a non-negative integer")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit] if offset < total else []
    return page, total


def page_response(items, args):
    limit, offset = parse_pagination(args)
    page, total = paginate(items, limit, offset)
    return ok_list(page, limit, offset, total)


def paged(items, args):
    limit, offset = parse_pagination(args)
    page, total = paginate(items, limit, offset)
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return Result(200, page, response_type="array", pagination=pagination)

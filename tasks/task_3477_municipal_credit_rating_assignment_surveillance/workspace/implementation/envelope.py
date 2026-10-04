"""Response envelope (PRD §2.2), entity serialization, and pagination
(PRD §2.3). Field names are fixed by SCAFFOLD §1.0: meta / response_type /
data, with limit / offset / total_count / has_more on list responses."""
import random
import re
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import jsonify

import timeutil
from constants import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
)
from errors import ERR_INVALID_PAGINATION_PARAMETERS, raise_err


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=24))


def _request_timestamp():
    """Wall-clock request metadata timestamp (3 fractional digits)."""
    return timeutil.iso(datetime.now(timezone.utc))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }


def serialize(value):
    """Recursively convert stored entities to JSON-safe structures:
    datetime -> ISO8601 ms string, Decimal -> float, internal keys dropped."""
    if isinstance(value, dict):
        return {k: serialize(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [serialize(v) for v in value]
    if isinstance(value, datetime):
        return timeutil.iso(value)
    if isinstance(value, Decimal):
        return float(value)
    return value


def success_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": serialize(data)}
    return jsonify(body), status


def success_array(items, total_count, limit, offset, status=200):
    meta = _meta()
    meta.update(
        limit=limit,
        offset=offset,
        total_count=total_count,
        has_more=(offset + limit) < total_count,
    )
    body = {"meta": meta, "response_type": "array", "data": serialize(items)}
    return jsonify(body), status


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def error_response(api_error):
    return jsonify(error_body(api_error.error_id, api_error.message)), api_error.http_status


_INT_RE = re.compile(r"^[+-]?\d+$")


def _parse_int_param(raw, name):
    text = str(raw).strip()
    if not _INT_RE.match(text):
        raise_err(ERR_INVALID_PAGINATION_PARAMETERS, name + " must be an integer")
    return int(text)


def parse_pagination(args):
    """Validate limit/offset (priority 12): limit 1..100 default 10, offset
    >= 0 default 0. Any violation is ERR_INVALID_PAGINATION_PARAMETERS."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        limit = _parse_int_param(raw_limit, "limit")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise_err(ERR_INVALID_PAGINATION_PARAMETERS, "limit must be within 1..100")
    if raw_offset is None:
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        offset = _parse_int_param(raw_offset, "offset")
        if offset < 0:
            raise_err(ERR_INVALID_PAGINATION_PARAMETERS, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    return items[offset : offset + limit], len(items)

"""Response envelope and pagination helpers."""

import random
import string
from datetime import datetime, timezone

from constants import API_PREFIX  # noqa: F401  (kept for import symmetry)
from errors import fail

_ALPHABET = string.ascii_uppercase + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(18))


def _stamp():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)


def meta(pagination=None):
    body = {"api_request_id": new_request_id(), "api_request_timestamp": _stamp()}
    if pagination:
        body.update(pagination)
    return body


def ok(data, response_type="object", status=200, pagination=None):
    return {"meta": meta(pagination), "response_type": response_type, "data": data}, status


def error_body(error_id, message):
    return {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def _int_param(raw, name, default):
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % name)


def pagination_args(args):
    """Parse limit/offset; out-of-range values are request-shape failures."""
    limit = _int_param(args.get("limit"), "limit", 10)
    offset = _int_param(args.get("offset"), "offset", 0)
    if limit < 1 or limit > 100:
        fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if offset < 0:
        fail("ERR_INVALID_REQUEST", "offset must be zero or greater.")
    return limit, offset


def paginate(rows, args):
    """Return (page_rows, pagination_meta) for an already filtered, ordered list."""
    limit, offset = pagination_args(args)
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }


def list_response(rows, args, serializer):
    page, pag = paginate(rows, args)
    return ok([serializer(r) for r in page], response_type="array", pagination=pag)

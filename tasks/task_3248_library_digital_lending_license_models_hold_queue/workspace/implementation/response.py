import secrets
import string
from flask import jsonify
from timeutil import fmt_ts_ms, wall_now
from errors import ApiError, ERR_INVALID_REQUEST, err

_ALPHANUM = string.ascii_letters + string.digits


def _request_id():
    return "req_" + "".join(secrets.choice(_ALPHANUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_ts_ms(wall_now()),
    }


def success(data, code=200, pagination=None):
    """Build the success envelope. pagination: dict(limit, offset, total_count)."""
    meta = _meta()
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = (pagination["offset"] + len(data)) < pagination["total_count"]
    body = {
        "meta": meta,
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), code


def error_response(api_err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": api_err.error_id, "message": api_err.message},
    }
    return jsonify(body), api_err.http_status


def parse_pagination(args):
    """Parse limit/offset query params per envelope defaults (10 / min 1 / max 100 / offset 0)."""
    def _parse_int(raw, name):
        if raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, f"{name} must be an integer")

    limit = _parse_int(args.get("limit"), "limit")
    offset = _parse_int(args.get("offset"), "offset")
    if limit is None:
        limit = 10
    if offset is None:
        offset = 0
    if limit < 1 or limit > 100:
        raise err(ERR_INVALID_REQUEST, "limit out of range")
    if offset < 0:
        raise err(ERR_INVALID_REQUEST, "offset out of range")
    return limit, offset


def paginate(items, args):
    """Apply limit/offset; items must already be sorted."""
    limit, offset = parse_pagination(args)
    total = len(items)
    return items[offset:offset + limit], {"limit": limit, "offset": offset, "total_count": total}

# Success envelope + pagination (PRD 2.2, 2.3; scaffold response_envelope).
from flask import jsonify

import clock
import constants
import errors


def _meta():
    return {
        "api_request_id": errors._request_id(),
        "api_request_timestamp": clock.now_iso(),
    }


def success(data, response_type="object", status=200, pagination=None):
    meta = _meta()
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def success_object(data, status=200):
    return success(data, response_type="object", status=status)


def success_list(items, total_count, limit, offset, status=200):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return success(items, response_type="array", status=status, pagination=pagination)


def parse_pagination(args):
    """Parse limit/offset query params (PRD 2.3): limit default 10, min 1, max 100;
    offset default 0. Non-integer values are body-shape violations; out-of-range
    integers are clamped to the allowed bounds."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = constants.PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            errors.validation("limit must be an integer")
        limit = max(constants.PAGINATION_MIN_LIMIT,
                    min(constants.PAGINATION_MAX_LIMIT, limit))
    if raw_offset is None:
        offset = constants.PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            errors.validation("offset must be an integer")
        offset = max(0, offset)
    return limit, offset


def paginate(items, args):
    """Sort by created_at ascending (insertion sequence breaks ties), then page."""
    limit, offset = parse_pagination(args)
    ordered = sorted(items, key=lambda e: (e.get("created_at", ""), e.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total, limit, offset

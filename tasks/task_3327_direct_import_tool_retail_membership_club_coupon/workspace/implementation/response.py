"""Response envelope helpers."""
from flask import jsonify
from db import DB, fmt_iso
from errors import new_request_id


def success(data, response_type="object", status=200, meta_extra=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_iso(DB.now()),
    }
    if meta_extra:
        meta.update(meta_extra)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    return success(
        items,
        response_type="array",
        status=200,
        meta_extra={
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        },
    )


def parse_pagination(args):
    def to_int(v, default):
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    limit = to_int(args.get("limit"), 10)
    offset = to_int(args.get("offset"), 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, total

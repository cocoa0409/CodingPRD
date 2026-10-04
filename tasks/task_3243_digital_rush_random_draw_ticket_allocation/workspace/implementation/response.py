"""Response envelope, pagination helpers and list ordering."""

import random
import string

from flask import jsonify

from clock import CLOCK

_PAGINATION_DEFAULTS = {"limit": 10, "min": 1, "max": 100, "offset": 0}


def new_request_id():
    body = "".join(
        random.choice(string.ascii_uppercase + string.digits) for _ in range(20)
    )
    return "req_" + body


def _meta_common():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": CLOCK.stamp(),
    }


def ok(data, status=200):
    """200-family envelope for a single resource or an empty object."""
    body = {
        "meta": _meta_common(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def ok_list(items, limit, offset):
    total = len(items)
    page = items[offset: offset + limit]
    meta = _meta_common()
    meta.update(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": (offset + limit) < total,
        }
    )
    return jsonify({"meta": meta, "response_type": "array", "data": page}), 200


def error(error_id, message, status):
    body = {
        "meta": _meta_common(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def read_pagination(args):
    """limit defaults to 10, 1..100, refused outside the band; offset >= 0."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    limit = _PAGINATION_DEFAULTS["limit"] if raw_limit is None else _int_arg(raw_limit)
    offset = _PAGINATION_DEFAULTS["offset"] if raw_offset is None else _int_arg(raw_offset)
    if limit is None or offset is None:
        return None
    if limit < _PAGINATION_DEFAULTS["min"] or limit > _PAGINATION_DEFAULTS["max"]:
        return None
    if offset < 0:
        return None
    return limit, offset


def _int_arg(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def sorted_by_created(rows):
    """Collections are ordered by created_at ascending."""
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("id") or ""))

def apply_filters(rows, args, fields):
    """Conjunctive, optional filters. Unknown filter values narrow to nothing."""
    out = rows
    for field in fields:
        value = args.get(field)
        if value is None:
            continue
        out = [r for r in out if str(r.get(field)) == str(value)]
    return out


def public(row):
    """Strip server-internal bookkeeping keys before serialising a row."""
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def public_list(rows):
    return [public(r) for r in rows]
"""Thin request/response plumbing shared by every route module."""

from flask import request

from envelope import list_response, paginate
from errors import fail


def json_body():
    """Parse the JSON body. A malformed body is a shape failure, not a 500."""
    raw = request.get_json(silent=True, force=True)
    if raw is None:
        if request.get_data(as_text=True).strip():
            fail("ERR_VALIDATION", "Request body must be a valid JSON object.")
        return {}
    return raw


def page(rows, serializer, limit, offset):
    items, total = paginate(rows, limit, offset)
    return list_response([serializer(row) for row in items], limit, offset, total)

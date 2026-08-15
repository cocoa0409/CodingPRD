"""Shared route helpers: pagination, empty-body guard, archived-program guard."""

from flask import request

from envelope import ok_list
from errors import raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from validate import get_body
from store import by_seq


def paginate(records, view):
    """limit/offset pagination with defaults 10/0, clamped to [1,100] / [0,inf)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    ordered = by_seq(records)
    total = len(ordered)
    page = ordered[offset : offset + limit]
    return ok_list([view(r) for r in page], limit, offset, total)


def empty_body():
    """Action endpoints with no declared input reject any body field (P0)."""
    body = get_body()
    if body:
        raise_err(ERR_INVALID_REQUEST, "undeclared field: %s" % sorted(body)[0])


def guard_program_writable(program):
    """An ARCHIVED program is read-only: writes to it or its children fail (P6)."""
    if program is not None and program["status"] == "ARCHIVED":
        raise_err(ERR_INVALID_STATE, "program is archived (read-only)")

"""Shared route helpers: pagination, filtering and serialization."""

import db
from errors import ApiError
from response import ListPayload

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def limit_offset(ctx):
    limit = ctx.q_int("limit", DEFAULT_LIMIT)
    offset = ctx.q_int("offset", DEFAULT_OFFSET)
    if limit is None:
        limit = DEFAULT_LIMIT
    if limit < MIN_LIMIT or limit > MAX_LIMIT:
        raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", "offset may not be negative")
    return limit, offset


def paginate(ctx, records):
    """Order by creation timestamp ascending, then page."""
    rows = db.creation_order(records)
    total = len(rows)
    limit, offset = limit_offset(ctx)
    page = rows[offset : offset + limit]
    return ListPayload([db.public(r) for r in page], limit, offset, total)


def serial(record):
    return db.public(record)


def filtered(records, ctx, mapping):
    """mapping: query parameter name -> record field name."""
    out = list(records)
    for param, field in mapping.items():
        want = ctx.q(param)
        if want is None:
            continue
        out = [r for r in out if str(r.get(field)) == str(want)]
    return out


def in_window(instant, start, end):
    if instant is None:
        return False
    if start is not None and instant < start:
        return False
    if end is not None and not (instant < end):
        return False
    return True
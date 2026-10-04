"""Shared helpers: ISO parsing, pagination, month arithmetic, rounding, validation."""
import calendar
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import errors as E
import db


def parse_iso(value, field="timestamp"):
    """Parse an ISO8601 UTC datetime string. Raises ERR_INVALID_REQUEST on failure."""
    if not isinstance(value, str):
        raise E.err(E.ERR_INVALID_REQUEST, f"{field} must be an ISO8601 string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise E.err(E.ERR_INVALID_REQUEST, f"{field} is not a valid ISO8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_months(dt, months):
    """Add whole calendar months, clamping to the last day of the target month."""
    total = (dt.year * 12 + (dt.month - 1)) + months
    year = total // 12
    month = total % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def round_half_up_cents(value):
    """Round a Decimal/float ratio to whole cents, half-up. Returns int."""
    d = Decimal(str(value)) if not isinstance(value, Decimal) else value
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def get_body(required=None):
    """Return JSON body ({} when absent). Never raises on missing body."""
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise E.err(E.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    if required:
        for f in required:
            if body.get(f) is None:
                raise E.err(E.ERR_INVALID_REQUEST, f"Missing required field: {f}")
    return body


def pagination_params():
    """Parse limit/offset query params per scaffold defaults."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise E.err(E.ERR_INVALID_REQUEST, "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise E.err(E.ERR_INVALID_REQUEST, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise E.err(E.ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset < 0:
        raise E.err(E.ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def list_response(store, filters, serialize, status_filter_field="status"):
    """Shared list handler: filter by query params, sort by created_at asc, paginate."""
    limit, offset = pagination_params()
    items = list(store.values())
    for key, value in filters.items():
        if value is not None:
            items = [r for r in items if str(r.get(key)) == str(value)]
    items.sort(key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    total = len(items)
    page = items[offset:offset + limit]
    from response import success_list
    return success_list([serialize(r) for r in page], total, limit, offset)


def get_or_404(store, rid):
    rec = store.get(rid)
    if rec is None:
        raise E.err(E.ERR_NOT_FOUND, f"Resource not found: {rid}")
    return rec


def year_of(iso_ts):
    return int(iso_ts[0:4])

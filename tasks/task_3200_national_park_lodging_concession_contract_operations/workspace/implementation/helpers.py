"""Shared helpers: ids, timestamps, rounding, pagination, field validation."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import store
from errors import err


def new_id():
    return str(uuid.uuid4())


def ts_now():
    """Timestamps follow the server's logical clock, never the wall clock."""
    dt = store.clock
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value, field="datetime"):
    """Parse an ISO 8601 datetime string to an aware datetime (UTC)."""
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", 400, f"{field} must be an ISO 8601 string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", 400, f"{field} must be an ISO 8601 string")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def round_half_up(x):
    """Round a Decimal-compatible value to integer, half-up."""
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def touch(entity):
    entity["updated_at"] = ts_now()
    entity["version"] = entity.get("version", 1) + 1


def new_entity(extra):
    base = {
        "id": new_id(),
        "created_at": ts_now(),
        "updated_at": ts_now(),
        "version": 1,
        "_seq": store.next_seq(),  # stable creation ordering
    }
    base.update(extra)
    return base


def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def paginate(items):
    from flask import request
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", 400, "limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise err("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    if offset < 0:
        raise err("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    items = sorted(items, key=lambda e: e["_seq"])
    total = len(items)
    page = items[offset:offset + limit]
    return [serialize(e) for e in page], limit, offset, total


def require_fields(body, fields):
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", 400, "JSON body required")
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", 400, f"missing field: {f}")


def req_int(body, field, minimum=None, maximum=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", 400, f"{field} must be an integer")
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", 400, f"{field} out of range")
    if maximum is not None and v > maximum:
        raise err("ERR_INVALID_REQUEST", 400, f"{field} out of range")
    return v


def req_enum(body, field, values):
    v = body.get(field)
    if v not in values:
        raise err("ERR_INVALID_REQUEST", 400, f"{field} must be one of {sorted(values)}")
    return v


def add_months(dt, months):
    """Advance a datetime by N whole months (clamping day)."""
    m = dt.month - 1 + months
    y = dt.year + m // 12
    mo = m % 12 + 1
    # days per month
    if mo == 12:
        next_first = datetime(y + 1, 1, 1, tzinfo=dt.tzinfo)
    else:
        next_first = datetime(y, mo + 1, 1, tzinfo=dt.tzinfo)
    this_first = datetime(y, mo, 1, tzinfo=dt.tzinfo)
    dim = (next_first - this_first).days
    day = min(dt.day, dim)
    return dt.replace(year=y, month=mo, day=day)


def months_between(start, end):
    """Whole months elapsed between two datetimes, floor (>= 0)."""
    if end < start:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    anchor = add_months(start, months)
    if anchor > end:
        months -= 1
    return max(0, months)


def contract_month_offset(contract):
    return months_between(parse_dt(contract["start_date"]), store.clock)

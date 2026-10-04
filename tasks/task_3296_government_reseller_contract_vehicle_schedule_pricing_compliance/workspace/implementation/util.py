"""Envelope helpers, timestamps, parsing, pagination, entity construction."""
import random
import string
import re
from datetime import datetime, timedelta, timezone

from flask import request

from errors import err, ERR_INVALID_PRICE_PERIOD

ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(\.\d+)?(Z|[+-]\d{2}:?\d{2})$")
PERIOD_RE = re.compile(r"^(\d{4})-(\d{2})$")
DUNS_RE = re.compile(r"^\d{9}$")


def gen_req_id():
    return "req_" + "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(20))


def wall_ts():
    """Wall-clock ISO-8601 UTC with 3 fractional digits (request meta / entity timestamps)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:23] + "Z"


def parse_iso(s):
    if not isinstance(s, str):
        return None
    m = ISO_RE.match(s)
    if not m:
        return None
    y, mo, d, h, mi, sec, frac, tz = m.groups()
    if frac:
        fs = frac[1:]
        if len(fs) < 6:
            fs = fs.ljust(6, "0")
        else:
            fs = fs[:6]
        frac = "." + fs
    else:
        frac = ""
    if tz == "Z":
        tz = "+00:00"
    elif len(tz) == 5:  # +0000 -> +00:00
        tz = tz[:3] + ":" + tz[3:]
    try:
        dt = datetime.fromisoformat(f"{y}-{mo}-{d}T{h}:{mi}:{sec}{frac}{tz}")
    except (ValueError, TypeError):
        return None
    return dt.astimezone(timezone.utc)


def fmt_iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:23] + "Z"


def now_logical(db):
    return parse_iso(db.logical_clock)


def envelope(data, status=200, page=None):
    meta = {"api_request_id": gen_req_id(), "api_request_timestamp": wall_ts()}
    if page is not None:
        meta["limit"] = page["limit"]
        meta["offset"] = page["offset"]
        meta["total_count"] = page["total_count"]
        meta["has_more"] = page["has_more"]
    body = {
        "meta": meta,
        "response_type": "array" if page is not None else "object",
        "data": data,
    }
    return body, status


def error_body(error_id, message):
    return {
        "meta": {"api_request_id": gen_req_id(), "api_request_timestamp": wall_ts()},
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def get_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def body_arg(name, default=None):
    return get_body().get(name, default)


def body_has(name):
    return name in get_body()


def parse_limit_offset():
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def page_result(items, limit, offset):
    total = len(items)
    sliced = items[offset:offset + limit]
    return sliced, {"limit": limit, "offset": offset, "total_count": total,
                    "has_more": offset + len(sliced) < total}


def respond_list(items):
    limit, offset = parse_limit_offset()
    items = sorted(items, key=lambda e: e.get("created_at", ""))
    sliced, page = page_result(items, limit, offset)
    return envelope(sliced, 200, page)


def require_period_label(v):
    m = PERIOD_RE.match(v) if isinstance(v, str) else None
    if not m:
        raise err(ERR_INVALID_PRICE_PERIOD, "period_label must be YYYY-MM", 422)
    if not (1 <= int(m.group(2)) <= 12):
        raise err(ERR_INVALID_PRICE_PERIOD, "period_label must be YYYY-MM", 422)
    return v


def period_bounds(period_label):
    """Return (start_dt, end_dt) for a YYYY-MM period; end = first day of next month."""
    y, m = int(period_label[:4]), int(period_label[5:7])
    start = datetime(y, m, 1, tzinfo=timezone.utc)
    end = datetime(y + 1, 1, 1, tzinfo=timezone.utc) if m == 12 else datetime(y, m + 1, 1, tzinfo=timezone.utc)
    return start, end


def new_entity(db, store, input_fields, common=True, **extra):
    import uuid as _uuid
    e = {"id": str(_uuid.uuid4())}
    e.update(input_fields)
    e.update(extra)
    e["created_at"] = wall_ts()
    if common:
        e["updated_at"] = e["created_at"]
        e["version"] = 1
    store[e["id"]] = e
    return e


def bump(entity):
    """Mutation: refresh updated_at and increment version."""
    entity["updated_at"] = wall_ts()
    entity["version"] += 1

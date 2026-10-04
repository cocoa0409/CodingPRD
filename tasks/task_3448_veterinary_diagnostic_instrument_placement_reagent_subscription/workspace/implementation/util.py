"""Shared helpers: time, decimal rounding, envelope, pagination, auth."""
import calendar as _cal
import re
import uuid
from datetime import timezone, datetime
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

import db
from constants import ROLES
from errors import err

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


# ---------------------------------------------------------------- time helpers
def parse_iso(s):
    """Parse an ISO 8601 string into an aware UTC datetime. Raises ValueError."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits (audit fields)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def iso_z(dt):
    """Compact ISO 8601 UTC: drops the fractional part when zero."""
    if dt.microsecond:
        return iso_ms(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def add_months(dt, n):
    """Advance dt by n calendar months, keeping the day-of-month (clamped)."""
    m = dt.month - 1 + n
    y = dt.year + m // 12
    m = m % 12 + 1
    d = min(dt.day, _cal.monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=d)


def month_of(dt):
    return f"{dt.year:04d}-{dt.month:02d}"


def term_months(start, n):
    """The n YYYY-MM term months beginning at the month containing start."""
    return [month_of(add_months(start, i)) for i in range(n)]


# ------------------------------------------------------------- numeric helpers
def dec(x):
    return Decimal(str(x))


def round_cents(d):
    """round_half_up to whole integer cents."""
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round4(d):
    """round_half_up to exactly 4 decimal places."""
    return d.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


# ------------------------------------------------------------ request/response
def body():
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


def meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": iso_ms(db.now()),
    }


def ok(data, code=200):
    return jsonify({"meta": meta(), "response_type": "object", "data": data}), code


def ok_list(items, limit, offset, total):
    m = meta()
    m.update({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(items) < total,
    })
    return jsonify({"meta": m, "response_type": "array", "data": items}), 200


def ok_array(items):
    """Array response without pagination (the 1:1 results collection)."""
    return jsonify({"meta": meta(), "response_type": "array", "data": items}), 200


def page_params():
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(100, limit))
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    return limit, max(0, offset)


def paginate(items):
    limit, offset = page_params()
    total = len(items)
    return ok_list(items[offset:offset + limit], limit, offset, total)


def sorted_items(coll):
    """created_at ASC, ties broken by insertion order."""
    return sorted(coll, key=lambda e: (e["_created"], e["_seq"]))


# ---------------------------------------------------------------------- auth
def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers must both be present and "
            "X-User-Role must be one of the five declared roles",
        )
    return uid, role


def require(role, allowed):
    if role not in allowed:
        raise err("ERR_INSUFFICIENT_PERMISSIONS",
                  "role is not permitted for this endpoint")


def forbidden(msg="role is not permitted for this field or action"):
    raise err("ERR_INSUFFICIENT_PERMISSIONS", msg)

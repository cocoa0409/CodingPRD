"""Shared helpers: ids, timestamps, envelope, pagination, dates, validation."""
import uuid
from datetime import datetime, timezone, date

from flask import request, jsonify

from db import db
from errors import ApiError, ERR_VALIDATION, raise_err


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Logical-clock-based timestamp with 3 fractional digits."""
    dt = db.clock
    s = dt.strftime("%Y-%m-%dT%H:%M:%S.")
    ms = "%03d" % (dt.microsecond // 1000)
    return s + ms + "Z"


def request_timestamp_iso():
    """Wall clock timestamp for meta (server-generated request time)."""
    dt = datetime.now(timezone.utc)
    s = dt.strftime("%Y-%m-%dT%H:%M:%S.")
    return s + "%03dZ" % (dt.microsecond // 1000)


def current_date():
    return db.clock.date()


def current_datetime():
    return db.clock


def parse_date(s):
    """Parse YYYY-MM-DD -> date, or None."""
    if not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def parse_period(s):
    """Validate YYYY-MM."""
    if not isinstance(s, str):
        return False
    parts = s.split("-")
    if len(parts) != 2:
        return False
    try:
        y = int(parts[0]); m = int(parts[1])
    except ValueError:
        return False
    return len(parts[0]) == 4 and len(parts[1]) == 2 and 1 <= m <= 12


def parse_iso_datetime(s):
    if not isinstance(s, str):
        return None
    t = s
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_date_str(d):
    return d.strftime("%Y-%m-%d")


def months_between(d1, d2):
    """Whole months between two dates (d2 - d1), partial rounds DOWN."""
    if d2 < d1:
        return 0
    months = (d2.year - d1.year) * 12 + (d2.month - d1.month)
    if d2.day < d1.day:
        months -= 1
    return max(0, months)


def months_between_period(period, current):
    """Whole months between a YYYY-MM period and a date's month (partial down)."""
    y, m = int(period[:4]), int(period[5:7])
    months = (current.year - y) * 12 + (current.month - m)
    return max(0, months)


def add_days(d, n):
    from datetime import timedelta
    return d + timedelta(days=n)


def meta(pagination=None):
    m = {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": request_timestamp_iso(),
    }
    if pagination is not None:
        m.update(pagination)
    return m


def ok(data, status=200):
    body = {"meta": meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items):
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    pg = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    body = {"meta": meta(pg), "response_type": "array", "data": page}
    return jsonify(body), 200


def pagination_params():
    try:
        limit = int(request.args.get("limit", 10))
    except (ValueError, TypeError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def body():
    """Request JSON body (may be empty)."""
    if request.data:
        try:
            b = request.get_json(force=True, silent=True)
        except Exception:
            b = None
        if isinstance(b, dict):
            return b
        return {}
    return {}


def require_fields(b, fields, types=None):
    """Validate presence + type of required fields. Returns cleaned dict."""
    out = {}
    for f in fields:
        if f not in b:
            raise_err(ERR_VALIDATION, "Missing required field: %s" % f)
        v = b[f]
        if types and f in types:
            if not check_type(v, types[f]):
                raise_err(ERR_VALIDATION, "Invalid type for field: %s" % f)
        out[f] = v
    return out


def check_type(v, t):
    if t == "string":
        return isinstance(v, str)
    if t == "int":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "bool":
        return isinstance(v, bool)
    return True


def require_enum(v, allowed, field):
    if v not in allowed:
        raise_err(ERR_VALIDATION, "Invalid value for %s" % field)
    return v


def require_non_neg_int(v, field):
    if not (isinstance(v, int) and not isinstance(v, bool)) or v < 0:
        raise_err(ERR_VALIDATION, "%s must be a non-negative integer" % field)
    return v


def touch(entity, has_version=True):
    """Refresh updated_at and bump version on a mutated entity."""
    if "updated_at" in entity:
        entity["updated_at"] = now_iso()
    if has_version and "version" in entity:
        entity["version"] += 1


def new_common():
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def register_error_handlers(app):
    @app.errorhandler(ApiError)
    def handle_api_error(e):
        body = {
            "meta": meta(),
            "response_type": "error",
            "data": {"error_id": e.error_id, "message": e.message},
        }
        return jsonify(body), e.http_status

    @app.errorhandler(404)
    def handle_404(e):
        body = {
            "meta": meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
        }
        return jsonify(body), 404

    @app.errorhandler(405)
    def handle_405(e):
        body = {
            "meta": meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"},
        }
        return jsonify(body), 404

    @app.errorhandler(Exception)
    def handle_exc(e):
        if isinstance(e, ApiError):
            return handle_api_error(e)
        import traceback
        traceback.print_exc()
        body = {
            "meta": meta(),
            "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL", "message": str(e)},
        }
        return jsonify(body), 500

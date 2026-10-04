"""Shared helpers: timestamps, logical clock, payload validation, pagination, entity utils."""
import math
import re
import uuid
from datetime import datetime, date, timezone

from flask import request

import db
from errors import raise_err, ERR_INVALID_REQUEST, ERR_FK_NOT_FOUND, ERR_NOT_FOUND

_MISSING = object()

DT_FORMATS = (
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S.%fZ",
)


def parse_dt(value):
    """Parse an ISO-8601 UTC datetime string into an aware datetime."""
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise ValueError("not a datetime string")
    for fmt in DT_FORMATS:
        try:
            dt = datetime.strptime(value, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    # Fall back to fromisoformat for offsets etc.
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        raise ValueError(f"unparseable datetime: {value}")


def parse_date(value):
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise ValueError("not a date string")
    return datetime.strptime(value, "%Y-%m-%d").date()


def fmt_dt(dt):
    """Format an aware UTC datetime as ISO 8601 with three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def logical_now():
    """Current logical-clock instant as an aware datetime."""
    return parse_dt(db.get_clock())


def logical_now_str():
    return fmt_dt(logical_now())


def new_id():
    return str(uuid.uuid4())


def new_entity():
    now = logical_now_str()
    return {"id": new_id(), "created_at": now, "updated_at": now, "version": 1}


def touch(entity):
    entity["updated_at"] = logical_now_str()
    entity["version"] = entity.get("version", 1) + 1


def get_json_body():
    """Return parsed JSON body; raise ERR_INVALID_REQUEST if malformed JSON object."""
    if request.data is None or request.data == b"":
        return {}
    data = request.get_json(silent=True, force=False)
    if data is None or not isinstance(data, dict):
        raise_err(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return data


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and not (isinstance(value, float) and math.isnan(value)))


def check_type(field, value, ftype):
    """Validate a value against a declared type. Raise ERR_INVALID_REQUEST on mismatch."""
    ok = True
    if ftype == "string":
        ok = isinstance(value, str)
    elif ftype == "integer":
        ok = _is_int(value)
    elif ftype == "boolean":
        ok = isinstance(value, bool)
    elif ftype == "number":
        ok = _is_num(value)
    elif ftype == "datetime":
        ok = isinstance(value, str)
        if ok:
            try:
                parse_dt(value)
            except ValueError:
                ok = False
    elif ftype == "array":
        ok = isinstance(value, list)
    else:
        ok = True
    if not ok:
        raise_err(ERR_INVALID_REQUEST, f"field '{field}' has invalid type (expected {ftype})")
    return value


def require(body, field, ftype="string", enum=None, min_len=None, min_val=None,
            max_val=None, fk_store=None):
    if field not in body or body[field] is None:
        raise_err(ERR_INVALID_REQUEST, f"missing required field: {field}")
    value = body[field]
    check_type(field, value, ftype)
    if enum is not None and value not in enum:
        raise_err(ERR_INVALID_REQUEST, f"field '{field}' must be one of {sorted(enum)}")
    if ftype == "string" and min_len is not None and len(value) < min_len:
        raise_err(ERR_INVALID_REQUEST, f"field '{field}' is too short")
    if ftype == "integer" and min_val is not None and value < min_val:
        raise_err(ERR_INVALID_REQUEST, f"field '{field}' below minimum {min_val}")
    if ftype == "integer" and max_val is not None and value > max_val:
        raise_err(ERR_INVALID_REQUEST, f"field '{field}' above maximum {max_val}")
    if fk_store is not None:
        store = db.STORES[fk_store]
        if value not in store:
            raise_err(ERR_FK_NOT_FOUND, f"unresolvable foreign key: {field}={value}")
    return value


def optional(body, field, default=None, ftype=None, enum=None):
    if field not in body or body[field] is None:
        return default
    value = body[field]
    if ftype is not None:
        check_type(field, value, ftype)
    if enum is not None and value not in enum:
        raise_err(ERR_INVALID_REQUEST, f"field '{field}' must be one of {sorted(enum)}")
    return value


def pagination_params():
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
    return limit, offset


def list_response(items, filters=None):
    """Filter, sort by created_at asc, paginate. Returns (page, total_count, limit, offset)."""
    result = list(items)
    if filters:
        for key, want in filters.items():
            if want is None:
                continue
            result = [r for r in result if r.get(key) == want]
    result.sort(key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    total = len(result)
    limit, offset = pagination_params()
    return result[offset:offset + limit], total, limit, offset


def parse_geo_point(geo):
    """Parse a WGS84 GeoJSON point string into (lon, lat). Returns None on failure."""
    import json
    if not isinstance(geo, str) or not geo.strip():
        return None
    try:
        obj = json.loads(geo)
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None
    if obj.get("type") == "Point" and isinstance(obj.get("coordinates"), list):
        coords = obj["coordinates"]
        if len(coords) >= 2 and all(_is_num(c) for c in coords[:2]):
            return float(coords[0]), float(coords[1])
    return None


def parse_geo_polygon(poly):
    """Parse a GeoJSON polygon string into a list of (lon, lat) exterior ring points."""
    import json
    if not isinstance(poly, str) or not poly.strip():
        return []
    try:
        obj = json.loads(poly)
    except (ValueError, TypeError):
        return []
    if not isinstance(obj, dict) or obj.get("type") != "Polygon":
        return []
    coords = obj.get("coordinates")
    if not isinstance(coords, list) or not coords:
        return []
    ring = coords[0]
    if not isinstance(ring, list):
        return []
    pts = []
    for p in ring:
        if isinstance(p, list) and len(p) >= 2 and all(_is_num(c) for c in p[:2]):
            pts.append((float(p[0]), float(p[1])))
    return pts


def point_in_polygon(point, ring):
    """Ray-casting point-in-polygon; boundary counts as inside."""
    if point is None or not ring or len(ring) < 3:
        return False
    x, y = point
    # boundary check
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
        if abs(cross) < 1e-9:
            if (min(x1, x2) - 1e-9 <= x <= max(x1, x2) + 1e-9 and
                    min(y1, y2) - 1e-9 <= y <= max(y1, y2) + 1e-9):
                return True
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y):
            xint = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < xint:
                inside = not inside
        j = i
    return inside


def age_years(dob, at):
    """Whole years between a date_of_birth date and a datetime, per PRD floor(days/365.25)."""
    if isinstance(at, datetime):
        at_date = at.date()
    else:
        at_date = at
    days = (at_date - dob).days
    return math.floor(days / 365.25)


def redact(entity, fields):
    return {k: v for k, v in entity.items() if k not in fields}

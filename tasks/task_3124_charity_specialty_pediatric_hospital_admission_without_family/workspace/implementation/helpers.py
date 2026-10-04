"""Shared helpers: ids, timestamps, request-body field validation, age math."""

import math
import uuid
from datetime import datetime, timezone

from errors import bad_request


def new_id():
    return str(uuid.uuid4())


def now_iso():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def touch(rec):
    """Refresh updated_at and increment version on a mutated resource."""
    rec["updated_at"] = now_iso()
    rec["version"] += 1


def get_body():
    from flask import request
    data = request.get_json(silent=True)
    if data is None:
        if request.data:
            raise bad_request("Request body must be valid JSON")
        return {}
    if not isinstance(data, dict):
        raise bad_request("Request body must be a JSON object")
    return data


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return ((isinstance(v, (int, float)) and not isinstance(v, bool))
            and math.isfinite(v))


def req_str(body, field):
    v = body.get(field)
    if v is None:
        raise bad_request(f"Missing required field: {field}")
    if not isinstance(v, str) or v == "":
        raise bad_request(f"Field {field} must be a non-empty string")
    return v


def opt_str(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, str) or v == "":
        raise bad_request(f"Field {field} must be a non-empty string")
    return v


def req_int(body, field, minimum=None):
    v = body.get(field)
    if v is None:
        raise bad_request(f"Missing required field: {field}")
    if not is_int(v):
        raise bad_request(f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        raise bad_request(f"Field {field} must be >= {minimum}")
    return v


def opt_int(body, field, default=None, minimum=None):
    v = body.get(field)
    if v is None:
        return default
    if not is_int(v):
        raise bad_request(f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        raise bad_request(f"Field {field} must be >= {minimum}")
    return v


def req_num(body, field, minimum=None, maximum=None):
    v = body.get(field)
    if v is None:
        raise bad_request(f"Missing required field: {field}")
    if not is_num(v):
        raise bad_request(f"Field {field} must be a number")
    v = float(v)
    if minimum is not None and v < minimum:
        raise bad_request(f"Field {field} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise bad_request(f"Field {field} must be <= {maximum}")
    return v


def req_bool(body, field):
    v = body.get(field)
    if v is None:
        raise bad_request(f"Missing required field: {field}")
    if not isinstance(v, bool):
        raise bad_request(f"Field {field} must be a boolean")
    return v


def opt_bool(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise bad_request(f"Field {field} must be a boolean")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None:
        raise bad_request(f"Missing required field: {field}")
    if not isinstance(v, str) or v not in allowed:
        raise bad_request(f"Field {field} must be one of {sorted(allowed)}")
    return v


def opt_enum(body, field, allowed, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, str) or v not in allowed:
        raise bad_request(f"Field {field} must be one of {sorted(allowed)}")
    return v


def parse_dt(value, field="datetime"):
    """Parse an ISO 8601 datetime string into an aware UTC datetime."""
    if not isinstance(value, str):
        raise bad_request(f"Field {field} must be an ISO 8601 datetime string")
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        raise bad_request(f"Field {field} must be an ISO 8601 datetime string")
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def req_dt(body, field):
    v = body.get(field)
    if v is None:
        raise bad_request(f"Missing required field: {field}")
    return parse_dt(v, field)


def iso_date(dt):
    """Serialize a business datetime at 00:00:00Z date granularity (no fractional digits).
    Business date-time fields echo client input format; only created_at/updated_at
    carry three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def months_between(dob, at):
    """Whole months elapsed from dob to `at` (floor). Both datetimes at date granularity."""
    m = (at.year - dob.year) * 12 + (at.month - dob.month)
    if at.day < dob.day:
        m -= 1
    return m


def haversine_miles(lat1, lon1, lat2, lon2):
    """Great-circle distance in miles, earth radius 3958.8 (PRD §3.7)."""
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2)
    a = min(1.0, max(0.0, a))
    return r * 2 * math.asin(math.sqrt(a))

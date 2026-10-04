"""Shared utilities: ids, timestamps, serialization, pagination, field validation."""

import uuid
from datetime import datetime, timezone, date

import db
from errors import invalid_request, not_found, stale_version


def new_id():
    return str(uuid.uuid4())


def now_iso():
    return db.utcnow().isoformat(timespec="milliseconds").replace("+00:00", "Z")


def logical_iso():
    return db.clock_now().isoformat(timespec="milliseconds").replace("+00:00", "Z")


def logical_date():
    return db.clock_now().date()


def parse_datetime(value, field):
    """Parse an ISO8601 string; returns aware UTC datetime. Shape error otherwise."""
    if not isinstance(value, str):
        raise invalid_request("Field '%s' must be an ISO8601 datetime string" % field)
    v = value
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except (ValueError, TypeError):
        raise invalid_request("Field '%s' is not a valid ISO8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_out(dt):
    """Serialize a datetime to ISO8601 with Z suffix."""
    if dt is None:
        return None
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def touch(entity):
    """Standard mutation bookkeeping: updated_at refresh + version +1."""
    entity["updated_at"] = now_iso()
    entity["version"] = int(entity.get("version", 0)) + 1


def base_entity():
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


# ---------------- pagination ----------------

def pagination_params():
    from flask import request
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise invalid_request("limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid_request("offset must be an integer")
        if offset < 0:
            raise invalid_request("offset must be >= 0")
    return limit, offset


def paginate(items):
    """Sort by created_at ascending and slice."""
    limit, offset = pagination_params()
    items = sorted(items, key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


# ---------------- body helpers ----------------

def get_json_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise invalid_request("Request body must be a JSON object")
    return body


def req_field(body, name):
    if name not in body or body[name] is None:
        raise invalid_request("Missing required field: %s" % name)
    return body[name]


def req_string(body, name):
    v = req_field(body, name)
    if not isinstance(v, str):
        raise invalid_request("Field '%s' must be a string" % name)
    return v


def req_int(body, name):
    v = req_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid_request("Field '%s' must be an integer" % name)
    return v


def req_number(body, name):
    v = req_field(body, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise invalid_request("Field '%s' must be a number" % name)
    return v


def req_bool(body, name):
    v = req_field(body, name)
    if not isinstance(v, bool):
        raise invalid_request("Field '%s' must be a boolean" % name)
    return v


def req_list(body, name):
    v = req_field(body, name)
    if not isinstance(v, list):
        raise invalid_request("Field '%s' must be an array" % name)
    return v


def opt_bool(body, name, default):
    if name not in body or body[name] is None:
        return default
    return req_bool(body, name)


def check_occ(body, parent, expected_field, parent_label):
    """OCC: expected_<parent>_version must be present and match."""
    if expected_field not in body or body[expected_field] is None:
        raise invalid_request("Missing required field: %s" % expected_field)
    v = body[expected_field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid_request("Field '%s' must be an integer" % expected_field)
    if v != parent["version"]:
        raise stale_version(
            "%s version mismatch: expected %s but current is %s"
            % (parent_label, v, parent["version"])
        )


def weekday_of_date(d):
    """0=Monday .. 6=Sunday for a date."""
    return d.weekday()


def calendar_days_between(start_dt, end_dt):
    """Whole calendar days between two datetimes (date distance)."""
    return (end_dt.date() - start_dt.date()).days

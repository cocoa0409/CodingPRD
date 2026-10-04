"""Shared entity helpers: timestamps, UUIDs, common-field minting."""

import re
import uuid
from datetime import datetime, date, timezone

import db
from errors import ApiError


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Current wall-clock timestamp with millisecond precision, ISO 8601 UTC."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + dt.strftime("%f")[:3] + "Z"


def new_entity(extra_fields=None):
    """Mint the common fields for a fresh entity."""
    ts = now_iso()
    ent = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    if extra_fields:
        ent.update(extra_fields)
    return ent


def touch(entity):
    """Refresh updated_at and bump version on a mutated entity."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


def get_or_404(collection, entity_id, error_id, label):
    ent = collection.get(entity_id)
    if ent is None:
        raise ApiError(error_id, f"{label} id does not exist", 404)
    return ent


def body():
    """Parse JSON request body; tolerate empty body for POSTs with no fields."""
    from flask import request

    if request.content_length is None or request.content_length == 0:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    return data


def logical_clock_date():
    """Return the logical clock's current date as a datetime.date."""
    ts = db.current_utc
    return parse_datetime(ts).date()


def logical_clock_iso():
    """Return the logical clock's current instant as ISO8601 with ms."""
    dt = parse_datetime(db.current_utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + dt.strftime("%f")[:3] + "Z"


def parse_datetime(value):
    """Parse an ISO8601 string with Z suffix or offset into an aware datetime."""
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_date(value):
    return date.fromisoformat(value)


def iso_week_key(d):
    """ISO week key (year, week) for a date."""
    iso = d.isocalendar()
    return (iso[0], iso[1])


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def require_field(data, name, expected_type=None, allow_null=False):
    """Pull a field out of the request body, enforcing presence and type.

    Missing or wrongly-typed required fields surface as ERR_VALIDATION (422).
    """
    if name not in data:
        raise ApiError("ERR_VALIDATION", f"Missing required field: {name}", 422)
    value = data[name]
    if value is None and allow_null:
        return None
    if expected_type is not None:
        if expected_type is int and isinstance(value, bool):
            raise ApiError("ERR_VALIDATION", f"Field {name} must be an integer", 422)
        if expected_type is bool:
            if not isinstance(value, bool):
                raise ApiError("ERR_VALIDATION", f"Field {name} must be a boolean", 422)
        elif not isinstance(value, expected_type):
            raise ApiError(
                "ERR_VALIDATION",
                f"Field {name} must be of type {expected_type.__name__}",
                422,
            )
    return value


def require_date(data, name):
    value = require_field(data, name, str)
    if not _DATE_RE.match(value):
        raise ApiError("ERR_VALIDATION", f"Field {name} must be YYYY-MM-DD", 422)
    try:
        parse_date(value)
    except ValueError:
        raise ApiError("ERR_VALIDATION", f"Field {name} must be a valid date", 422)
    return value


def require_time_hhmm(data, name):
    value = require_field(data, name, str)
    if not _HHMM_RE.match(value):
        raise ApiError("ERR_VALIDATION", f"Field {name} must be HH:MM", 422)
    return value


def require_enum(data, name, allowed):
    value = require_field(data, name, str)
    if value not in allowed:
        raise ApiError(
            "ERR_VALIDATION",
            f"Field {name} must be one of {sorted(allowed)}",
            422,
        )
    return value


def require_positive_int(data, name, minimum=1):
    value = require_field(data, name, int)
    if value < minimum:
        raise ApiError(
            "ERR_VALIDATION", f"Field {name} must be >= {minimum}", 422
        )
    return value


def check_occ(data, field_name, entity):
    """Optimistic concurrency: supplied expected_*_version must match current.

    The field is mandatory on the three OCC endpoints; a missing field is a
    validation error. A mismatched one is ERR_STALE_VERSION (412).
    """
    if field_name not in data:
        raise ApiError(
            "ERR_VALIDATION", f"Missing required field: {field_name}", 422
        )
    supplied = data[field_name]
    if not isinstance(supplied, int) or isinstance(supplied, bool):
        raise ApiError(
            "ERR_VALIDATION", f"Field {field_name} must be an integer", 422
        )
    if supplied != entity["version"]:
        from errors import stale_version

        raise stale_version()

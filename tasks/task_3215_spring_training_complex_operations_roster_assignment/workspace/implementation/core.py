"""Errors, response envelope, clock arithmetic and shared record helpers."""

import random
import string
from datetime import datetime, timedelta, timezone

# --------------------------------------------------------------------------
# Error identifiers (scaffold section 1.6 / PRD section 5)
# --------------------------------------------------------------------------

ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
ERR_SOD_VIOLATION = "ERR_SOD_VIOLATION"
ERR_RESOURCE_NOT_FOUND = "ERR_RESOURCE_NOT_FOUND"
ERR_FOREIGN_KEY_NOT_FOUND = "ERR_FOREIGN_KEY_NOT_FOUND"
ERR_ROSTER_STATUS_INVALID_TRANSITION = "ERR_ROSTER_STATUS_INVALID_TRANSITION"
ERR_ROSTER_ALREADY_FINAL = "ERR_ROSTER_ALREADY_FINAL"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_OUTSIDE_WINDOW = "ERR_OUTSIDE_WINDOW"
ERR_PHYSICAL_WINDOW_LEAD = "ERR_PHYSICAL_WINDOW_LEAD"
ERR_MEDICAL_CLEARANCE_REQUIRED = "ERR_MEDICAL_CLEARANCE_REQUIRED"
ERR_INJURY_TRAVEL_UNSAFE = "ERR_INJURY_TRAVEL_UNSAFE"
ERR_MAINTENANCE_CONFLICT = "ERR_MAINTENANCE_CONFLICT"
ERR_TEMPORAL_OVERLAP = "ERR_TEMPORAL_OVERLAP"
ERR_PHYSICAL_DOUBLE_BOOKED = "ERR_PHYSICAL_DOUBLE_BOOKED"
ERR_GROUP_CAPACITY_EXCEEDED = "ERR_GROUP_CAPACITY_EXCEEDED"
ERR_PLAYER_ALREADY_ASSIGNED = "ERR_PLAYER_ALREADY_ASSIGNED"
ERR_BUCKET_MISMATCH = "ERR_BUCKET_MISMATCH"
ERR_TRAVEL_RADIUS_EXCEEDED = "ERR_TRAVEL_RADIUS_EXCEEDED"
ERR_DUPLICATE_IDP_NUMBER = "ERR_DUPLICATE_IDP_NUMBER"
ERR_THROW_REQUIREMENT_UNMET = "ERR_THROW_REQUIREMENT_UNMET"
ERR_WAIVER_WINDOW_EXPIRED = "ERR_WAIVER_WINDOW_EXPIRED"
ERR_FARM_ENTITY_EXCLUDED = "ERR_FARM_ENTITY_EXCLUDED"
ERR_AGREEMENT_NOT_ACTIVE = "ERR_AGREEMENT_NOT_ACTIVE"
ERR_INVITATION_LETTER_MISSING = "ERR_INVITATION_LETTER_MISSING"
ERR_SPONSORSHIP_NOT_FULLY_FUNDED = "ERR_SPONSORSHIP_NOT_FULLY_FUNDED"
ERR_AGREEMENT_UNDERFUNDED = "ERR_AGREEMENT_UNDERFUNDED"
ERR_POSTURE_BLOCKS_FISCAL = "ERR_POSTURE_BLOCKS_FISCAL"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_STALE_VERSION = "ERR_STALE_VERSION"

ERROR_STATUS = {
    ERR_UNAUTHENTICATED: 401,
    ERR_UNAUTHORIZED: 403,
    ERR_SOD_VIOLATION: 403,
    ERR_RESOURCE_NOT_FOUND: 404,
    ERR_FOREIGN_KEY_NOT_FOUND: 404,
    ERR_ROSTER_STATUS_INVALID_TRANSITION: 409,
    ERR_ROSTER_ALREADY_FINAL: 409,
    ERR_INVALID_STATE: 409,
    ERR_OUTSIDE_WINDOW: 422,
    ERR_PHYSICAL_WINDOW_LEAD: 422,
    ERR_MEDICAL_CLEARANCE_REQUIRED: 422,
    ERR_INJURY_TRAVEL_UNSAFE: 422,
    ERR_MAINTENANCE_CONFLICT: 409,
    ERR_TEMPORAL_OVERLAP: 409,
    ERR_PHYSICAL_DOUBLE_BOOKED: 409,
    ERR_GROUP_CAPACITY_EXCEEDED: 409,
    ERR_PLAYER_ALREADY_ASSIGNED: 409,
    ERR_BUCKET_MISMATCH: 422,
    ERR_TRAVEL_RADIUS_EXCEEDED: 422,
    ERR_DUPLICATE_IDP_NUMBER: 409,
    ERR_THROW_REQUIREMENT_UNMET: 422,
    ERR_WAIVER_WINDOW_EXPIRED: 409,
    ERR_FARM_ENTITY_EXCLUDED: 409,
    ERR_AGREEMENT_NOT_ACTIVE: 409,
    ERR_INVITATION_LETTER_MISSING: 409,
    ERR_SPONSORSHIP_NOT_FULLY_FUNDED: 422,
    ERR_AGREEMENT_UNDERFUNDED: 402,
    ERR_POSTURE_BLOCKS_FISCAL: 409,
    ERR_INVALID_REQUEST: 400,
    ERR_STALE_VERSION: 412,
}


class ApiError(Exception):
    def __init__(self, error_id, message="Request refused."):
        Exception.__init__(self, message)
        self.error_id = error_id
        self.message = message
        self.http_status = ERROR_STATUS.get(error_id, 400)


def bad(message="Request is structurally invalid."):
    return ApiError(ERR_INVALID_REQUEST, message)


# --------------------------------------------------------------------------
# Response envelope
# --------------------------------------------------------------------------

def _request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(18))


def stamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        "%03dZ" % (datetime.now(timezone.utc).microsecond // 1000)


def envelope(response_type, data, request_id=None):
    return {
        "meta": {
            "api_request_id": request_id or _request_id(),
            "api_request_timestamp": stamp(),
        },
        "response_type": response_type,
        "data": data if data is not None else {},
    }


def list_envelope(data, limit, offset, total_count, request_id=None):
    body = envelope("array", data, request_id)
    body["meta"]["limit"] = limit
    body["meta"]["offset"] = offset
    body["meta"]["total_count"] = total_count
    body["meta"]["has_more"] = (offset + len(data)) < total_count
    return body


def error_envelope(err, request_id=None):
    return envelope("error", {"error_id": err.error_id, "message": err.message},
                    request_id)


# --------------------------------------------------------------------------
# Datetime helpers
# --------------------------------------------------------------------------

def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value, field="datetime"):
    if value is None:
        raise bad("Missing %s." % field)
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z") or text.endswith("z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            raise bad("Field %s is not a valid ISO 8601 instant." % field)
    else:
        raise bad("Field %s is not a valid ISO 8601 instant." % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def truncate_midnight(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def truncate_minute(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.replace(second=0, microsecond=0)


def business_days(start, end):
    """Whole-day span, start-inclusive and end-exclusive; never negative."""
    if start is None or end is None:
        return 0
    return max(0, (end.date() - start.date()).days)


def spend_days(dt, days):
    return dt + timedelta(days=days)


# --------------------------------------------------------------------------
# Common record helpers
# --------------------------------------------------------------------------

def touch(record, clock, bump_version=True):
    record["updated_at"] = fmt(clock)
    if bump_version:
        record["version"] = record.get("version", 0) + 1


def new_record(record_id, clock):
    now = fmt(clock)
    return {
        "id": record_id,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def require_int(body, field, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        raise bad("Missing required field %s." % field)
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad("Field %s must be an integer." % field)
    if isinstance(value, float):
        if value != int(value):
            raise bad("Field %s must be an integer." % field)
        value = int(value)
    if minimum is not None and value < minimum:
        raise bad("Field %s is below its permitted minimum." % field)
    if maximum is not None and value > maximum:
        raise bad("Field %s is above its permitted maximum." % field)
    return value


def require_str(body, field):
    if field not in body or body[field] is None:
        raise bad("Missing required field %s." % field)
    value = body[field]
    if not isinstance(value, str) or not value.strip():
        raise bad("Field %s must be a non-empty string." % field)
    return value


def optional_int(body, field, default, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        return default
    return require_int(body, field, minimum, maximum)


def require_enum(body, field, allowed):
    value = require_str(body, field)
    if value not in allowed:
        raise bad("Field %s carries an unrecognized value." % field)
    return value


def enum_or_default(body, field, default, allowed):
    if field not in body or body[field] is None:
        return default
    return require_enum(body, field, allowed)


SERVER_MINTED_FIELDS = (
    "id",
    "created_at",
    "updated_at",
    "version",
    "posted_occupancy_units",
    "reserved_major_units",
    "reserved_minor_units",
    "maintenance_block_units",
    "facility_posture",
    "contention_flagged",
    "posture_sweep_index",
)


def reject_server_minted(body, extra=()):
    """Structural guard: `id`, the timestamps and every derived read are
    server-minted and are never accepted as client inputs."""
    for field in SERVER_MINTED_FIELDS + tuple(extra):
        if field in body:
            raise bad("Field %s is server-minted and may not be supplied." % field)


def require_number(body, field, minimum=None):
    if field not in body or body[field] is None:
        raise bad("Missing required field %s." % field)
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad("Field %s must be a number." % field)
    value = float(value)
    if minimum is not None and value < minimum:
        raise bad("Field %s is below its permitted minimum." % field)
    return value


def optional_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    value = body[field]
    if not isinstance(value, bool):
        raise bad("Field %s must be a boolean." % field)
    return value


def upper_snake(text):
    out = []
    pending_sep = False
    for ch in text.strip():
        if ch.isalnum():
            if pending_sep and out:
                out.append("_")
            out.append(ch.upper())
            pending_sep = False
        else:
            pending_sep = True
    return "".join(out)
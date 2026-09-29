"""Core infrastructure for the Venue Event-Day Staffing & Guest Services API.

Holds the in-memory store, the logical clock, the response envelope, the error
catalogue and the request-validation helpers.  Nothing is seeded here: the store
starts completely empty on every boot.
"""

import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from flask import jsonify, request

UTC = timezone.utc

# §2.4 - the logical clock reads exactly this instant before any client sets it.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

COLLECTIONS = [
    "events",
    "position_types",
    "staffing_plans",
    "position_slots",
    "staff_members",
    "certifications",
    "shift_bids",
    "staff_assignments",
    "backfill_requests",
    "guest_issues",
    "accessibility_resources",
    "accessibility_requests",
    "satisfaction_responses",
]

ROLES = (
    "GuestExperienceDirector",
    "StaffingCoordinator",
    "GuestServicesSupervisor",
    "StaffMember",
)


class DB(object):
    """Plain in-memory store: one dict per collection, keyed by id."""

    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_DEFAULT
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()


def now():
    return db.clock


def set_clock(value):
    db.clock = value


# ---------------------------------------------------------------------------
# errors
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=None):
    return ApiError(error_id, http_status, message)


def unauthenticated(msg="Authentication headers are missing or invalid."):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def role_not_permitted(msg="The acting role may not perform this operation."):
    return ApiError("ERR_ROLE_NOT_PERMITTED", 403, msg)


def not_owner(msg="The acting worker does not own this resource."):
    return ApiError("ERR_NOT_RESOURCE_OWNER", 403, msg)


def invalid(msg="Request validation failed."):
    return ApiError("ERR_VALIDATION_FAILED", 422, msg)


def bad_window(msg="Interval fields are not strictly ordered."):
    return ApiError("ERR_INVALID_TIME_WINDOW", 422, msg)


def conflict(error_id, msg=None):
    return ApiError(error_id, 409, msg or error_id)


NOT_FOUND_IDS = {
    "events": "ERR_EVENT_NOT_FOUND",
    "position_types": "ERR_POSITION_TYPE_NOT_FOUND",
    "staffing_plans": "ERR_STAFFING_PLAN_NOT_FOUND",
    "position_slots": "ERR_POSITION_SLOT_NOT_FOUND",
    "staff_members": "ERR_STAFF_MEMBER_NOT_FOUND",
    "certifications": "ERR_CERTIFICATION_NOT_FOUND",
    "shift_bids": "ERR_SHIFT_BID_NOT_FOUND",
    "staff_assignments": "ERR_STAFF_ASSIGNMENT_NOT_FOUND",
    "backfill_requests": "ERR_BACKFILL_REQUEST_NOT_FOUND",
    "guest_issues": "ERR_GUEST_ISSUE_NOT_FOUND",
    "accessibility_resources": "ERR_ACCESSIBILITY_RESOURCE_NOT_FOUND",
    "accessibility_requests": "ERR_ACCESSIBILITY_REQUEST_NOT_FOUND",
}


def not_found(collection):
    return ApiError(NOT_FOUND_IDS[collection], 404, "%s does not exist." % collection)


def lookup(collection, ident):
    """Resolve an id inside a collection or raise the entity-specific 404."""
    if not isinstance(ident, str) or not ident:
        raise not_found(collection)
    row = getattr(db, collection).get(ident)
    if row is None:
        raise not_found(collection)
    return row


# ---------------------------------------------------------------------------
# timestamps
# ---------------------------------------------------------------------------

def fmt_dt(value):
    if value is None:
        return None
    value = value.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
        value.microsecond // 1000,
    )


def parse_dt(value, name="timestamp"):
    if not isinstance(value, str) or not value.strip():
        raise invalid("%s must be an ISO 8601 timestamp." % name)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise invalid("%s must be an ISO 8601 timestamp." % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def minutes_between(start, end):
    """Whole minutes, truncated toward zero (§2.6)."""
    return int((end - start).total_seconds() // 60)


# ---------------------------------------------------------------------------
# records
# ---------------------------------------------------------------------------

MISSING = object()


def new_record(collection, fields, versioned=True):
    row = dict(fields)
    row["id"] = str(uuid.uuid4())
    row["_seq"] = db.next_seq()
    row["_collection"] = collection
    stamp = now()
    row["created_at"] = stamp
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    getattr(db, collection)[row["id"]] = row
    return row


def touch(row):
    row["updated_at"] = now()
    row["version"] = row.get("version", 0) + 1


def update(row, **changes):
    """Apply changes; bump updated_at/version once when anything really moved."""
    changed = False
    for key, value in changes.items():
        if key not in row or row[key] != value:
            row[key] = value
            changed = True
    if changed:
        touch(row)
    return changed


def ordered(rows):
    """Deterministic created_at ascending order (§2.6 fallback key)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def all_rows(collection):
    return ordered(list(getattr(db, collection).values()))


# ---------------------------------------------------------------------------
# response envelope (§2.2)
# ---------------------------------------------------------------------------

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_dt(now()),
    }
    if extra:
        meta.update(extra)
    return meta


def respond(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def respond_list(items, limit, offset, total_count, status=200):
    meta = _meta(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        }
    )
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def respond_error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# ---------------------------------------------------------------------------
# authentication / authorization (§2.1, ladder rungs 1-2)
# ---------------------------------------------------------------------------

MUTATING_METHODS = ("POST", "PATCH", "PUT", "DELETE")


def auth(*allowed_roles):
    """Rung 1 then rung 2.  Returns (user_id, role)."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in ROLES:
        raise unauthenticated("X-User-Role is missing or unrecognized.")
    if request.method in MUTATING_METHODS:
        if user_id is None or not str(user_id).strip():
            raise unauthenticated("X-User-ID is required on mutating requests.")
    if allowed_roles and role not in allowed_roles:
        raise role_not_permitted(
            "Role %s is not permitted on this endpoint." % role
        )
    return user_id, role


# ---------------------------------------------------------------------------
# request body / query validation (rung 3)
# ---------------------------------------------------------------------------

def body_dict():
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise invalid("Request body must be a JSON object.")
    return payload


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_num(value):
    return (isinstance(value, int) or isinstance(value, float)) and not isinstance(
        value, bool
    )


def raw(body, name):
    return body.get(name, MISSING)


def v_str(value, name, allow_empty=False):
    if not isinstance(value, str):
        raise invalid("%s must be a string." % name)
    if not allow_empty and not value.strip():
        raise invalid("%s must not be empty." % name)
    return value


def v_int(value, name, minimum=None, maximum=None):
    if not is_int(value):
        raise invalid("%s must be an integer." % name)
    if minimum is not None and value < minimum:
        raise invalid("%s must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        raise invalid("%s must be <= %s." % (name, maximum))
    return value


def v_num(value, name, minimum=None, exclusive_minimum=None):
    if not is_num(value):
        raise invalid("%s must be a number." % name)
    dec = Decimal(str(value))
    if minimum is not None and dec < Decimal(str(minimum)):
        raise invalid("%s must be >= %s." % (name, minimum))
    if exclusive_minimum is not None and dec <= Decimal(str(exclusive_minimum)):
        raise invalid("%s must be > %s." % (name, exclusive_minimum))
    return dec


def v_bool(value, name):
    if not isinstance(value, bool):
        raise invalid("%s must be a boolean." % name)
    return value


def v_enum(value, name, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise invalid("%s must be one of %s." % (name, ", ".join(allowed)))
    return value


def v_enum_list(value, name, allowed):
    if not isinstance(value, list):
        raise invalid("%s must be an array." % name)
    out = []
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            raise invalid("%s entries must be one of %s." % (name, ", ".join(allowed)))
        if item not in out:
            out.append(item)
    return out


def req(body, name):
    value = body.get(name, MISSING)
    if value is MISSING:
        raise invalid("%s is required." % name)
    return value


def req_str(body, name):
    return v_str(req(body, name), name)


def req_int(body, name, minimum=None, maximum=None):
    return v_int(req(body, name), name, minimum, maximum)


def req_enum(body, name, allowed):
    return v_enum(req(body, name), name, allowed)


def req_dt(body, name):
    return parse_dt(req(body, name), name)


def opt_str(body, name, default=None, nullable=False):
    value = body.get(name, MISSING)
    if value is MISSING:
        return default
    if value is None:
        if nullable:
            return None
        raise invalid("%s must not be null." % name)
    return v_str(value, name, allow_empty=True)


def opt_int(body, name, default=None, minimum=None, maximum=None, nullable=False):
    value = body.get(name, MISSING)
    if value is MISSING:
        return default
    if value is None:
        if nullable:
            return None
        raise invalid("%s must not be null." % name)
    return v_int(value, name, minimum, maximum)


def opt_bool(body, name, default=None):
    value = body.get(name, MISSING)
    if value is MISSING:
        return default
    return v_bool(value, name)


def opt_dt(body, name, default=None, nullable=False):
    value = body.get(name, MISSING)
    if value is MISSING:
        return default
    if value is None:
        if nullable:
            return None
        raise invalid("%s must not be null." % name)
    return parse_dt(value, name)


# ---------------------------------------------------------------------------
# query parameters and pagination (§2.3)
# ---------------------------------------------------------------------------

def q_int(name, default):
    text = request.args.get(name)
    if text is None or text == "":
        return default
    try:
        return int(text)
    except (TypeError, ValueError):
        raise invalid("%s must be an integer." % name)


def pagination():
    limit = q_int("limit", 10)
    offset = q_int("offset", 0)
    if limit < 1 or limit > 100:
        raise invalid("limit must be between 1 and 100.")
    if offset < 0:
        raise invalid("offset must not be negative.")
    return limit, offset


def q_enum(name, allowed):
    text = request.args.get(name)
    if text is None or text == "":
        return None
    if text not in allowed:
        raise invalid("%s must be one of %s." % (name, ", ".join(allowed)))
    return text


def q_str(name):
    text = request.args.get(name)
    if text is None or text == "":
        return None
    return text


def q_bool(name):
    text = request.args.get(name)
    if text is None or text == "":
        return None
    lowered = text.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise invalid("%s must be a boolean." % name)


def paginate(rows, serializer):
    limit, offset = pagination()
    total = len(rows)
    window = rows[offset:offset + limit]
    return respond_list([serializer(r) for r in window], limit, offset, total)


ALL_ROLES = ROLES


def respond_array(items, status=200):
    """A computed array read: no pagination window is applied to it."""
    body = {"meta": _meta(), "response_type": "array", "data": items}
    return jsonify(body), status

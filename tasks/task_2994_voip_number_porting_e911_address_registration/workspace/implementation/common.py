"""Response envelope, authentication, pagination and entity bookkeeping."""
from flask import jsonify, request

import store
import util
from errors import ApiError, invalid

ROLES = (
    "PlatformAdmin",
    "NumberingAdmin",
    "PortingSpecialist",
    "CarrierLiaison",
    "AccountAdmin",
    "E911Validator",
    "SecurityAnalyst",
    "BillingAdmin",
)

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# ---------------------------------------------------------------------------
def _meta():
    return {
        "api_request_id": util.new_request_id(),
        "api_request_timestamp": util.to_iso(store.now()),
    }


def object_response(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": util.jsonable(data or {})}
    return jsonify(body), code


def list_response(rows, limit, offset, total_count, code=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": [util.jsonable(r) for r in rows]}
    return jsonify(body), code


def error_response(error_id, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return body


# ---------------------------------------------------------------------------
# Authentication and role checks (ladder rules 1-3)
# ---------------------------------------------------------------------------
def authenticate():
    """Rule 1: both headers present, non-empty, and a recognised role."""
    raw_id = request.headers.get("X-User-ID")
    raw_role = request.headers.get("X-User-Role")
    user_id = raw_id.strip() if isinstance(raw_id, str) else ""
    role = raw_role.strip() if isinstance(raw_role, str) else ""
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or unrecognised authentication headers.")
    return user_id, role


def require_role(role, allowed):
    """Rule 2: the acting role appears in the endpoint's authorized-role list."""
    if role not in allowed:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "Role %s may not address this endpoint." % role,
        )


def guard_account_owner(role, user_id, owner_account_id):
    """Rule 3: AccountAdmin ownership.  `owner_account_id` of None defers to the
    applicable not-found error raised later by the caller."""
    if role != "AccountAdmin":
        return
    if owner_account_id is None:
        return
    if owner_account_id != user_id:
        raise ApiError("ERR_ACCOUNT_FORBIDDEN", "Resource belongs to another account.")


def auth_for(allowed):
    user_id, role = authenticate()
    require_role(role, allowed)
    return user_id, role


# ---------------------------------------------------------------------------
# Request body
# ---------------------------------------------------------------------------
def body_or_error():
    """Parse the JSON body.  A body is required."""
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise invalid(detail="A JSON object request body is required.")
    return data


def optional_body():
    """Endpoints declared with no input accept and ignore any body."""
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return {}


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3, ladder rule 5)
# ---------------------------------------------------------------------------
def _int_param(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    if not text:
        raise ApiError("ERR_INVALID_PAGINATION", "%s must be an integer." % name)
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_PAGINATION", "%s must be an integer." % name)
    value = int(text)
    return value


def pagination():
    limit = _int_param("limit", PAGINATION_DEFAULT_LIMIT)
    offset = _int_param("offset", PAGINATION_DEFAULT_OFFSET)
    if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
        raise ApiError("ERR_INVALID_PAGINATION", "limit must be between 1 and 100.")
    if offset < 0:
        raise ApiError("ERR_INVALID_PAGINATION", "offset must be zero or greater.")
    return limit, offset


def enum_filter(name, allowed):
    """A filter whose value is outside its field's enumeration is ERR_INVALID_REQUEST."""
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in allowed:
        raise invalid(detail="Filter %s is not a valid value for its field." % name)
    return raw


def str_filter(name):
    return request.args.get(name)


def period_filter(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    if util.parse_period(raw) is None:
        raise invalid(detail="Filter %s must be a YYYY-MM period." % name)
    return raw


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


def sort_created_asc(rows):
    """Default list order: created_at ascending, insertion order breaking ties."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def sort_created_desc(rows):
    """Newest first: created_at descending, last written first among ties."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]), reverse=True)


# ---------------------------------------------------------------------------
# Entity bookkeeping (PRD 2.5)
# ---------------------------------------------------------------------------
def new_entity(with_mutation_fields=True):
    now = store.now()
    row = {"id": util.new_id(), "created_at": now, "_seq": store.next_seq()}
    if with_mutation_fields:
        row["updated_at"] = now
        row["version"] = 1
    return row


def bump(entity):
    """A mutation: refresh updated_at and increment version by exactly 1."""
    entity["updated_at"] = store.now()
    entity["version"] = entity.get("version", 1) + 1
    return entity


def snapshot(entity, fields):
    return {f: entity.get(f) for f in fields}


def bump_if_changed(entity, before, fields):
    for f in fields:
        if entity.get(f) != before.get(f):
            bump(entity)
            return True
    return False

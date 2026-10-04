"""Auth header extraction, role membership and body/path resolution helpers."""

from functools import wraps

from flask import request, g

from db import db, parse_iso
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
)

ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_ACCOUNT_MANAGER = "AccountManager"
ROLE_SETTLEMENT_ANALYST = "SettlementAnalyst"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_SERVICE_PROVIDER = "ServiceProvider"
ROLE_ANONYMOUS = "Anonymous"

# The six roles the system recognizes, spelled exactly as PRD §2.1 declares them.
ALL_ROLES = {
    ROLE_PLATFORM_ADMIN,
    ROLE_ACCOUNT_MANAGER,
    ROLE_SETTLEMENT_ANALYST,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_SERVICE_PROVIDER,
    ROLE_ANONYMOUS,
}


def extract_identity():
    """Read X-User-ID / X-User-Role. Missing headers or an undeclared role -> 401."""
    from errors import ERR_MISSING_AUTH_HEADER

    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    role = role.strip() if isinstance(role, str) else role
    uid = uid.strip() if isinstance(uid, str) else uid
    if not uid or not role:
        raise ApiError(ERR_MISSING_AUTH_HEADER)
    if role not in ALL_ROLES:
        raise ApiError(ERR_MISSING_AUTH_HEADER)
    return role, uid


def protected(roles):
    """Enforce the two auth gates (priority 1 then priority 2).

    PRD §2.1 declares PlatformAdmin may act on any operation for support
    purposes, so it bypasses the endpoint role list; every other role must
    appear in the list. Anonymous is never in a list, so it always fails 403.
    """
    from errors import ERR_UNAUTHORIZED

    allowed = set(roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role, uid = extract_identity()
            if role != ROLE_PLATFORM_ADMIN and role not in allowed:
                raise ApiError(ERR_UNAUTHORIZED)
            g.role = role
            g.uid = uid
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def body_json():
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ApiError(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return payload


def require_fields(body, names):
    for name in names:
        if name not in body or body[name] is None:
            raise ApiError(ERR_INVALID_REQUEST, "missing required field: %s" % name)
    return body


def enum_field(body, name, allowed, default=None, required=True):
    if name not in body or body[name] is None:
        if required and default is None:
            raise ApiError(ERR_INVALID_REQUEST, "missing required field: %s" % name)
        return default
    value = body[name]
    if value not in allowed:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "%s must be one of %s" % (name, ", ".join(sorted(allowed))),
        )
    return value


def string_field(body, name, default=None, required=True, non_empty=True):
    if name not in body or body[name] is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, "missing required field: %s" % name)
        return default
    value = body[name]
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, "%s must be a string" % name)
    if non_empty and not value.strip():
        raise ApiError(ERR_INVALID_REQUEST, "%s must be non-empty" % name)
    return value


def int_field(body, name, default=None, required=True, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, "missing required field: %s" % name)
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(ERR_INVALID_REQUEST, "%s must be an integer" % name)
    if minimum is not None and value < minimum:
        raise ApiError(ERR_INVALID_REQUEST, "%s must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError(ERR_INVALID_REQUEST, "%s must be <= %s" % (name, maximum))
    return value


def number_field(body, name, default=None, required=True, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, "missing required field: %s" % name)
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(ERR_INVALID_REQUEST, "%s must be a number" % name)
    value = float(value)
    if minimum is not None and value < minimum:
        raise ApiError(ERR_INVALID_REQUEST, "%s must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError(ERR_INVALID_REQUEST, "%s must be <= %s" % (name, maximum))
    return value


def bool_field(body, name, default=None, required=False):
    if name not in body or body[name] is None:
        if required and default is None:
            raise ApiError(ERR_INVALID_REQUEST, "missing required field: %s" % name)
        return default
    value = body[name]
    if not isinstance(value, bool):
        raise ApiError(ERR_INVALID_REQUEST, "%s must be a boolean" % name)
    return value


def datetime_field(body, name, default=None, required=True):
    if name not in body or body[name] is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, "missing required field: %s" % name)
        return default
    return parse_iso(body[name])


# ---------------------------------------------------------------------------
# Row resolution
# ---------------------------------------------------------------------------

def find_row(entity_type, row_id, not_found_error):
    row = db.get(entity_type, row_id)
    if row is None:
        raise ApiError(not_found_error)
    return row


def resolve_body_fk(entity_type, value, not_found_error, field_name):
    """Priority 12: every body-declared foreign key resolves at one point."""
    if value is None:
        return None
    row = db.get(entity_type, value)
    if row is None:
        raise ApiError(not_found_error, "%s does not resolve" % field_name)
    return row


def sort_by_created(rows):
    """Every list endpoint sorts by creation timestamp ascending (PRD §2.3)."""
    return sorted(rows, key=lambda r: (r.get("created_at", ""), r.get("id", "")))


def check_terminal(status, terminal_states):
    """Priority 15 runs before the legality check (priority 14)."""
    from errors import ERR_ALREADY_TERMINAL

    if status in terminal_states:
        raise ApiError(ERR_ALREADY_TERMINAL)


def check_transition(status, allowed_from, terminal_states):
    check_terminal(status, terminal_states)
    from errors import ERR_INVALID_STATE

    if status not in allowed_from:
        raise ApiError(
            ERR_INVALID_STATE,
            "status %s cannot perform this transition" % status,
        )


def query_flag(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value.lower() in ("1", "true", "yes", "on")
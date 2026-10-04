"""Authentication, RBAC and request-payload validation (PRD 2.1, 2.9, 2.7)."""

from functools import wraps

from flask import request

import errors
import storage

ROLES = ("PlatformAdmin", "CustomerService", "CreditAnalyst", "TradeInInspector", "Customer")
INTERNAL_ROLES = ("PlatformAdmin", "CustomerService", "CreditAnalyst", "TradeInInspector")


def current_caller():
    """Extract and authenticate the caller. Always evaluated first."""
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role:
        errors.fail("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required.")
    if user_role not in ROLES:
        errors.fail("ERR_UNAUTHENTICATED", "X-User-Role names no recognized role.")
    return {"id": user_id, "role": user_role}


def require_roles(*allowed):
    """Decorator: authenticate, then authorize against the endpoint's role list."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            caller = current_caller()
            if caller["role"] not in allowed:
                errors.fail("ERR_UNAUTHORIZED", "The calling role may not perform this operation.")
            return fn(caller, *args, **kwargs)

        return wrapper

    return decorator


def enforce_ownership(caller, account_id):
    """Customer callers may only touch resources owned by their own account."""
    if caller and caller["role"] == "Customer":
        if account_id is None or account_id != caller["id"]:
            errors.fail("ERR_UNAUTHORIZED", "A customer may only read their own resources.")


# ---------------------------------------------------------------------------
# Payload coercion -- ERR_INVALID_REQUEST is the last validation evaluated, and
# these helpers are only ever called after semantic checks have been settled.
# ---------------------------------------------------------------------------
def body():
    return request.get_json(silent=True) or {}


def required_str(data, field):
    value = data.get(field)
    if value is None or not isinstance(value, str) or value == "":
        errors.fail("ERR_INVALID_REQUEST", "Field '%s' is required and must be a string." % field)
    return value


def optional_str(data, field, default=None):
    value = data.get(field, default)
    if value is None:
        return default
    if not isinstance(value, str):
        errors.fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % field)
    return value


def required_int(data, field):
    value = data.get(field)
    if value is None or isinstance(value, bool) or not isinstance(value, int):
        errors.fail("ERR_INVALID_REQUEST", "Field '%s' is required and must be an integer." % field)
    return value


def optional_int(data, field, default=0):
    value = data.get(field, default)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        errors.fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % field)
    return value


def optional_bool(data, field, default=False):
    value = data.get(field, default)
    if value is None:
        return default
    if not isinstance(value, bool):
        errors.fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % field)
    return value


def optional_instant(data, field, default=None):
    value = data.get(field, default)
    if value is None:
        return default
    import clock

    parsed = clock.to_iso(value)
    if parsed is None:
        errors.fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 instant." % field)
    return parsed


def require_expected_line_version(data, line):
    """OCC on the three line-writing creates (PRD 2.7).

    When the field is omitted the check is skipped.
    """
    if "expected_subscriber_line_version" not in data:
        return
    value = data.get("expected_subscriber_line_version")
    if isinstance(value, bool) or not isinstance(value, int):
        errors.fail("ERR_INVALID_REQUEST",
                    "expected_subscriber_line_version must be an integer.")
    if value != line["version"]:
        errors.fail("ERR_STALE_SUBSCRIBER_LINE_VERSION",
                    "The supplied subscriber line version is stale.")
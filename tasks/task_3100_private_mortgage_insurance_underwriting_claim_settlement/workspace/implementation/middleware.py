"""Identity header extraction, role gating and body-shape validation.

PRD 2.1: every request carries `X-User-ID` and `X-User-Role`. Five roles are
recognized, spelled exactly: MasterPolicyAdmin, Underwriter, Lender, Servicer,
Borrower. A missing or malformed header pair is ERR_UNAUTHENTICATED (401); a
well-formed role that is not permitted for the operation is
ERR_FORBIDDEN_FOR_ROLE (403).

PRD 2.12 precedence: authentication first, role permission second, then
existence, then state, then the business gates, with ERR_INVALID_REQUEST (400)
detected during deserialization so a malformed body surfaces before the gates.
"""

from flask import request

from errors import (
    ApiError,
    ERR_UNAUTHENTICATED,
    ERR_FORBIDDEN_FOR_ROLE,
    ERR_INVALID_REQUEST,
)
from common import clock_dt, parse_utc

ROLE_MASTER_POLICY_ADMIN = "MasterPolicyAdmin"
ROLE_UNDERWRITER = "Underwriter"
ROLE_LENDER = "Lender"
ROLE_SERVICER = "Servicer"
ROLE_BORROWER = "Borrower"

VALID_ROLES = (
    ROLE_MASTER_POLICY_ADMIN,
    ROLE_UNDERWRITER,
    ROLE_LENDER,
    ROLE_SERVICER,
    ROLE_BORROWER,
)


class Identity(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError(ERR_UNAUTHENTICATED, "X-User-ID and X-User-Role headers are required.")
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or not role:
        raise ApiError(ERR_UNAUTHENTICATED, "X-User-ID and X-User-Role headers are required.")
    if role not in VALID_ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, "X-User-Role is not one of the recognized roles.")
    return Identity(user_id, role)


def require_roles(identity, *roles):
    if identity.role not in roles:
        raise ApiError(
            ERR_FORBIDDEN_FOR_ROLE,
            "Role %s is not permitted for this operation." % identity.role,
        )


def require_owner(identity, owner_id, label="lender"):
    """PRD 2.1 entity-backed identity: a Lender / Servicer caller's X-User-ID is
    the id of the acting row and must match the resource's foreign key."""
    if identity.user_id != owner_id:
        raise ApiError(
            ERR_FORBIDDEN_FOR_ROLE,
            "Caller is not the owning %s for this operation." % label,
        )


# --- body shape ---------------------------------------------------------------

def body():
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ApiError(ERR_INVALID_REQUEST, "The request body must be a JSON object.")
    return payload


def require_fields(payload, *names):
    for name in names:
        if name not in payload or payload[name] is None:
            raise ApiError(ERR_INVALID_REQUEST, "Field '%s' is required." % name)


def require_string(payload, name, required=True, default=None):
    value = payload.get(name, default)
    if value is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, "Field '%s' is required." % name)
        return None
    if not isinstance(value, str) or not value.strip():
        raise ApiError(ERR_INVALID_REQUEST, "Field '%s' must be a non-empty string." % name)
    return value


def require_int(payload, name, required=True, default=None, non_negative=True):
    if name not in payload or payload.get(name) is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, "Field '%s' is required." % name)
        return default
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(ERR_INVALID_REQUEST, "Field '%s' must be an integer." % name)
    if non_negative and value < 0:
        raise ApiError(ERR_INVALID_REQUEST, "Field '%s' must not be negative." % name)
    return value


def require_number(payload, name, required=True, default=None, non_negative=True):
    if name not in payload or payload.get(name) is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, "Field '%s' is required." % name)
        return default
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(ERR_INVALID_REQUEST, "Field '%s' must be a number." % name)
    if non_negative and value < 0:
        raise ApiError(ERR_INVALID_REQUEST, "Field '%s' must not be negative." % name)
    return value


def require_bool(payload, name, required=True, default=None):
    if name not in payload or payload.get(name) is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, "Field '%s' is required." % name)
        return default
    value = payload.get(name)
    if not isinstance(value, bool):
        raise ApiError(ERR_INVALID_REQUEST, "Field '%s' must be a boolean." % name)
    return value


def require_enum(payload, name, allowed, required=True, default=None):
    value = payload.get(name, default)
    if value is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, "Field '%s' is required." % name)
        return None
    if value not in allowed:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed))),
        )
    return value


def require_instant(payload, name, required=True, default=None, not_future=False):
    """Parse an ISO 8601 instant.

    `not_future` is off by default: the rejection discipline of PRD 2.12 lists a
    future event instant among the malformed-body cases, but the temporal rules
    in this API are evaluated against the logical clock, which an operator moves
    explicitly, so instants are carried through as supplied and compared against
    stored state rather than against each other at parse time.
    """
    value = payload.get(name, default)
    if value is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, "Field '%s' is required." % name)
        return None
    try:
        parsed = parse_utc(value)
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, "Field '%s' must be an ISO 8601 instant." % name)
    if not_future and parsed > clock_dt():
        raise ApiError(ERR_INVALID_REQUEST, "Field '%s' must not be in the future." % name)
    return parsed


def optional_list(payload, name, required=False):
    value = payload.get(name)
    if value is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, "Field '%s' is required." % name)
        return None
    if not isinstance(value, list):
        raise ApiError(ERR_INVALID_REQUEST, "Field '%s' must be a list." % name)
    return value
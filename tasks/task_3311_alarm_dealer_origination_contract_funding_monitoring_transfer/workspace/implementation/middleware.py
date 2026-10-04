"""Auth header extraction, role checking and shared validation helpers.

PRD §2.1 — every request carries `X-User-ID` and `X-User-Role`. A request that
omits either header, or presents a role string that is not one of the eight
declared roles, is refused with ERR_UNAUTHENTICATED (401). A declared role the
endpoint does not admit is refused with ERR_UNAUTHORIZED (403).

The rejection ORDER is PRD §2.10, not text order.
"""

import db
from errors import ApiError

# PRD §2.1 — the eight declared roles, spelled exactly.
ROLES = [
    "PlatformAdmin",
    "ChannelManager",
    "Dealer",
    "FundingAnalyst",
    "ComplianceOfficer",
    "MonitoringOperator",
    "ServiceCoordinator",
    "Customer",
]

IDENTITY_HEADER = "X-User-ID"
ROLE_HEADER = "X-User-Role"


class Actor(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    def __repr__(self):
        return "Actor(%r, %r)" % (self.user_id, self.role)


def authenticate(headers):
    """PRD §2.10 priority 1 — presence of both headers and a declared role."""
    user_id = headers.get(IDENTITY_HEADER)
    role = headers.get(ROLE_HEADER)
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED")
    if str(user_id).strip() == "" or str(role).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return Actor(str(user_id), role)


def authorize(actor, allowed_roles):
    """PRD §2.10 priority 2 — is the acting role admitted for this operation?"""
    if actor.role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")


def resolve(table, row_id):
    """Priority 3 — a path identifier that does not resolve yields 404."""
    row = db.state.get(table, row_id)
    if row is None:
        raise ApiError("ERR_ENTITY_NOT_FOUND")
    return row


def require_fk(table, row_id, field=None):
    """Priority 3 — a body foreign key that does not resolve yields 400."""
    if row_id is None:
        raise ApiError("ERR_FK_INTEGRITY_VIOLATION",
                       "The body field %s is required." % (field or "reference"))
    row = db.state.get(table, row_id)
    if row is None:
        raise ApiError("ERR_FK_INTEGRITY_VIOLATION")
    return row


# --- body shape helpers (priority 10 — last of the checks) ----------------

def body_or_empty(request):
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return payload


def required(body, *names):
    for name in names:
        if name not in body or body[name] is None:
            raise ApiError("ERR_INVALID_REQUEST", "The field %r is required." % name)


def as_int(value, field, minimum=None, maximum=None):
    if isinstance(value, bool) or value is None:
        raise ApiError("ERR_INVALID_REQUEST", "The field %r must be an integer." % field)
    if isinstance(value, int):
        out = value
    elif isinstance(value, float) and float(value).is_integer():
        out = int(value)
    elif isinstance(value, str):
        try:
            out = int(value.strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "The field %r must be an integer." % field)
    else:
        raise ApiError("ERR_INVALID_REQUEST", "The field %r must be an integer." % field)
    if minimum is not None and out < minimum:
        raise ApiError("ERR_INVALID_REQUEST",
                       "The field %r must be at least %d." % (field, minimum))
    if maximum is not None and out > maximum:
        raise ApiError("ERR_INVALID_REQUEST",
                       "The field %r must be at most %d." % (field, maximum))
    return out


def as_str(value, field, none_ok=False, length=None):
    if value is None:
        if none_ok:
            return None
        raise ApiError("ERR_INVALID_REQUEST", "The field %r is required." % field)
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "The field %r must be a string." % field)
    if value.strip() == "" and not none_ok:
        raise ApiError("ERR_INVALID_REQUEST", "The field %r must be a non-empty string." % field)
    if length is not None and len(value) != length:
        raise ApiError("ERR_INVALID_REQUEST",
                       "The field %r must be exactly %d characters." % (field, length))
    return value


def as_enum(value, field, allowed):
    if value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST",
                       "The field %r must be one of %s." % (field, sorted(allowed)))
    return value


def as_number(value, field, minimum=None, maximum=None):
    if value is None or isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST", "The field %r must be a number." % field)
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "The field %r must be a number." % field)
    if minimum is not None and out < minimum:
        raise ApiError("ERR_INVALID_REQUEST",
                       "The field %r must be at least %s." % (field, minimum))
    if maximum is not None and out > maximum:
        raise ApiError("ERR_INVALID_REQUEST",
                       "The field %r must be at most %s." % (field, maximum))
    return out


def as_timestamp(value, field):
    from util import parse_ts
    parsed = parse_ts(value)
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST", "The field %r must be an ISO 8601 instant." % field)
    return parsed
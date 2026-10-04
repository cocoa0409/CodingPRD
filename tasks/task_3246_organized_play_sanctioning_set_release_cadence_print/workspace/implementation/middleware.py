"""Authentication, RBAC and request-shape validation.

The validation ladder of §2.12: identity first (ERR_UNAUTHENTICATED), then
role permission (ERR_UNAUTHORIZED), then request shape (ERR_INVALID_REQUEST).
Reference resolution and the state/business rungs follow in the route handlers.
"""

from errors import fail
from utils import parse_dt

# §2.1 — exactly four roles, spelled as follows.
ROLE_OPS_ADMIN = "OpsAdmin"
ROLE_STORE_ORGANIZER = "StoreOrganizer"
ROLE_JUDGE = "Judge"
ROLE_DISTRIBUTOR = "Distributor"

ALL_ROLES = (ROLE_OPS_ADMIN, ROLE_STORE_ORGANIZER, ROLE_JUDGE, ROLE_DISTRIBUTOR)

# Roles whose X-User-ID names a persisted entity rather than an opaque operator.
ENTITY_BACKED_ROLES = (ROLE_STORE_ORGANIZER, ROLE_JUDGE)


def require_role(request, allowed):
    """Identity then permission. Returns the caller's role."""
    role = request.headers.get("X-User-Role")
    if role is None or role.strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    role = role.strip()
    if role not in ALL_ROLES:
        fail("ERR_UNAUTHENTICATED",
             "X-User-Role must name one of OpsAdmin, StoreOrganizer, Judge or Distributor.")

    user_id = request.headers.get("X-User-ID")
    if role in ENTITY_BACKED_ROLES:
        if user_id is None or user_id.strip() == "":
            fail("ERR_UNAUTHENTICATED",
                 "X-User-ID is required for the %s role." % role)
    if role not in allowed:
        fail("ERR_UNAUTHORIZED",
             "Role %s is not authorized for this operation." % role)
    return role


def caller_id(request):
    value = request.headers.get("X-User-ID")
    return value.strip() if isinstance(value, str) else value


def is_ops_or_owner(request, owner_id):
    """OpsAdmin passes everywhere; entity-backed roles must own the resource."""
    role = request.headers.get("X-User-Role", "").strip()
    if role == ROLE_OPS_ADMIN:
        return True
    return caller_id(request) == owner_id


# --------------------------------------------------------------------------
# Request shape (§1.4 priority 3 / PRD §2.12)
# --------------------------------------------------------------------------

# Type tokens used by the body validator.
STRING = "string"
INTEGER = "integer"
BOOLEAN = "boolean"
DATETIME = "datetime"


def body_of(request):
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    return body


def check_body(request, required=(), optional=(), types=None, enums=None):
    """Every required field present, no undeclared field, values well typed."""
    types = types or {}
    enums = enums or {}
    body = body_of(request)
    if not isinstance(body, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")

    for name in required:
        if name not in body or body[name] is None:
            fail("ERR_INVALID_REQUEST", "Required field '%s' is missing." % name)

    allowed = set(required) | set(optional)
    for name in body:
        if name not in allowed:
            fail("ERR_INVALID_REQUEST", "Undeclared field '%s'." % name)

    for name, value in body.items():
        if value is None:
            continue
        token = types.get(name)
        if token is None:
            continue
        if token == INTEGER:
            if not isinstance(value, int) or isinstance(value, bool):
                fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
        elif token == BOOLEAN:
            if not isinstance(value, bool):
                fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
        elif token == STRING:
            if not isinstance(value, str):
                fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
        elif token == DATETIME:
            if parse_dt(value) is None:
                fail("ERR_INVALID_REQUEST",
                     "Field '%s' must be an ISO 8601 datetime." % name)
        if name in enums:
            domain = enums[name]
            if value not in domain:
                fail("ERR_INVALID_REQUEST",
                     "Field '%s' must be one of %s." % (name, ", ".join(domain)))
    return body


def check_query_enums(request, enums):
    """Query filter values must fall inside their declared enumerated domain."""
    for name, domain in (enums or {}).items():
        value = request.args.get(name)
        if value is None or value == "":
            continue
        if value not in domain:
            fail("ERR_INVALID_REQUEST",
                 "Query parameter '%s' must be one of %s." % (name, ", ".join(domain)))


def require_action(body, domain):
    action = body.get("action")
    if action is None:
        fail("ERR_INVALID_REQUEST", "Required field 'action' is missing.")
    if action not in domain:
        fail("ERR_INVALID_REQUEST",
             "Field 'action' must be one of %s." % ", ".join(domain))
    return action
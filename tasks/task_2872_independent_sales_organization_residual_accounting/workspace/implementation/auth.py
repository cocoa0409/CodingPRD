"""Authentication (band 1), authorization (band 2) and agent scope (band 3)."""
from flask import g, request

from apierrors import fail

ROLES = ("IsoAdmin", "ResidualAnalyst", "ResidualController", "Agent")


def authenticate():
    """PRD 2.1: the very first check on any request, ahead of routing concerns."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or user_id == "" or role == "":
        fail("ERR_MISSING_AUTH_HEADERS", "X-User-ID and X-User-Role headers are required")
    if role not in ROLES:
        fail("ERR_MISSING_AUTH_HEADERS", "X-User-Role must be one of the four declared roles")
    g.user_id = user_id
    g.role = role


def authorize(*roles):
    if g.role not in roles:
        fail("ERR_UNAUTHORIZED", "role %s may not call this endpoint" % g.role)
    return g.role


def acting_agent():
    return g.role == "Agent"


def scope_self(path_id):
    """An acting Agent may address only its own id."""
    if acting_agent() and g.user_id != path_id:
        fail("ERR_AGENT_SCOPE_VIOLATION", "an agent may address only its own record")


def scope_owned(owner_agent_id):
    """An acting Agent may read only resources whose agent FK is itself."""
    if acting_agent() and g.user_id != owner_agent_id:
        fail("ERR_AGENT_SCOPE_VIOLATION", "resource does not belong to the acting agent")


def scope_list_filter(param):
    """An acting Agent must narrow a list read to itself with the named filter."""
    if acting_agent():
        value = request.args.get(param)
        if value is None or value != g.user_id:
            fail(
                "ERR_AGENT_SCOPE_VIOLATION",
                "an agent must pass %s equal to its own id" % param,
            )

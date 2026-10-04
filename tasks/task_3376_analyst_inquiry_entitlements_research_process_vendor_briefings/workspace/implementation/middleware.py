"""Identity headers, role checking and body parsing helpers (PRD 2.1, 2.11)."""

from flask import request

from errors import bad_request, unauthenticated, unauthorized

ROLE_HEADER = "X-User-Role"
ID_HEADER = "X-User-ID"

# Roles whose X-User-ID is an opaque operator identifier, never an entity id.
OPAQUE_ROLES = {
    "PlatformAdmin",
    "ResearchDirector",
    "ComplianceOfficer",
    "EventProgrammer",
    "SalesRep",
}


def authenticate(roles, anonymous=False):
    """Return (role, user_id) after the auth/authz checks of PRD 2.11.

    `anonymous` marks the one clock operation that does not require the
    identity headers; when a role is nevertheless supplied there, the ordinary
    authorization rule still applies.
    """
    role = request.headers.get(ROLE_HEADER)
    user_id = request.headers.get(ID_HEADER)
    role = role.strip() if isinstance(role, str) else role
    user_id = user_id.strip() if isinstance(user_id, str) else user_id

    if anonymous:
        if not role and not user_id:
            return None, None
        if not role or not user_id:
            raise unauthenticated()
        if role not in roles:
            raise unauthorized()
        return role, user_id

    if not role or not user_id:
        raise unauthenticated()
    if role not in roles:
        raise unauthorized()
    return role, user_id


def body():
    """Return the JSON request body as a dict (an empty dict when absent)."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise bad_request("The request body must be a JSON object.")
    return data


def required(data, field):
    if field not in data or data[field] is None:
        raise bad_request("Missing required field: %s" % field)
    return data[field]


def require_str(data, field):
    value = required(data, field)
    if not isinstance(value, str):
        raise bad_request("Field %s must be a string." % field)
    return value


def require_int(data, field):
    value = required(data, field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request("Field %s must be an integer." % field)
    return value


def optional_str(data, field, default=""):
    value = data.get(field, default)
    if value is None:
        return default
    if not isinstance(value, str):
        raise bad_request("Field %s must be a string." % field)
    return value


def optional_int(data, field, default=None):
    value = data.get(field, default)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request("Field %s must be an integer." % field)
    return value


def optional_bool(data, field, default=False):
    value = data.get(field, default)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise bad_request("Field %s must be a boolean." % field)
    return value


def enum(value, allowed, field):
    if value not in allowed:
        raise bad_request(
            "Field %s must be one of %s." % (field, ", ".join(sorted(allowed)))
        )
    return value


def query_int(name, default, minimum=None, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        value = default
    else:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = default
    if minimum is not None and value < minimum:
        value = minimum
    if maximum is not None and value > maximum:
        value = maximum
    return value


def pagination():
    """limit/offset per SCAFFOLD section 1.0 and PRD 2.3."""
    limit = query_int("limit", 10, minimum=1, maximum=100)
    offset = query_int("offset", 0, minimum=0)
    return limit, offset

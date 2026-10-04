"""Validation pipeline tiers 1-4 helpers (PRD 2.7): authentication, role
authorization, body-FK existence, and field-shape checks."""

from flask import request

from errors import (
    ApiError,
    ERR_UNAUTHENTICATED,
    ERR_FORBIDDEN,
    ERR_VALIDATION,
)

# PRD 2.1: the eight declared roles.
ROLES = {
    "Anonymous",
    "SocietyAdmin",
    "AccreditationReviewer",
    "Registrar",
    "Consultant",
    "SchoolAdmin",
    "ProgramDirector",
    "AdultLearner",
}

AGE_LEVELS = {
    "INFANT_TODDLER",
    "EARLY_CHILDHOOD",
    "ELEMENTARY_I",
    "ELEMENTARY_II",
    "SECONDARY",
}


# ---------------------------------------------------------------------------
# Tier 1 / 2: authentication and role authorization
# ---------------------------------------------------------------------------

def authenticate():
    """Tier 1: X-User-ID and X-User-Role present; role is a declared role."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED[0], ERR_UNAUTHENTICATED[1],
                       "Missing or unrecognized identity headers.")
    return uid, role


def require_role(role, allowed):
    """Tier 2: the role must appear in the endpoint's authorized set."""
    if role not in allowed:
        raise ApiError(ERR_FORBIDDEN[0], ERR_FORBIDDEN[1],
                       "Role %s is not authorized for this endpoint." % role)


# ---------------------------------------------------------------------------
# Payload access
# ---------------------------------------------------------------------------

def payload():
    """Return the JSON request body as a dict (empty dict when absent)."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                       "Request body must be a JSON object.")
    return body


# ---------------------------------------------------------------------------
# Tier 4: field-shape helpers (all raise ERR_VALIDATION / 400)
# ---------------------------------------------------------------------------

def _bad(msg):
    raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1], msg)


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        _bad("Field %r is required and must be a non-empty string." % field)
    return v


def opt_str(body, field):
    v = body.get(field)
    if v is not None and not isinstance(v, str):
        _bad("Field %r must be a string when present." % field)
    return v


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        _bad("Field %r is required and must be a boolean." % field)
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(body, field, minimum=None):
    v = body.get(field)
    if not _is_int(v):
        _bad("Field %r is required and must be an integer." % field)
    if minimum is not None and v < minimum:
        _bad("Field %r must be at least %s." % (field, minimum))
    return v


def opt_int(body, field, minimum=None):
    v = body.get(field)
    if v is None:
        return None
    if not _is_int(v):
        _bad("Field %r must be an integer." % field)
    if minimum is not None and v < minimum:
        _bad("Field %r must be at least %s." % (field, minimum))
    return v


def _is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_number(body, field, gt=None):
    v = body.get(field)
    if not _is_number(v):
        _bad("Field %r is required and must be a number." % field)
    if gt is not None and not v > gt:
        _bad("Field %r must be greater than %s." % (field, gt))
    return v


def opt_number(body, field, gt=None):
    v = body.get(field)
    if v is None:
        return None
    if not _is_number(v):
        _bad("Field %r must be a number." % field)
    if gt is not None and not v > gt:
        _bad("Field %r must be greater than %s." % (field, gt))
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        _bad("Field %r must be one of %s." % (field, sorted(allowed)))
    return v


def req_list(body, field, non_empty=False):
    v = body.get(field)
    if not isinstance(v, list):
        _bad("Field %r is required and must be an array." % field)
    if non_empty and len(v) == 0:
        _bad("Field %r must be a non-empty array." % field)
    return v


def req_dict(body, field):
    v = body.get(field)
    if not isinstance(v, dict):
        _bad("Field %r is required and must be an object." % field)
    return v

"""Auth header extraction, RBAC, body access and input coercion helpers.

PRD 2.1: every request carries X-User-ID and X-User-Role.  A missing or empty
header is ERR_UNAUTHENTICATED (401); an unrecognised role or a role that is not
authorized for the endpoint is ERR_ROLE_NOT_PERMITTED (403).
"""

from flask import g, request

from errors import ApiError, require
from util import BadValue, parse_dt, to_bool, to_decimal, to_int

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

REGISTRAR = "Registrar"
LMS_ADMIN = "LmsAdmin"
INSTRUCTOR = "Instructor"
PRIVACY_REVIEWER = "PrivacyReviewer"
ACCESSIBILITY_REVIEWER = "AccessibilityReviewer"
STUDENT = "Student"

ALL_ROLES = (
    REGISTRAR,
    LMS_ADMIN,
    INSTRUCTOR,
    PRIVACY_REVIEWER,
    ACCESSIBILITY_REVIEWER,
    STUDENT,
)


def authenticate(allowed_roles):
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    user_id = user_id.strip()
    role = role.strip()
    require(role in ALL_ROLES, "ERR_ROLE_NOT_PERMITTED",
            "Unknown role '%s'." % role)
    require(role in allowed_roles, "ERR_ROLE_NOT_PERMITTED",
            "Role '%s' may not call this endpoint." % role)
    g.user_id = user_id
    g.role = role
    return user_id, role


def actor():
    return g.user_id


def role():
    return g.role


def body():
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return payload


def has(payload, name):
    return name in payload and payload[name] is not None


def bad(name, detail="is invalid"):
    raise ApiError("ERR_INVALID_REQUEST", "'%s' %s." % (name, detail))


def need(payload, name):
    if not has(payload, name):
        bad(name, "is required")
    return payload[name]


def as_str(payload, name, required=False, default=None):
    if not has(payload, name):
        if required:
            bad(name, "is required")
        return default
    value = payload[name]
    if not isinstance(value, str) or value.strip() == "":
        bad(name, "must be a non-empty string")
    return value


def as_enum(payload, name, members, required=False, default=None):
    if not has(payload, name):
        if required:
            bad(name, "is required")
        return default
    value = payload[name]
    if not isinstance(value, str) or value not in members:
        bad(name, "must be one of %s" % ", ".join(members))
    return value


def as_int(payload, name, required=False, default=None, low=None, high=None):
    if not has(payload, name):
        if required:
            bad(name, "is required")
        return default
    try:
        value = to_int(payload[name])
    except BadValue:
        bad(name, "must be an integer")
    if low is not None and value < low:
        bad(name, "must be at least %d" % low)
    if high is not None and value > high:
        bad(name, "must be at most %d" % high)
    return value


def as_decimal(payload, name, required=False, default=None, low=None, high=None):
    if not has(payload, name):
        if required:
            bad(name, "is required")
        return default
    try:
        value = to_decimal(payload[name])
    except BadValue:
        bad(name, "must be a number")
    if low is not None and value < low:
        bad(name, "must be at least %s" % low)
    if high is not None and value > high:
        bad(name, "must be at most %s" % high)
    return value


def as_bool(payload, name, required=False, default=None):
    if not has(payload, name):
        if required:
            bad(name, "is required")
        return default
    try:
        return to_bool(payload[name])
    except BadValue:
        bad(name, "must be a boolean")


def as_dt(payload, name, required=False, default=None):
    if not has(payload, name):
        if required:
            bad(name, "is required")
        return default
    try:
        return parse_dt(payload[name])
    except BadValue:
        bad(name, "must be an ISO 8601 UTC timestamp")


def as_id(payload, name, required=False):
    """A foreign key reference: must be a non-empty string when supplied."""
    if not has(payload, name):
        if required:
            return None
        return None
    value = payload[name]
    if not isinstance(value, str) or value.strip() == "":
        return None
    return value

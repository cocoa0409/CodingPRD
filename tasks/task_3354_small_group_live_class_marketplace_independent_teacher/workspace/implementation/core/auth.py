"""Authentication, role membership, ownership and body-shape helpers.

Ladder positions 1, 2, 16, 30 and 31 of PRD section 2.6.
"""

from flask import request

from .errors import fail

ROLES = ("TeacherApplicant", "TeacherReviewer", "Teacher", "Parent", "PlatformAdmin")

MISSING = object()


def authenticate():
    """Ladder 1: X-User-Role and X-User-ID present and the role is declared."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or user_id is None or str(role).strip() == "" or str(user_id).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-Role and X-User-ID headers are both required")
    role = str(role).strip()
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role %r is not a declared role" % (role,))
    return role, str(user_id).strip()


def authorize(role, allowed):
    """Ladder 2: the acting role is permitted for this operation."""
    if role not in allowed:
        fail("ERR_FORBIDDEN", "Role %s may not perform this operation" % (role,))


def require_teacher_owner(role, user_id, teacher_id):
    """Ladder 16: an acting Teacher must own the resource being mutated."""
    if role == "Teacher" and user_id != teacher_id:
        fail("ERR_NOT_RESOURCE_OWNER", "The acting teacher does not own this resource")


def require_parent_owner(role, user_id, learner):
    """Ladder 16: an acting Parent must own the learner being mutated."""
    if role == "Parent" and user_id != learner.get("parent_user_id"):
        fail("ERR_NOT_RESOURCE_OWNER", "The acting parent does not own this learner")


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {}
    return data


def raw(data, name, default=MISSING):
    value = data.get(name, default)
    return value


def is_blank(value):
    return value is None or (isinstance(value, str) and value.strip() == "")


def require_fields(data, names):
    """Ladder 30: every required input field is present and non-blank."""
    for name in names:
        if name not in data or is_blank(data.get(name)):
            fail("ERR_MISSING_REQUIRED_FIELD", "Field %r is required" % (name,))


def require_enum(data, name, allowed):
    """Ladder 31: an enum-typed input carries a declared member."""
    value = data.get(name)
    if value is None:
        return None
    if value not in allowed:
        fail("ERR_INVALID_ENUM_VALUE", "%s must be one of %s" % (name, ", ".join(allowed)))
    return value


def require_int(data, name, minimum=None, maximum=None):
    value = data.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        else:
            fail("ERR_INVALID_ENUM_VALUE", "%s must be an integer" % (name,))
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_ENUM_VALUE", "%s must be at least %d" % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_ENUM_VALUE", "%s must be at most %d" % (name, maximum))
    return value

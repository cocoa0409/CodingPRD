"""Authentication and role authorization (PRD section 2.1, 2.6 priorities 1 & 3).

Every request must carry X-User-ID and X-User-Role. Exactly six roles exist.
Missing/invalid headers -> ERR_UNAUTHENTICATED (401). A role not on the
endpoint's authorized list -> ERR_FORBIDDEN_ROLE (403). X-User-ID is compared
to entity ids only by ownership checks (priority 5), never at authentication.
"""

from flask import request

from errors import api_error

ROLES = (
    "PlatformAdmin",
    "GovernmentContact",
    "Reviewer",
    "CommitteeMember",
    "Member",
    "AwardsDirector",
)


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not role or role not in ROLES:
        raise api_error(
            "ERR_UNAUTHENTICATED",
            "missing or invalid X-User-ID / X-User-Role headers",
        )
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise api_error(
            "ERR_FORBIDDEN_ROLE",
            "role %s is not authorized for this operation" % role,
        )

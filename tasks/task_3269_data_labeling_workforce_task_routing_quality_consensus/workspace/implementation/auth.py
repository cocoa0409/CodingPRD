"""Identity headers, role matrix and the segregation-of-duties guard.

PRD section 2.1 fixes the header names and the four role spellings. PRD section
2.11 puts the header check and the body-completeness check together at rank 1,
and the role check at rank 2.
"""

from flask import request

from errors import (
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    fail,
)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

ROLE_ADMIN = "PlatformAdmin"
ROLE_REVIEWER = "PlatformReviewer"
ROLE_WORKER = "Worker"
ROLE_ANONYMOUS = "Anonymous"

KNOWN_ROLES = (ROLE_ADMIN, ROLE_REVIEWER, ROLE_WORKER, ROLE_ANONYMOUS)


class Principal(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    def __repr__(self):  # pragma: no cover - debugging aid
        return "Principal(%r, %r)" % (self.user_id, self.role)


def raw_identity():
    """Read the identity headers without enforcing anything."""
    uid = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    uid = uid.strip() if isinstance(uid, str) else uid
    role = role.strip() if isinstance(role, str) else role
    return uid, role


def enforce_headers():
    """Rank 1: both identity headers must be present and non-empty."""
    uid, role = raw_identity()
    if not uid or not role:
        fail(ERR_UNAUTHENTICATED)
    return Principal(uid, role)


def required(*roles):
    """Rank 2: the acting role must be one of the roles the endpoint declares."""
    return roles


def enforce_role(principal, roles):
    if principal.role not in roles:
        fail(ERR_UNAUTHORIZED)
    return principal


def actor_id(principal):
    """The acting principal's X-User-ID."""
    return principal.user_id


def worker_identity_id(principal):
    """For a Worker principal X-User-ID is the id of the acting WorkerIdentity."""
    return principal.user_id


# --------------------------------------------------------------------------
# Segregation of duties (PRD section 2.1)
# --------------------------------------------------------------------------
def reviewer_holds_commit(reviewer_id, item_id):
    """True when the acting reviewer owns a Commit on the piece."""
    from db import commits

    for commit in commits.values():
        if commit.get("item_id") == item_id and commit.get("worker_id") == reviewer_id:
            return True
    return False


def enforce_segregation(reviewer_id, item_id):
    if reviewer_holds_commit(reviewer_id, item_id):
        fail(ERR_SEGREGATION_OF_DUTIES)
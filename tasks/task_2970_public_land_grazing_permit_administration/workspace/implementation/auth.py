"""Identity and role enforcement (PRD sections 2.1, 2.10 -- priorities 3 and 4)."""

from flask import request

from constants import OPERATIONAL_ROLES, ROLES
from errors import ApiError
import store


class Actor(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_permittee(self):
        return self.role == "Permittee"


def _unauthorized(message):
    raise ApiError("ERR_UNAUTHORIZED", message)


def authenticate(allowed_roles):
    """Priority 3. Both headers must be present, the role must be a real role and
    must be listed for the endpoint; a Permittee identity must resolve to a
    registered permittee."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "":
        _unauthorized("X-User-ID is required")
    if role is None or role.strip() == "":
        _unauthorized("X-User-Role is required")
    if role not in ROLES:
        _unauthorized("unknown role %s" % role)
    if role not in allowed_roles:
        _unauthorized("role %s may not perform this operation" % role)
    if role == "Permittee" and store.get("permittees", user_id) is None:
        _unauthorized("X-User-ID does not resolve to a registered permittee")
    return Actor(user_id, role)


def any_operational():
    return authenticate(OPERATIONAL_ROLES)


def require_own(actor, permittee_id):
    """A Permittee actor may only touch rows that belong to it."""
    if actor.is_permittee and actor.user_id != permittee_id:
        _unauthorized("a permittee may only act on its own records")


def scope_permittee_rows(actor, records, owner_of):
    """List scoping for a Permittee actor: only its own rows are visible."""
    if not actor.is_permittee:
        return records
    return [record for record in records if owner_of(record) == actor.user_id]


def require_identity(actor, expected_user_id, message):
    """Identity rules of PRD 2.10 that are not segregation of duties: only the
    stamped officer may act. The rule bites only once the identifier exists."""
    if expected_user_id is not None and actor.user_id != expected_user_id:
        _unauthorized(message)


def require_segregation(actor, forbidden_user_id, message):
    """Priority 4. The acting identity must differ from the named identity."""
    if forbidden_user_id is not None and actor.user_id == forbidden_user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", message)

"""Rungs 1, 2 and 7 of the ladder: authentication, role authorisation, ownership.

Headers are exactly `X-User-ID` and `X-User-Role` (PRD §2.1).
"""

from flask import request

import errors
from errors import ApiError

SPA_DIRECTOR = "SpaDirector"
COMPLIANCE_OFFICER = "ComplianceOfficer"
SPA_COORDINATOR = "SpaCoordinator"
THERAPIST = "Therapist"
GUEST = "Guest"

ALL_ROLES = (SPA_DIRECTOR, COMPLIANCE_OFFICER, SPA_COORDINATOR, THERAPIST, GUEST)


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_guest(self):
        return self.role == GUEST

    @property
    def is_therapist(self):
        return self.role == THERAPIST


def authenticate(*allowed_roles):
    """Rung 1 then rung 2. Returns the Caller."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id == "" or role is None or role == "":
        raise ApiError(errors.ERR_UNAUTHENTICATED,
                      "Both X-User-ID and X-User-Role headers are required.")
    if role not in ALL_ROLES or role not in allowed_roles:
        raise ApiError(errors.ERR_ROLE_NOT_PERMITTED,
                      "Role '%s' is not permitted for this operation." % role)
    return Caller(user_id, role)


def require_owner(caller, expected_id):
    """Rung 7: ownership for Guest and Therapist callers."""
    if caller.role in (GUEST, THERAPIST) and caller.user_id != expected_id:
        raise ApiError(errors.ERR_NOT_RESOURCE_OWNER,
                      "The caller does not own this resource.")


def require_guest_owner(caller, guest_id):
    if caller.role == GUEST and caller.user_id != guest_id:
        raise ApiError(errors.ERR_NOT_RESOURCE_OWNER,
                      "The caller does not own this resource.")


def require_therapist_owner(caller, therapist_id):
    if caller.role == THERAPIST and caller.user_id != therapist_id:
        raise ApiError(errors.ERR_NOT_RESOURCE_OWNER,
                      "The caller does not own this resource.")

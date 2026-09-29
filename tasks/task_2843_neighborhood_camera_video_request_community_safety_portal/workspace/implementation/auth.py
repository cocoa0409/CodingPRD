"""Authentication / authorisation (PRD 2.1, refusal ladder rules 1, 2, 6, 7)."""
from flask import request

from errors import ApiError
from store import db

ROLES = ("PlatformAdmin", "AgencyAdmin", "Officer", "Resident", "Moderator",
         "Anonymous")

ROLE_HEADER = "X-User-Role"
ID_HEADER = "X-User-ID"


class Actor(object):
    __slots__ = ("role", "user_id")

    def __init__(self, role, user_id):
        self.role = role
        self.user_id = user_id

    @property
    def officer(self):
        return db.officers.get(self.user_id)

    @property
    def resident(self):
        return db.residents.get(self.user_id)


def authenticate(allowed_roles, auth_exempt=False):
    """Rule 1 then rule 2 of the order of refusal."""
    role = request.headers.get(ROLE_HEADER)
    user_id = request.headers.get(ID_HEADER)

    if auth_exempt:
        # Resident self-registration is exempt from the header requirement
        # entirely (PRD 2.1).
        if role is None or role.strip() == "":
            role = "Anonymous"
    else:
        if role is None or role not in ROLES:
            raise ApiError("ERR_UNAUTHENTICATED",
                           "A recognised %s header is required" % ROLE_HEADER)
        if role != "Anonymous" and (user_id is None or user_id.strip() == ""):
            raise ApiError("ERR_UNAUTHENTICATED",
                           "A non-empty %s header is required" % ID_HEADER)

    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Role %s may not perform this operation" % role)
    return Actor(role, user_id)


def mismatch(message="Acting identity does not own this resource"):
    raise ApiError("ERR_IDENTITY_MISMATCH", message)


def sod(message="Separated duties violated"):
    raise ApiError("ERR_SEGREGATION_OF_DUTIES", message)


def require_agency_scope(actor, agency_id):
    """AgencyAdmin acts as the agency; an Officer must belong to the agency."""
    if actor.role == "AgencyAdmin":
        if actor.user_id != agency_id:
            mismatch("Acting agency does not own this resource")
    elif actor.role == "Officer":
        officer = actor.officer
        if officer is None or officer["agency_id"] != agency_id:
            mismatch("Acting officer does not belong to this agency")


def require_officer(actor):
    officer = actor.officer
    if officer is None:
        mismatch("Acting officer is unknown")
    return officer


def require_officer_is(actor, officer_id, agency_id):
    """The acting officer must be a specific officer of a specific agency."""
    if actor.role != "Officer":
        return None
    officer = require_officer(actor)
    if officer["agency_id"] != agency_id:
        mismatch("Acting officer does not belong to this agency")
    if officer_id is not None and officer["id"] != officer_id:
        mismatch("Acting officer does not own this resource")
    return officer


def require_resident_scope(actor, resident_id):
    if actor.role == "Resident" and actor.user_id != resident_id:
        mismatch("Acting resident does not own this resource")


def acting_resident(actor, resident_id):
    """Resident row the caller acts as (only meaningful for role Resident)."""
    if actor.role != "Resident":
        return None
    resident = db.residents.get(actor.user_id)
    if resident is None or (resident_id is not None
                            and resident["id"] != resident_id):
        mismatch("Acting resident does not own this resource")
    return resident

"""Auth extraction, role checks, and posture gates."""
from flask import request
from db import db
from errors import err_unauthenticated, err_forbidden, ApiError, ERR_CIRCLE_FROZEN, ERR_CIRCLE_RESTRICTED

VALID_ROLES = {"Owner", "Admin", "Member", "Minor", "System"}
MEMBER_ROLES = {"Owner", "Admin", "Member", "Minor"}


class Actor:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_system(self):
        return self.role == "System"

    @property
    def member(self):
        """The Member row backing this actor, or None for System/unknown."""
        if self.role in MEMBER_ROLES:
            return db.members.get(self.user_id)
        return None


def get_actor():
    """Priority 1: headers present and role valid."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise err_unauthenticated()
    return Actor(user_id, role)


def require_roles(actor, allowed):
    """Priority 2a: role-name must be in the endpoint's roles list."""
    if actor.role not in allowed:
        raise err_forbidden()


def require_circle_member(actor, circle, allowed):
    """Priority 2b: for entity-backed roles, actor must be a member of the
    target circle and (for Owner/Admin) actually hold that role."""
    if actor.is_system:
        if "System" in allowed:
            return
        raise err_forbidden()
    if actor.role not in allowed:
        raise err_forbidden()
    member = actor.member
    if member is None or member["circle_id"] != circle["id"]:
        raise err_forbidden()
    if actor.role == "Owner" and member["role"] != "OWNER":
        raise err_forbidden()
    if actor.role == "Admin" and member["role"] != "ADMIN":
        raise err_forbidden()
    if actor.role == "Member" and member["role"] not in ("MEMBER",):
        # a MEMBER-role header must be backed by a MEMBER-role member row
        # (demoted ADMINs become MEMBER, so accept role==MEMBER only)
        raise err_forbidden()
    if actor.role == "Minor" and member["role"] != "MINOR":
        raise err_forbidden()


def require_circle_admin(actor, circle):
    """Actor must be OWNER or ADMIN of the circle."""
    if actor.is_system:
        raise err_forbidden()
    member = actor.member
    if member is None or member["circle_id"] != circle["id"]:
        raise err_forbidden()
    if member["role"] not in ("OWNER", "ADMIN"):
        raise err_forbidden()


def require_circle_owner(actor, circle):
    if actor.is_system:
        raise err_forbidden()
    member = actor.member
    if member is None or member["circle_id"] != circle["id"]:
        raise err_forbidden()
    if member["role"] != "OWNER":
        raise err_forbidden()


def circle_posture(circle):
    """Derived: FROZEN > RESTRICTED > OPEN."""
    status = circle["subscription_status"]
    if status in ("SUSPENDED", "CANCELLED"):
        return "FROZEN"
    if status == "PAST_DUE":
        return "RESTRICTED"
    for h in db.compliance_holds.values():
        if h["circle_id"] == circle["id"] and h["hold_status"] == "OPEN":
            return "RESTRICTED"
    return "OPEN"


def posture_of(circle):
    p = circle_posture(circle)
    circle["circle_posture"] = p
    return p


def require_not_frozen(circle):
    if circle_posture(circle) == "FROZEN":
        raise ApiError(ERR_CIRCLE_FROZEN, 409, "Circle posture FROZEN blocks this mutation")


def require_not_restricted(circle):
    if circle_posture(circle) == "RESTRICTED":
        raise ApiError(ERR_CIRCLE_RESTRICTED, 409, "Circle posture RESTRICTED blocks assistance-unit consumption")


def check_frozen_read(actor, circle):
    """FROZEN posture: location-sharing reads to non-Owner members refused."""
    if circle_posture(circle) == "FROZEN":
        if actor.is_system:
            return
        member = actor.member
        if member is None or member["role"] != "OWNER" or member["circle_id"] != circle["id"]:
            raise ApiError(ERR_CIRCLE_FROZEN, 409, "Circle posture FROZEN blocks this read")

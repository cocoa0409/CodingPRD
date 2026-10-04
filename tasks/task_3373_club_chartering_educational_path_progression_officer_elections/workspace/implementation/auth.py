"""Authentication, role authorisation and the ownership clauses.

PRD section 2.1:
  * every request carries X-User-ID and X-User-Role;
  * the four recognised roles are WorldHeadquarters, ClubOfficer, Member and
    DistrictDirector;
  * WorldHeadquarters acts opaquely and without an ownership check;
  * ClubOfficer's X-User-ID names an acting Membership, so club-scoped
    operations are refused for a membership of any other club;
  * Member's and DistrictDirector's X-User-ID names an acting Member, and
    ownership compares the resource's member foreign key to it.
"""

from errors import ApiError
import db

VALID_ROLES = ("WorldHeadquarters", "ClubOfficer", "Member", "DistrictDirector")


class Principal(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_hq(self):
        return self.role == "WorldHeadquarters"

    @property
    def is_officer(self):
        return self.role == "ClubOfficer"

    @property
    def officer_membership(self):
        """The Membership row that a ClubOfficer's X-User-ID names."""
        return db.MEMBERSHIPS.get(self.user_id)

    @property
    def officer_club_id(self):
        membership = self.officer_membership
        return membership["club_id"] if membership else None


def authenticate(headers):
    """Priority 1: both headers present and the role one of the four."""
    user_id = headers.get("X-User-ID")
    role = headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError("ERR_UNAUTHENTICATED")
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or role not in VALID_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return Principal(user_id, role)


def require_role(principal, allowed):
    """Priority 2 (role half): the acting role must be listed on the endpoint."""
    if principal.role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED")


# --- ownership clauses ------------------------------------------------------
def require_officer_of_club(principal, club_id):
    """ClubOfficer ownership: the acting Membership must belong to the club."""
    if principal.is_hq:
        return
    if principal.role != "ClubOfficer":
        raise ApiError("ERR_UNAUTHORIZED")
    if principal.officer_club_id is None or principal.officer_club_id != club_id:
        raise ApiError("ERR_UNAUTHORIZED")


def require_owns_membership(principal, membership):
    """Shared renew ownership: Member matches member_id, ClubOfficer its club."""
    if principal.is_hq:
        return
    if principal.role == "ClubOfficer":
        require_officer_of_club(principal, membership["club_id"])
        return
    if principal.role == "Member":
        if membership["member_id"] != principal.user_id:
            raise ApiError("ERR_UNAUTHORIZED")
        return
    raise ApiError("ERR_UNAUTHORIZED")


def require_member_identity(principal, member_id):
    """Member ownership: X-User-ID must equal the resource's member FK."""
    if principal.is_hq:
        return
    if principal.role == "Member" and principal.user_id == member_id:
        return
    raise ApiError("ERR_UNAUTHORIZED")


def require_path_owner(principal, path):
    """Member ownership through the path's membership_id."""
    if principal.is_hq:
        return
    if principal.role != "Member":
        raise ApiError("ERR_UNAUTHORIZED")
    membership = db.MEMBERSHIPS.get(path["membership_id"])
    if membership is None or membership["member_id"] != principal.user_id:
        raise ApiError("ERR_UNAUTHORIZED")


def require_evaluator_owner(principal, completion):
    """Member ownership through the completion's evaluator_member_id."""
    if principal.is_hq:
        return
    if principal.role != "Member":
        raise ApiError("ERR_UNAUTHORIZED")
    if completion.get("evaluator_member_id") != principal.user_id:
        raise ApiError("ERR_UNAUTHORIZED")


def require_director_not_nominee(principal, term):
    """DistrictDirector training clause: the director differs from the officer."""
    if principal.is_hq:
        return
    if principal.role != "DistrictDirector":
        raise ApiError("ERR_UNAUTHORIZED")
    if principal.user_id == term["member_id"]:
        raise ApiError("ERR_UNAUTHORIZED")


def require_director_of_visit(principal, visit):
    """DistrictDirector visit clause: X-User-ID equals director_member_id."""
    if principal.is_hq:
        return
    if principal.role != "DistrictDirector":
        raise ApiError("ERR_UNAUTHORIZED")
    if principal.user_id != visit["director_member_id"]:
        raise ApiError("ERR_UNAUTHORIZED")

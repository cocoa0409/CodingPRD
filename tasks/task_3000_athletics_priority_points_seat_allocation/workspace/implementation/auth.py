"""Identity, roles and role-based access control (PRD section 2.1, 2.8 steps 1-4)."""
from flask import request

from errors import err

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

DEVELOPMENT_OFFICER = "DevelopmentOfficer"
POINTS_CERTIFIER = "PointsCertifier"
DISPUTE_ANALYST = "DisputeAnalyst"
POLICY_COMMITTEE = "PolicyCommittee"
DONOR = "Donor"
PLATFORM_ADMIN = "PlatformAdmin"

ALL_ROLES = (
    DEVELOPMENT_OFFICER,
    POINTS_CERTIFIER,
    DISPUTE_ANALYST,
    POLICY_COMMITTEE,
    DONOR,
    PLATFORM_ADMIN,
)


class Caller(object):
    """The authenticated caller of the current request."""

    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_donor(self):
        return self.role == DONOR


def require(*roles):
    """Steps 1 and 2 of PRD section 2.8, run before anything else."""
    allowed = []
    for entry in roles:
        if isinstance(entry, (list, tuple, set, frozenset)):
            allowed.extend(entry)
        else:
            allowed.append(entry)
    raw_id = request.headers.get(USER_ID_HEADER)
    raw_role = request.headers.get(USER_ROLE_HEADER)
    if raw_id is None or str(raw_id).strip() == "":
        raise err("ERR_UNAUTHENTICATED",
                  "the %s header is required and must not be empty" % USER_ID_HEADER)
    if raw_role is None or str(raw_role).strip() == "":
        raise err("ERR_UNAUTHENTICATED",
                  "the %s header is required and must not be empty" % USER_ROLE_HEADER)
    role = str(raw_role)
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE",
                  "role '%s' may not call this endpoint" % role)
    return Caller(str(raw_id), role)


def require_owner(caller, owner_donor_id):
    """Step 3: a Donor caller may only act on their own resources."""
    if caller.role == DONOR and caller.user_id != owner_donor_id:
        raise err("ERR_NOT_RESOURCE_OWNER",
                  "the acting donor does not own this resource")


def require_segregation(caller, other_user_id, label):
    """Step 4: segregation of duties, compared on X-User-ID values."""
    if other_user_id is not None and caller.user_id == other_user_id:
        raise err("ERR_SEGREGATION_OF_DUTIES",
                  "the acting user may not also be the %s" % label)


# ---------------------------------------------------------------------------
# The role sets each endpoint authorises (PRD section 4)
# ---------------------------------------------------------------------------
STAFF_ONLY = (DEVELOPMENT_OFFICER, POINTS_CERTIFIER, DISPUTE_ANALYST,
              POLICY_COMMITTEE, PLATFORM_ADMIN)
STAFF_AND_DONOR = (DEVELOPMENT_OFFICER, POINTS_CERTIFIER, DISPUTE_ANALYST,
                   POLICY_COMMITTEE, PLATFORM_ADMIN, DONOR)
NO_ANALYST = (DEVELOPMENT_OFFICER, POINTS_CERTIFIER, POLICY_COMMITTEE,
              PLATFORM_ADMIN, DONOR)
ANALYSIS_READERS = (DEVELOPMENT_OFFICER, POINTS_CERTIFIER, PLATFORM_ADMIN)
DISPUTE_READERS = (DEVELOPMENT_OFFICER, DISPUTE_ANALYST, POLICY_COMMITTEE,
                   PLATFORM_ADMIN, DONOR)
SECTION_READERS = (DEVELOPMENT_OFFICER, POINTS_CERTIFIER, POLICY_COMMITTEE,
                   PLATFORM_ADMIN)
OFFICE = (DEVELOPMENT_OFFICER, PLATFORM_ADMIN)
ADMIN_ONLY = (PLATFORM_ADMIN,)
CERTIFIER_ONLY = (POINTS_CERTIFIER,)
ANALYST_ONLY = (DISPUTE_ANALYST,)
COMMITTEE_ONLY = (POLICY_COMMITTEE,)
DONOR_ONLY = (DONOR,)
DONOR_AND_OFFICER = (DONOR, DEVELOPMENT_OFFICER)
EVERY_ROLE = ALL_ROLES

"""Header authentication (pipeline priorities 1-2) and ownership (priority 3)."""
from flask import request

from errors import fail

ROLES = (
    "ProgramAdmin",
    "ApplicantSponsor",
    "InnovatorSponsor",
    "RegulatoryReviewer",
    "FacilityInspector",
)
ALL_ROLES = list(ROLES)


def auth():
    """Priority 1: both context headers present, role declared."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        fail("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
             "X-User-ID and X-User-Role headers must both be present and "
             "X-User-Role must be a declared role")
    return uid, role


def require_role(role, allowed):
    """Priority 2: the caller's role must be listed for the endpoint."""
    if role not in allowed:
        fail("ERR_INSUFFICIENT_PERMISSIONS",
             "Role %s is not permitted for this endpoint" % role)


def own_application(uid, app):
    """Priority 3: ApplicantSponsor's X-User-ID must equal applicant_id."""
    if app["applicant_id"] != uid:
        fail("ERR_NOT_RESOURCE_OWNER",
             "ApplicantSponsor does not own the target application")


def own_reference_product(uid, rp):
    """Priority 3: InnovatorSponsor's X-User-ID must equal patent_owner_user_id."""
    if rp["patent_owner_user_id"] != uid:
        fail("ERR_NOT_RESOURCE_OWNER",
             "InnovatorSponsor does not own the patent side of this reference product")

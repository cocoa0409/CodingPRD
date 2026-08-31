"""Authentication (rung 1), role authorisation (rung 2) and ownership (rung 3)."""

from flask import request

from .errors import ApiError
from .store import store

ROLES = [
    "ProgramDirector",
    "IntakeCoordinator",
    "ReferralSource",
    "Counselor",
    "VolunteerCompanion",
    "Participant",
    "GrantOfficer",
]

ENTITY_BACKED = {"Counselor", "VolunteerCompanion", "Participant"}

HEADER_USER = "X-User-ID"
HEADER_ROLE = "X-User-Role"


class Ctx(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate(allowed_roles):
    """Rungs 1 and 2 of the rejection ladder."""
    user_id = request.headers.get(HEADER_USER)
    role = request.headers.get(HEADER_ROLE)
    if user_id is None or str(user_id).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if role is None or str(role).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role is not a declared role.")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Role %s may not call this endpoint." % role)
    return Ctx(user_id, role)


def _deny():
    raise ApiError("ERR_NOT_RESOURCE_OWNER", "The acting principal does not own this resource.")


def own_participant(ctx, participant):
    """Participant role acting on a participant-identified resource."""
    if ctx.role == "Participant" and participant.get("id") != ctx.user_id:
        _deny()


def own_participant_field(ctx, rec):
    """Participant role acting on an Enrollment / Invitation / AnniversaryOutreach."""
    if ctx.role == "Participant" and rec.get("participant_id") != ctx.user_id:
        _deny()


def own_counseling_referral(ctx, referral):
    """Counselor role acting on a counselling referral.

    The comparison is against CounselingReferral.counselor_id; a referral that
    carries no counsellor yet yields no ownership determination.
    """
    if ctx.role == "Counselor":
        owner = referral.get("counselor_id")
        if owner is not None and owner != ctx.user_id:
            _deny()


def own_counseling_referral_strict(ctx, referral):
    if ctx.role == "Counselor" and referral.get("counselor_id") != ctx.user_id:
        _deny()


def own_volunteer_path(ctx, volunteer):
    if ctx.role == "VolunteerCompanion" and volunteer.get("id") != ctx.user_id:
        _deny()


def own_match(ctx, match):
    if ctx.role == "VolunteerCompanion" and match.get("companion_id") != ctx.user_id:
        _deny()


def own_outreach_volunteer(ctx, outreach):
    """A volunteer qualifies through an ACTIVE match with the touchpoint's participant."""
    if ctx.role != "VolunteerCompanion":
        return
    for match in store.all("CompanionMatch"):
        if (match.get("companion_id") == ctx.user_id
                and match.get("participant_id") == outreach.get("participant_id")
                and match.get("status") == "ACTIVE"):
            return
    _deny()

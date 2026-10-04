"""Authentication, RBAC and the volunteer safety battery (PRD 2.1 / 2.7).

Band 1: X-User-Role must name a declared role; X-User-ID is required for
every role except PublicUser; entity-backed roles must reference a live
record of the backing type carrying the required capability tag.
Band 2: the authenticated role must be listed for the endpoint.
Bands 10/11: volunteer-backed mutations require the acting volunteer to be
ACTIVE with a CURRENT attestation (attest itself is the attestation cure).
"""
from flask import request

from errors import (attestation_lapsed, unauthenticated, unauthorized_role,
                    volunteer_suspended)
from store import store

LEAGUE_ADMIN = "LeagueAdmin"
CHAPTER_COORDINATOR = "ChapterCoordinator"
QUESTIONNAIRE_EDITOR = "QuestionnaireEditor"
NEUTRALITY_REVIEWER = "NeutralityReviewer"
FORUM_MODERATOR = "ForumModerator"
CANDIDATE = "Candidate"
PUBLIC_USER = "PublicUser"

ROLES = (LEAGUE_ADMIN, CHAPTER_COORDINATOR, QUESTIONNAIRE_EDITOR,
         NEUTRALITY_REVIEWER, FORUM_MODERATOR, CANDIDATE, PUBLIC_USER)

ROLE_CAPABILITY = {
    CHAPTER_COORDINATOR: "COORDINATOR",
    QUESTIONNAIRE_EDITOR: "EDITOR",
    NEUTRALITY_REVIEWER: "REVIEWER",
    FORUM_MODERATOR: "MODERATOR",
}

VOLUNTEER_BACKED = (CHAPTER_COORDINATOR, QUESTIONNAIRE_EDITOR,
                    NEUTRALITY_REVIEWER, FORUM_MODERATOR)


def authenticate():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or role not in ROLES:
        raise unauthenticated("X-User-Role header is missing or names an unknown role")
    if role == PUBLIC_USER:
        # The only role exempt from X-User-ID; any supplied value is opaque.
        return None, role, None
    if not uid:
        raise unauthenticated("X-User-ID header is required for this role")
    if role == LEAGUE_ADMIN:
        # Opaque operator identifier, never compared to any entity id.
        return uid, role, None
    if role == CANDIDATE:
        if uid not in store.filings:
            raise unauthenticated("X-User-ID does not reference a CandidateFiling")
        return uid, role, None
    capability = ROLE_CAPABILITY[role]
    volunteer = store.volunteers.get(uid)
    if volunteer is None or capability not in volunteer["roles"]:
        raise unauthenticated(
            "X-User-ID does not reference a Volunteer carrying the %s capability"
            % capability)
    return uid, role, volunteer


def require_roles(*allowed):
    uid, role, volunteer = authenticate()
    if role not in allowed:
        raise unauthorized_role()
    return uid, role, volunteer


def attestation_current(volunteer):
    """Lazy attestation evaluation against the logical clock (PRD 2.4/2.10)."""
    return store.clock <= volunteer["attestation_expires_at"]


def check_active(volunteer):
    if volunteer["status"] == "SUSPENDED":
        raise volunteer_suspended()


def check_active_current(volunteer):
    """Bands 10-11 for the acting volunteer on a privileged mutation."""
    check_active(volunteer)
    if not attestation_current(volunteer):
        raise attestation_lapsed()

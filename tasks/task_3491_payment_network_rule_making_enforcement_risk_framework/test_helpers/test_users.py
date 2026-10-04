"""Pre-built role headers for the four PRD §2.1 roles.

Identity model (PRD §2.1):
- PlatformAdmin and Auditor are OPAQUE roles: X-User-ID is not tied to any
  persisted entity. Distinct opaque ids still matter for segregation-of-duties
  rules (the admin who escalated an inquiry may not uphold the resulting
  action; the auditor who created an engagement may not complete it), so both
  a primary and an alternate header set are provided for each.
- ParticipantOfficer and VotingDelegate are ENTITY-BACKED roles: X-User-ID must
  equal the id of the owning Participant on ownership-gated operations. The
  shared constants below are fallbacks ONLY for tests that do not exercise
  ownership (400/404/unauthenticated checks); any ownership-gated call MUST be
  built with make_participant_officer_headers(participant["id"]) or
  make_voting_delegate_headers(participant["id"]).
"""

from prd_bench_local_runner.testing import build_user_headers

PLATFORM_ADMIN_PRIMARY_ID = "admin-primary-1"
PLATFORM_ADMIN_ALT_ID = "admin-alt-1"
AUDITOR_PRIMARY_ID = "auditor-1"
AUDITOR_ALT_ID = "auditor-2"

TEST_USERS = {
    # Opaque roles — canonical shared form.
    "platform_admin_headers": build_user_headers(PLATFORM_ADMIN_PRIMARY_ID, "PlatformAdmin"),
    "platform_admin_alt_headers": build_user_headers(PLATFORM_ADMIN_ALT_ID, "PlatformAdmin"),
    "auditor_headers": build_user_headers(AUDITOR_PRIMARY_ID, "Auditor"),
    "auditor_alt_headers": build_user_headers(AUDITOR_ALT_ID, "Auditor"),
    # Entity-backed roles — FALLBACK ONLY for non-ownership tests. These ids are
    # deliberately not any real Participant id; using them on an ownership-gated
    # call is the canonical ERR_FORBIDDEN-everything bug.
    "participant_officer_headers": build_user_headers("test-officer-1", "ParticipantOfficer"),
    "voting_delegate_headers": build_user_headers("test-delegate-1", "VotingDelegate"),
}


def make_platform_admin_headers(user_id: str) -> dict:
    """PlatformAdmin (opaque). Pass a distinct id for segregation-of-duties tests."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_participant_officer_headers(participant_id: str) -> dict:
    """ParticipantOfficer (entity-backed). user_id MUST be the owning Participant's id
    whenever the call is ownership-gated (originator create/transition/limit-patch,
    entry create/cancel/return, inquiry respond, attestation submit)."""
    return build_user_headers(participant_id, "ParticipantOfficer")


def make_voting_delegate_headers(participant_id: str) -> dict:
    """VotingDelegate (entity-backed). user_id MUST be the voting Participant's id
    for ballot cast/recast."""
    return build_user_headers(participant_id, "VotingDelegate")


def make_auditor_headers(user_id: str) -> dict:
    """Auditor (opaque). Pass a distinct id from the audit creator to complete it."""
    return build_user_headers(user_id, "Auditor")

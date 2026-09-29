"""Pre-built role headers for the six roles declared in PRD §2.1.

Five of the six roles carry an opaque identity: "`X-User-ID` is an opaque
operator identifier not tied to any persisted entity" (PRD §2.1), so shared
constants are the canonical form for them.  `Coach` is the one entity-backed
role — "When `X-User-Role` is `Coach`, `X-User-ID` is the `id` of the acting
`Volunteer` record" — so ownership-gated coach calls MUST use
``make_coach_headers(volunteer_id)``.

Because credentialing enforces segregation of duties across three distinct
`X-User-ID` values (PRD §2.8), distinct officer identities are provided.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "program_manager_headers": build_user_headers("manager-1", "ProgramManager"),
    "credentialing_officer_headers": build_user_headers(
        "officer-1", "CredentialingOfficer"),
    "medical_reviewer_headers": build_user_headers("reviewer-1", "MedicalReviewer"),
    # Coach is entity_backed: this shared constant is only for tests that do not
    # exercise credential ownership (e.g. role-authorisation probes).
    "coach_headers": build_user_headers("coach-reader", "Coach"),
    "competition_director_headers": build_user_headers(
        "director-1", "CompetitionDirector"),
    "health_screening_lead_headers": build_user_headers(
        "screening-lead-1", "HealthScreeningLead"),
}

# Distinct credentialing officers, so screening, training and certification can
# each be recorded by a different X-User-ID (PRD §2.8).
OFFICERS = {
    f"officer-{i}": build_user_headers(f"officer-{i}", "CredentialingOfficer")
    for i in range(1, 10)
}

REVIEWERS = {
    f"reviewer-{i}": build_user_headers(f"reviewer-{i}", "MedicalReviewer")
    for i in range(1, 4)
}


def make_program_manager_headers(user_id: str) -> dict:
    """ProgramManager identity is opaque; the id is only ever recorded."""
    return build_user_headers(user_id, "ProgramManager")


def make_credentialing_officer_headers(user_id: str) -> dict:
    """CredentialingOfficer identity is opaque but compared against other
    officers' ids for segregation of duties (PRD §2.8)."""
    return build_user_headers(user_id, "CredentialingOfficer")


def make_medical_reviewer_headers(user_id: str) -> dict:
    """MedicalReviewer identity is opaque; recorded as reviewed_by_user_id."""
    return build_user_headers(user_id, "MedicalReviewer")


def make_competition_director_headers(user_id: str) -> dict:
    """CompetitionDirector identity is opaque."""
    return build_user_headers(user_id, "CompetitionDirector")


def make_health_screening_lead_headers(user_id: str) -> dict:
    """HealthScreeningLead identity is opaque."""
    return build_user_headers(user_id, "HealthScreeningLead")


def make_coach_headers(volunteer_id: str) -> dict:
    """For Coach (entity-backed on Volunteer).

    Pass the acting Volunteer's own ``id``: PRD §2.1 requires that "the
    credential named by that session's `coach_credential_id` must belong to the
    volunteer whose `id` equals `X-User-ID`".
    """
    return build_user_headers(volunteer_id, "Coach")


ALL_ROLE_NAMES = [
    "ProgramManager",
    "CredentialingOfficer",
    "MedicalReviewer",
    "Coach",
    "CompetitionDirector",
    "HealthScreeningLead",
]

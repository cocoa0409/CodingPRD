"""Pre-built role headers for every role in the PRD.

Four roles are opaque — their X-User-ID is an operator identifier the server never
compares to any record's id. Three roles are entity-backed: their X-User-ID must be
the id of the persisted record they act as, so ownership-gated calls MUST use the
per-instance builder with the real entity id.
"""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
# Safe for the four opaque roles, and for entity-backed roles only in tests whose
# outcome does not depend on the caller owning the subject resource.
TEST_USERS = {
    "program_director_headers": build_user_headers("pd-001", "ProgramDirector"),
    "intake_coordinator_headers": build_user_headers("ic-001", "IntakeCoordinator"),
    "referral_source_headers": build_user_headers("rs-001", "ReferralSource"),
    "grant_officer_headers": build_user_headers("go-001", "GrantOfficer"),
    # Entity-backed roles: fallbacks for non-ownership tests only.
    "counselor_headers": build_user_headers("cn-unowned-001", "Counselor"),
    "volunteer_companion_headers": build_user_headers("vc-unowned-001", "VolunteerCompanion"),
    "participant_headers": build_user_headers("pt-unowned-001", "Participant"),
}

PD = TEST_USERS["program_director_headers"]
IC = TEST_USERS["intake_coordinator_headers"]
RS = TEST_USERS["referral_source_headers"]
GO = TEST_USERS["grant_officer_headers"]


def make_program_director_headers(user_id: str) -> dict:
    """ProgramDirector is opaque; the operator id is recorded on grant reports."""
    return build_user_headers(user_id, "ProgramDirector")


def make_intake_coordinator_headers(user_id: str) -> dict:
    """IntakeCoordinator is opaque."""
    return build_user_headers(user_id, "IntakeCoordinator")


def make_referral_source_headers(user_id: str) -> dict:
    """ReferralSource is opaque."""
    return build_user_headers(user_id, "ReferralSource")


def make_grant_officer_headers(user_id: str) -> dict:
    """GrantOfficer is opaque; the operator id is compared with submitted_by_user_id."""
    return build_user_headers(user_id, "GrantOfficer")


def make_participant_headers(participant_id: str) -> dict:
    """Pass the acting Participant's own id — ownership is checked against it."""
    return build_user_headers(participant_id, "Participant")


def make_counselor_headers(counselor_id: str) -> dict:
    """Pass the acting Counselor's own id — ownership is checked against it."""
    return build_user_headers(counselor_id, "Counselor")


def make_volunteer_companion_headers(companion_id: str) -> dict:
    """Pass the acting VolunteerCompanion's own id — ownership is checked against it."""
    return build_user_headers(companion_id, "VolunteerCompanion")


def headers_without_role(user_id: str = "rs-001") -> dict:
    """Headers carrying X-User-ID but no X-User-Role at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str = "ReferralSource") -> dict:
    """Headers carrying X-User-Role but no X-User-ID at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}

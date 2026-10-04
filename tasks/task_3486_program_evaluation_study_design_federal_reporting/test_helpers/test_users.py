"""Pre-built role headers for every role in the PRD.

Identity model (PRD user/RBAC section):
- Participant is entity-backed: X-User-ID MUST equal the acting Participant
  record's id. Always build these headers with make_participant_headers(
  participant["id"]) — the shared constant is only a fallback for tests whose
  outcome does not depend on ownership.
- The other eight roles are opaque operator identities; X-User-ID is recorded
  (submitted_by_id / decided_by_id / reviewed_by_id / prepared_by_id) but never
  compared to an entity id. Segregation-of-duties tests need a header whose
  X-User-ID collides with another operator's id, so every role also gets a
  make_<role>_headers(user_id) builder.
"""
from prd_bench_local_runner.testing import build_user_headers


def make_agency_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AgencyOfficer")


def make_principal_investigator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PrincipalInvestigator")


def make_study_director_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "StudyDirector")


def make_data_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DataManager")


def make_irb_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "IRBReviewer")


def make_peer_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PeerReviewer")


def make_participant_headers(user_id: str) -> dict:
    """Entity-backed role: pass the actual Participant.id as user_id whenever
    the call is ownership-gated (consent, self-withdraw, self read)."""
    return build_user_headers(user_id, "Participant")


def make_external_researcher_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ExternalResearcher")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


# Shared constants — canonical identities used by composite fixtures.
# Distinct ids per operator so segregation-of-duties checks pass in setups:
# pi-1 submits IRB protocols and reports; irb-1 / peer-1 / ao-1 decide them;
# dm-1 prepares restricted-use files.
TEST_USERS = {
    "agency_officer_headers": make_agency_officer_headers("ao-1"),
    "principal_investigator_headers": make_principal_investigator_headers("pi-1"),
    "study_director_headers": make_study_director_headers("sd-1"),
    "data_manager_headers": make_data_manager_headers("dm-1"),
    "irb_reviewer_headers": make_irb_reviewer_headers("irb-1"),
    "peer_reviewer_headers": make_peer_reviewer_headers("peer-1"),
    # Fallback only — ownership-gated calls must use make_participant_headers.
    "participant_headers": make_participant_headers("participant-1"),
    "external_researcher_headers": make_external_researcher_headers("er-1"),
    "platform_admin_headers": make_platform_admin_headers("admin-1"),
}

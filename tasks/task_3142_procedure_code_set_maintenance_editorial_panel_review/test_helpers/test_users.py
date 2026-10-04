"""Pre-built role headers for every role declared in the PRD (SS2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for calls that do not exercise ownership.
TEST_USERS = {
    "editorial_staff_headers": build_user_headers("test-editorial-staff-1", "EditorialStaff"),
    "editorial_panel_chair_headers": build_user_headers("test-panel-chair-1", "EditorialPanelChair"),
    "licensing_officer_headers": build_user_headers("test-licensing-officer-1", "LicensingOfficer"),
    # entity_backed fallbacks — only for tests with no ownership gate.
    "committee_reviewer_headers": build_user_headers("test-committee-reviewer-1", "CommitteeReviewer"),
    "licensee_headers": build_user_headers("test-licensee-1", "Licensee"),
    "change_applicant_headers": build_user_headers("test-change-applicant-1", "ChangeApplicant"),
}

# A second editorial staff identity, for segregation-of-duties probes.
SECOND_EDITORIAL_STAFF_HEADERS = build_user_headers("test-editorial-staff-2", "EditorialStaff")
SECOND_PANEL_CHAIR_HEADERS = build_user_headers("test-panel-chair-2", "EditorialPanelChair")


def make_committee_reviewer_headers(user_id: str) -> dict:
    """CommitteeReviewer is entity_backed:AdvisoryCommitteeReview — pass the
    AdvisoryCommitteeReview.id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "CommitteeReviewer")


def make_licensee_headers(user_id: str) -> dict:
    """Licensee is entity_backed:LicensingAgreement — pass the LicensingAgreement.id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Licensee")


def make_change_applicant_headers(user_id: str) -> dict:
    """ChangeApplicant is entity_backed:ChangeApplicant — pass the ChangeApplicant.id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "ChangeApplicant")
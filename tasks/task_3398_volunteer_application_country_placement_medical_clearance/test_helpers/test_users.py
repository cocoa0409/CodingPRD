"""Pre-built role headers for every role in the PRD.

The Applicant role is entity-backed: X-User-ID must equal the acting
Applicant's id whenever a call is ownership-gated (application submit /
withdraw, invitation accept / decline, medical clearance create / resubmit,
match-list reads, application creation). Use make_applicant_headers with the
real Applicant.id for those calls; the shared "applicant_headers" constant is
only a fallback for tests that never touch an owned resource.
"""

from prd_bench_local_runner.testing import build_user_headers

# Distinct LegalReviewer identities: segregation of duties forbids the same
# reviewer from adjudicating the background and determining suitability.
LEGAL_REVIEWER_BACKGROUND_ID = "legal-1"
LEGAL_REVIEWER_SUITABILITY_ID = "legal-2"
MEDICAL_OFFICER_ID = "medical-1"
PLACEMENT_OFFICER_ID = "po-1"
TRAINING_DIRECTOR_ID = "training-1"
COUNTRY_DIRECTOR_ID = "country-1"
SYSTEM_ADMIN_ID = "admin-1"

TEST_USERS = {
    "system_admin_headers": build_user_headers(SYSTEM_ADMIN_ID, "SystemAdmin"),
    # Entity-backed fallback — non-ownership tests only (see module docstring).
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
    "placement_officer_headers": build_user_headers(PLACEMENT_OFFICER_ID, "PlacementOfficer"),
    "medical_officer_headers": build_user_headers(MEDICAL_OFFICER_ID, "MedicalOfficer"),
    "legal_reviewer_headers": build_user_headers(LEGAL_REVIEWER_BACKGROUND_ID, "LegalReviewer"),
    "legal_reviewer_background_headers": build_user_headers(LEGAL_REVIEWER_BACKGROUND_ID, "LegalReviewer"),
    "legal_reviewer_suitability_headers": build_user_headers(LEGAL_REVIEWER_SUITABILITY_ID, "LegalReviewer"),
    "training_director_headers": build_user_headers(TRAINING_DIRECTOR_ID, "TrainingDirector"),
    "country_director_headers": build_user_headers(COUNTRY_DIRECTOR_ID, "CountryDirector"),
}


def make_applicant_headers(user_id: str) -> dict:
    """For the entity-backed Applicant role. Pass the actual Applicant.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Applicant")


def make_legal_reviewer_headers(user_id: str) -> dict:
    """For picking ad-hoc LegalReviewer identities (e.g. the self-approval
    segregation-of-duties probe)."""
    return build_user_headers(user_id, "LegalReviewer")

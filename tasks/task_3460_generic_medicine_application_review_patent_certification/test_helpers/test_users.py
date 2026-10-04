"""Pre-built role headers for every role in the PRD (section 2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants for opaque roles and for tests that do not exercise ownership.
TEST_USERS = {
    "program_admin_headers": build_user_headers("program-admin-1", "ProgramAdmin"),
    "regulatory_reviewer_headers": build_user_headers("reviewer-1", "RegulatoryReviewer"),
    "facility_inspector_headers": build_user_headers("inspector-1", "FacilityInspector"),
    # Fallback for non-ownership calls only; patent-side writes must use
    # make_innovator_headers(product["patent_owner_user_id"]).
    "innovator_headers": build_user_headers("innovator-ops-1", "InnovatorSponsor"),
    # Fallback for non-ownership calls only; ApplicantSponsor is entity-backed
    # (X-User-ID must equal the ApplicantCompany id) — use make_applicant_headers.
    "applicant_headers": build_user_headers("applicant-placeholder", "ApplicantSponsor"),
}


def make_applicant_headers(user_id: str) -> dict:
    """ApplicantSponsor is entity-backed: pass the actual ApplicantCompany id."""
    return build_user_headers(user_id, "ApplicantSponsor")


def make_innovator_headers(user_id: str) -> dict:
    """InnovatorSponsor: pass the reference product's patent_owner_user_id."""
    return build_user_headers(user_id, "InnovatorSponsor")

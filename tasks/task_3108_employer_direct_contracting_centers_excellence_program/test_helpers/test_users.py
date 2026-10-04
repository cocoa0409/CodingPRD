"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# employer-scope ownership checks.
TEST_USERS = {
    "program_admin_headers": build_user_headers("test-program-admin-1", "ProgramAdmin"),
    # entity_backed:Employer — fallback for non-ownership tests only.
    "employer_rep_headers": build_user_headers("test-employer-rep-1", "EmployerRep"),
    "care_coordinator_headers": build_user_headers(
        "test-care-coordinator-1", "CareCoordinator"
    ),
    "physician_reviewer_headers": build_user_headers(
        "test-physician-reviewer-1", "PhysicianReviewer"
    ),
    "claims_admin_headers": build_user_headers("test-claims-admin-1", "ClaimsAdmin"),
}


def make_employer_rep_headers(employer_id: str) -> dict:
    """For EmployerRep (entity_backed:Employer). Pass the actual Employer.id as
    employer_id whenever the call is scope-checked (report generation, scoped
    reads) — ownership compares the resource's employer FK to X-User-ID."""
    return build_user_headers(employer_id, "EmployerRep")

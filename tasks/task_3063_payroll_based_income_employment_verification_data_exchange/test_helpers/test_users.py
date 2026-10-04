"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the opaque PlatformAdmin role, and for tests that do
# not exercise ownership. Entity-backed roles MUST use the per-instance builders
# below whenever the addressed call is ownership-gated.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "employer_headers": build_user_headers("test-employer-1", "Employer"),
    "worker_headers": build_user_headers("test-worker-1", "CoveredWorker"),
    "verifier_headers": build_user_headers("test-verifier-1", "Verifier"),
}


def make_employer_headers(employer_id: str) -> dict:
    """For Employer (entity_backed:Employer). Pass the actual Employer.id whenever
    the call is ownership-gated."""
    return build_user_headers(employer_id, "Employer")


def make_worker_headers(worker_id: str) -> dict:
    """For CoveredWorker (entity_backed:CoveredWorker). Pass the actual
    CoveredWorker.id whenever the call is ownership-gated."""
    return build_user_headers(worker_id, "CoveredWorker")


def make_verifier_headers(verifier_id: str) -> dict:
    """For Verifier (entity_backed:Verifier). Pass the actual Verifier.id whenever
    the call is ownership-gated."""
    return build_user_headers(verifier_id, "Verifier")
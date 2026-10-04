"""Pre-built role headers for every role in the PRD.

RecruiterUser is entity-backed: X-User-ID must equal the acting Recruiter's
id, so callers must use make_recruiter_user_headers(recruiter["id"]) for any
ownership-gated call. The shared constant is only for non-ownership tests.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constant is the canonical form.
    "contract_admin_headers": build_user_headers("test-contract-admin-1", "ContractAdmin"),
    "seat_admin_headers": build_user_headers("test-seat-admin-1", "SeatAdmin"),
    "ats_service_headers": build_user_headers("test-ats-service-1", "AtsService"),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
    # entity_backed:Recruiter — fallback for non-ownership tests only.
    "recruiter_user_headers": build_user_headers("test-recruiter-user-1", "RecruiterUser"),
}


def make_recruiter_user_headers(user_id: str) -> dict:
    """For RecruiterUser (entity-backed by Recruiter). Pass the actual
    Recruiter.id as user_id whenever the call is ownership-gated (candidate
    search and message send check X-User-ID against the seat's
    assigned_recruiter_id)."""
    return build_user_headers(user_id, "RecruiterUser")

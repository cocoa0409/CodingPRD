"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# Candidate ownership. The Candidate role is entity-backed: use
# make_candidate_headers(candidate["id"]) for any ownership-gated call.
TEST_USERS = {
    "hr_admin_headers": build_user_headers("admin-1", "HRAdmin"),
    "hm_headers": build_user_headers("hm-1", "HiringManager"),
    "hm2_headers": build_user_headers("hm-2", "HiringManager"),
    "recruiter_headers": build_user_headers("rec-1", "Recruiter"),
    "comp_analyst_headers": build_user_headers("ca-1", "CompAnalyst"),
    "finance_headers": build_user_headers("fin-1", "FinanceController"),
    "director_headers": build_user_headers("dir-1", "DepartmentDirector"),
    "vp_headers": build_user_headers("vp-1", "VPPeople"),
    "screener_headers": build_user_headers("scr-1", "BackgroundScreener"),
    # Fallback constant for Candidate — only for non-ownership paths.
    "candidate_headers": build_user_headers("test-candidate-1", "Candidate"),
}


def make_candidate_headers(user_id: str) -> dict:
    """For Candidate (entity_backed:Candidate). Pass the actual Candidate.id as
    user_id whenever the call is ownership-gated (reads, accept, decline)."""
    return build_user_headers(user_id, "Candidate")


def make_hm_headers(user_id: str) -> dict:
    """HiringManager headers bound to a specific opaque user id (ownership of a
    requisition is keyed on hiring_manager_id == X-User-ID)."""
    return build_user_headers(user_id, "HiringManager")

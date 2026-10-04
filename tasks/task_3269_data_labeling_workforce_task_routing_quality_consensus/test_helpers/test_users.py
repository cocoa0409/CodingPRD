"""Pre-built role headers for every role in the PRD.

Worker is the entity-backed role: X-User-ID must be the id of the acting
WorkerIdentity, so every ownership-gated call must use make_worker_headers()
with the real worker id rather than the shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# PlatformAdmin, PlatformReviewer and Anonymous carry opaque identifiers that
# are never resolved against a persisted row, so shared constants are correct.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "reviewer_headers": build_user_headers("test-reviewer-1", "PlatformReviewer"),
    "reviewer_two_headers": build_user_headers("test-reviewer-2", "PlatformReviewer"),
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
    # entity_backed role: fallback only for calls that are not ownership gated.
    "worker_headers": build_user_headers("test-worker-1", "Worker"),
}


def make_worker_headers(worker_id: str) -> dict:
    """For the Worker role (entity_backed:WorkerIdentity).

    Pass the actual WorkerIdentity.id whenever the call compares the acting
    identity to a worker_id on a Commit, an AppealClaim or an Incident.
    """
    return build_user_headers(worker_id, "Worker")


def make_admin_headers(operator_id: str) -> dict:
    return build_user_headers(operator_id, "PlatformAdmin")


def make_reviewer_headers(operator_id: str) -> dict:
    return build_user_headers(operator_id, "PlatformReviewer")
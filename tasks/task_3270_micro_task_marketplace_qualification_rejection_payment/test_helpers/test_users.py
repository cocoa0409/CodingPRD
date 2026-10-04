"""
Pre-built role headers for every role on the platform.

``Anonymous`` and ``PlatformAdmin`` carry opaque identifiers that are not tied
to any persisted entity, so a shared constant is the canonical form for them.
``Requester`` and ``Worker`` are entity-backed: for any ownership-gated call the
acting principal must be the resource owner, so those roles get per-instance
builder functions that take the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constants are canonical.
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    # Entity-backed roles — shared constants are a fallback for tests that do
    # NOT exercise ownership; ownership-gated calls must use the builders below.
    "requester_headers": build_user_headers("test-requester-1", "Requester"),
    "worker_headers": build_user_headers("test-worker-1", "Worker"),
}


def make_requester_headers(requester_id: str) -> dict:
    """Headers for a Requester acting as itself.

    Pass the actual Requester.id whenever the call is ownership-gated (publish,
    cancel, sweep, approve, reject, bonus, deposit creation).
    """
    return build_user_headers(requester_id, "Requester")


def make_worker_headers(worker_id: str) -> dict:
    """Headers for a Worker acting as itself.

    Pass the actual Worker.id whenever the call is ownership-gated (accept,
    submit, return, dispute, payout request).
    """
    return build_user_headers(worker_id, "Worker")
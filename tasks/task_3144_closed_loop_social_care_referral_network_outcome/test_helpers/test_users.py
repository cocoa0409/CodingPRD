"""Pre-built role headers for every role in the PRD.

`NetworkCoordinator` is an opaque identity: the shared constant is canonical.
`CaseWorker`, `OrgAdmin`, and `FunderAdmin` are entity-backed by Organization:
ownership-gated calls must use the per-instance builders with the real org id,
and segregation-of-duties comparisons look at the full X-User-ID string
(including the `#<staff_label>` suffix).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # opaque role: shared constant is the canonical form.
    "coordinator_headers": build_user_headers("test-coordinator-1", "NetworkCoordinator"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "case_worker_headers": build_user_headers("test-caseworker-placeholder", "CaseWorker"),
    "org_admin_headers": build_user_headers("test-orgadmin-placeholder", "OrgAdmin"),
    "funder_admin_headers": build_user_headers("test-funderadmin-placeholder", "FunderAdmin"),
}


def make_case_worker_headers(org_id: str, staff_label: str = None) -> dict:
    """For CaseWorker (entity-backed by Organization). Pass the acting sender
    org's real id; add a staff_label suffix to distinguish individual workers."""
    user_id = f"{org_id}#{staff_label}" if staff_label else org_id
    return build_user_headers(user_id, "CaseWorker")


def make_org_admin_headers(org_id: str, staff_label: str = None) -> dict:
    """For OrgAdmin (entity-backed by Organization). Pass the acting receiver
    org's real id whenever the call is ownership-gated."""
    user_id = f"{org_id}#{staff_label}" if staff_label else org_id
    return build_user_headers(user_id, "OrgAdmin")


def make_funder_admin_headers(org_id: str, staff_label: str = None) -> dict:
    """For FunderAdmin (entity-backed by Organization). Pass the funder org's
    real id; segregation of duties compares the full X-User-ID, so distinct
    staff members of one funder must use distinct staff labels."""
    user_id = f"{org_id}#{staff_label}" if staff_label else org_id
    return build_user_headers(user_id, "FunderAdmin")

"""Pre-built role headers for every role the system recognises.

``Surety`` is the only entity-backed role: its ``X-User-ID`` must be the ``id``
of the acting ``Surety``, so ownership-gated calls must use
``make_surety_headers(surety["id"])`` rather than the shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator identifiers — the canonical form for these roles.
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "estimator_headers": build_user_headers("test-estimator-1", "Estimator"),
    "contracting_officer_headers": build_user_headers(
        "test-contracting-officer-1", "ContractingOfficer"
    ),
    "project_manager_headers": build_user_headers("test-project-manager-1", "ProjectManager"),
    "engineer_headers": build_user_headers("test-engineer-1", "Engineer"),
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
    # entity_backed:Surety — fallback only for calls that are not ownership-gated.
    "surety_headers": build_user_headers("test-surety-1", "Surety"),
}


def make_surety_headers(surety_id: str) -> dict:
    """Headers for a Surety whose ``X-User-ID`` is the acting Surety's own id.

    Bond issuance is ownership-gated, so callers must pass the real
    ``Surety.id`` returned by ``POST /construction/sureties``.
    """
    return build_user_headers(surety_id, "Surety")

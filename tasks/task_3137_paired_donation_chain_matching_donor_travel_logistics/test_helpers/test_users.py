"""Pre-built role headers for every role in the PRD (§2.1).

RegistryAdmin, MatchOperator and LogisticsCoordinator use opaque user ids —
the shared constants below are canonical for them. CenterCoordinator is
entity-backed: its X-User-ID must equal the id of the acting
TransplantCenter, so ownership-gated calls MUST use
make_center_coordinator_headers(center_id) rather than the shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical shared constants.
    "registry_admin_headers": build_user_headers("test-admin-1", "RegistryAdmin"),
    "match_operator_headers": build_user_headers("test-matchop-1", "MatchOperator"),
    "logistics_headers": build_user_headers("test-logistics-1", "LogisticsCoordinator"),
    # CenterCoordinator is entity-backed: this fallback is safe ONLY for
    # calls that do not exercise center ownership (e.g. 400/404 surfaces).
    "center_coordinator_headers": build_user_headers(
        "test-coordinator-1", "CenterCoordinator"
    ),
}


def make_registry_admin_headers(user_id: str) -> dict:
    """RegistryAdmin with a distinct opaque id (e.g. for segregation-of-duties
    scenarios needing two different admin users)."""
    return build_user_headers(user_id, "RegistryAdmin")


def make_center_coordinator_headers(center_id: str) -> dict:
    """CenterCoordinator headers for the coordinator of the given
    TransplantCenter. Pass the center's own id whenever the call is
    ownership-gated (crossmatch review, center-accept, nephrectomy, ...)."""
    return build_user_headers(center_id, "CenterCoordinator")

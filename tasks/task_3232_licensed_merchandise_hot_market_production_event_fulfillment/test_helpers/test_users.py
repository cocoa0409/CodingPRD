"""Pre-built role headers for every role in the PRD's role matrix (§2.1).

Every role other than `LicensingOps` is an opaque identity: `X-User-ID` is an
operator identifier the server never compares to any persisted entity's id.
`LicensingOps` is entity-backed on `Licensor` - its `X-User-ID` is the id of
the acting licensor, so ownership-gated calls must use
`make_licensing_ops_headers(licensor["id"])`.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "design_ops_headers": build_user_headers("test-design-1", "DesignOps"),
    "production_planner_headers": build_user_headers("test-planner-1", "ProductionPlanner"),
    "print_operator_headers": build_user_headers("test-print-1", "PrintOperator"),
    "fulfillment_coordinator_headers": build_user_headers("test-fulfil-1", "FulfillmentCoordinator"),
    "enforcement_agent_headers": build_user_headers("test-enforce-1", "EnforcementAgent"),
    "audit_only_headers": build_user_headers("test-audit-1", "AuditOnly"),
    # entity_backed role: shared constant is a non-ownership fallback only.
    "licensing_ops_headers": build_user_headers("test-licensing-1", "LicensingOps"),
}


def make_licensing_ops_headers(licensor_id: str) -> dict:
    """For LicensingOps (entity_backed:Licensor).

    Pass the actual Licensor.id as `user_id` on every ownership-gated call:
    licensor decisions and minimum-guarantee settlements compare the target
    licensor's id to X-User-ID.
    """
    return build_user_headers(licensor_id, "LicensingOps")


def make_headers_for_unknown_role() -> dict:
    """A well-formed header set carrying a role the matrix does not recognise."""
    return {"X-User-ID": "test-unknown-1", "X-User-Role": "no_such_role"}


def make_headers_without_role() -> dict:
    """An X-User-ID with no X-User-Role, for the authentication check."""
    return {"X-User-ID": "test-anon-1"}
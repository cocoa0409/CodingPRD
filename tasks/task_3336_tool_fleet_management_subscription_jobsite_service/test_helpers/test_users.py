"""Pre-built role headers for every role in the PRD §2.1.

ContractorManager and JobsiteSupervisor are entity_backed roles: X-User-ID must
be the owning ContractorAccount's id. Use make_contractor_manager_headers /
make_jobsite_supervisor_headers with the actual account id for any
ownership-gated call. Opaque roles use shared constants.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are canonical.
    "fleet_admin_headers": build_user_headers("admin-1", "FleetAdmin"),
    "service_coordinator_headers": build_user_headers("svc-1", "ServiceCoordinator"),
    "claims_adjuster_headers": build_user_headers("adj-1", "ClaimsAdjuster"),
    "field_engineer_headers": build_user_headers("eng-1", "FieldEngineer"),
    # Entity-backed roles — fallback only for non-ownership tests.
    "contractor_manager_headers": build_user_headers("test-cm-1", "ContractorManager"),
    "jobsite_supervisor_headers": build_user_headers("test-js-1", "JobsiteSupervisor"),
}


def make_contractor_manager_headers(account_id: str) -> dict:
    """ContractorManager acting for the given ContractorAccount."""
    return build_user_headers(account_id, "ContractorManager")


def make_jobsite_supervisor_headers(account_id: str) -> dict:
    """JobsiteSupervisor supervising the given ContractorAccount's jobsites."""
    return build_user_headers(account_id, "JobsiteSupervisor")


def make_fleet_admin_headers(user_id: str) -> dict:
    """Opaque FleetAdmin identity (needed where verified_by is compared)."""
    return build_user_headers(user_id, "FleetAdmin")


def make_claims_adjuster_headers(user_id: str) -> dict:
    """Opaque ClaimsAdjuster identity (needed for segregation-of-duties)."""
    return build_user_headers(user_id, "ClaimsAdjuster")


def make_field_engineer_headers(user_id: str) -> dict:
    """Opaque FieldEngineer identity (recorded as approved_by_engineer_id)."""
    return build_user_headers(user_id, "FieldEngineer")

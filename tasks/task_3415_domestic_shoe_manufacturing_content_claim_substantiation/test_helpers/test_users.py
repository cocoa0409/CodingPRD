"""Pre-built role headers for every role in the PRD.

Shared constants are for opaque roles and for tests that never exercise an
ownership/identity check. FactoryManager is entity-backed (X-User-ID must be
the managed Factory.id), so ownership-gated calls MUST use
make_factory_manager_headers(factory["id"]). Evidence segregation tests use
per-person user ids (e.g. "sm-1", "co-1") via the make_*_headers builders.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin": build_user_headers("test-admin-1", "PlatformAdmin"),
    "sourcing": build_user_headers("test-sourcing-1", "SourcingManager"),
    "planner": build_user_headers("test-planner-1", "ProductionPlanner"),
    "compliance": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    "training": build_user_headers("test-training-1", "TrainingCoordinator"),
    # FactoryManager shared constant: safe only for calls that are NOT
    # ownership-gated (its X-User-ID equals no real factory id).
    "factory_manager": build_user_headers("test-factory-manager-1", "FactoryManager"),
    "customer": build_user_headers("cust-1", "CustomProgramCustomer"),
}


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_sourcing_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SourcingManager")


def make_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProductionPlanner")


def make_compliance_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_training_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TrainingCoordinator")


def make_factory_manager_headers(user_id: str) -> dict:
    """FactoryManager is entity-backed: pass the managed Factory.id whenever
    the call is ownership-gated (run hold/resume)."""
    return build_user_headers(user_id, "FactoryManager")


def make_customer_headers(user_id: str) -> dict:
    """CustomProgramCustomer: buyer_ref on orders must equal X-User-ID."""
    return build_user_headers(user_id, "CustomProgramCustomer")

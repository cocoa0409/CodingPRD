"""Pre-built role headers for every role in the PRD (§2.1).

All roles are opaque: ``X-User-ID`` is an operator identifier never compared
to any entity id, so shared per-role constants are canonical.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "project_developer_headers": build_user_headers("test-developer-1", "ProjectDeveloper"),
    "performance_engineer_headers": build_user_headers("test-perf-eng-1", "PerformanceEngineer"),
    "service_manager_headers": build_user_headers("test-svc-mgr-1", "ServiceManager"),
    "service_engineer_headers": build_user_headers("test-svc-eng-1", "ServiceEngineer"),
    "warranty_admin_headers": build_user_headers("test-warranty-1", "WarrantyAdmin"),
    "safety_authority_headers": build_user_headers("test-safety-1", "SafetyAuthority"),
    "market_operator_headers": build_user_headers("test-market-1", "MarketOperator"),
}


def make_platform_admin_headers(user_id):
    return build_user_headers(user_id, "PlatformAdmin")


def make_project_developer_headers(user_id):
    return build_user_headers(user_id, "ProjectDeveloper")


def make_performance_engineer_headers(user_id):
    return build_user_headers(user_id, "PerformanceEngineer")


def make_service_manager_headers(user_id):
    return build_user_headers(user_id, "ServiceManager")


def make_service_engineer_headers(user_id):
    return build_user_headers(user_id, "ServiceEngineer")


def make_warranty_admin_headers(user_id):
    return build_user_headers(user_id, "WarrantyAdmin")


def make_safety_authority_headers(user_id):
    return build_user_headers(user_id, "SafetyAuthority")


def make_market_operator_headers(user_id):
    return build_user_headers(user_id, "MarketOperator")

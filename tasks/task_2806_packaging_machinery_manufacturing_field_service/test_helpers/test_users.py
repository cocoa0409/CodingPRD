"""Pre-built role headers for the six roles of PRD §2.1."""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Shared constants. The five operator roles are peer roles whose X-User-ID is an
# opaque operator identifier that is never compared to any stored row (PRD §2.1),
# so the shared constant is the canonical form for them. The CustomerContact entry
# is a fallback for tests that do not exercise ownership (e.g. cross-customer 403s).
TEST_USERS: Dict[str, Dict[str, str]] = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "application_engineer_headers": build_user_headers(
        "test-application-engineer-1", "ApplicationEngineer"
    ),
    "production_planner_headers": build_user_headers(
        "test-production-planner-1", "ProductionPlanner"
    ),
    "quality_inspector_headers": build_user_headers("test-quality-inspector-1", "QualityInspector"),
    "service_manager_headers": build_user_headers("test-service-manager-1", "ServiceManager"),
    "customer_contact_headers": build_user_headers("test-customer-contact-1", "CustomerContact"),
}


def make_customer_contact_headers(customer_id: str) -> Dict[str, str]:
    """Headers for a CustomerContact acting as a specific customer.

    When X-User-Role is CustomerContact, X-User-ID is the id of the acting
    Customer row (PRD §2.1), so ownership-gated calls MUST pass the real
    Customer.id here rather than the shared constant.
    """
    return build_user_headers(customer_id, "CustomerContact")


def make_platform_admin_headers(user_id: str = "test-platform-admin-1") -> Dict[str, str]:
    return build_user_headers(user_id, "PlatformAdmin")


def make_application_engineer_headers(
    user_id: str = "test-application-engineer-1",
) -> Dict[str, str]:
    return build_user_headers(user_id, "ApplicationEngineer")


def make_production_planner_headers(user_id: str = "test-production-planner-1") -> Dict[str, str]:
    return build_user_headers(user_id, "ProductionPlanner")


def make_quality_inspector_headers(user_id: str = "test-quality-inspector-1") -> Dict[str, str]:
    return build_user_headers(user_id, "QualityInspector")


def make_service_manager_headers(user_id: str = "test-service-manager-1") -> Dict[str, str]:
    return build_user_headers(user_id, "ServiceManager")

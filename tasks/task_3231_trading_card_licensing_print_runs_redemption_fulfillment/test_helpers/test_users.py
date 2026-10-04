"""Pre-built role headers for every role in the PRD (§2.1)."""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership. Ten of the eleven roles present an opaque operator identifier.
TEST_USERS = {
    "licensing_manager_headers": build_user_headers("test-licensing-manager-1", "LicensingManager"),
    "product_manager_headers": build_user_headers("test-product-manager-1", "ProductManager"),
    "production_planner_headers": build_user_headers("test-production-planner-1", "ProductionPlanner"),
    "signing_coordinator_headers": build_user_headers("test-signing-coordinator-1", "SigningCoordinator"),
    "authentication_officer_headers": build_user_headers("test-authentication-officer-1", "AuthenticationOfficer"),
    "redemption_analyst_headers": build_user_headers("test-redemption-analyst-1", "RedemptionFulfilmentAnalyst"),
    "distribution_manager_headers": build_user_headers("test-distribution-manager-1", "DistributionManager"),
    "quality_analyst_headers": build_user_headers("test-quality-analyst-1", "QualityAnalyst"),
    "collector_support_headers": build_user_headers("test-collector-support-1", "CollectorSupportSpecialist"),
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
}


def make_licensor_approver_headers(license_id: str) -> dict:
    """For LicensorApprover (entity-backed:License).

    X-User-ID must be the `id` of the acting License, because the artwork
    approval's `approver_id` is ownership-checked against it. Always pass the
    actual License.id.
    """
    return build_user_headers(license_id, "LicensorApprover")


def make_unknown_role_headers(user_id: str, role: str) -> dict:
    """Headers for a role the platform does not recognise (PRD §2.1)."""
    return build_user_headers(user_id, role)
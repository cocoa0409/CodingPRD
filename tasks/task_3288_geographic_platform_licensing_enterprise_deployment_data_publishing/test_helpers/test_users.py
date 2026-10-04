"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership. entity_backed roles (NamedUser, ComplianceOfficer) should prefer
# the per-instance builders below whenever an ownership/segregation check is
# under test.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "license_admin_headers": build_user_headers("test-license-admin-1", "LicenseAdmin"),
    "deployment_admin_headers": build_user_headers("test-deployment-admin-1", "DeploymentAdmin"),
    "billing_admin_headers": build_user_headers("test-billing-admin-1", "BillingAdmin"),
    "compliance_officer_headers": build_user_headers("test-compliance-officer-1", "ComplianceOfficer"),
    "content_moderator_headers": build_user_headers("test-content-moderator-1", "ContentModerator"),
    "named_user_headers": build_user_headers("test-named-user-1", "NamedUser"),
}


def make_named_user_headers(user_id: str) -> dict:
    """Headers for the entity-backed NamedUser role. Pass the actual
    NamedUser.id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "NamedUser")


def make_compliance_officer_headers(user_id: str) -> dict:
    """Headers for the entity-backed ComplianceOfficer role. X-User-ID is the
    acting NamedUser's id so segregation-of-duties comparisons can run."""
    return build_user_headers(user_id, "ComplianceOfficer")

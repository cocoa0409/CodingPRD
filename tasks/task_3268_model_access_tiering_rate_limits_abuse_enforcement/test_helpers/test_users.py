"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not
# exercise ownership. For OrganizationAdmin (entity_backed:Organization)
# the shared constant is a fallback for non-ownership tests only; any
# ownership-gated call MUST use make_organization_admin_headers(org_id).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "billing_contact_headers": build_user_headers("test-billing-contact-1", "BillingContact"),
    "trust_analyst_headers": build_user_headers("test-trust-analyst-1", "TrustAnalyst"),
    "trust_lead_headers": build_user_headers("test-trust-lead-1", "TrustLead"),
    # Fallback only — do NOT use for ownership-gated calls.
    "organization_admin_headers": build_user_headers("test-org-admin-1", "OrganizationAdmin"),
}


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_billing_contact_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BillingContact")


def make_trust_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TrustAnalyst")


def make_trust_lead_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TrustLead")


def make_organization_admin_headers(user_id: str) -> dict:
    """For OrganizationAdmin (entity_backed:Organization). Pass the actual
    Organization.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "OrganizationAdmin")

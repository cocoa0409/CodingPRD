"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for Policyholder calls whose
# success does not depend on owning the subject resource.
TEST_USERS = {
    "policyholder_headers": build_user_headers("test-policyholder-1", "Policyholder"),
    "agent_headers": build_user_headers("test-agent-1", "Agent"),
    "partner_platform_headers": build_user_headers("test-partner-1", "PartnerPlatform"),
    "underwriter_headers": build_user_headers("test-underwriter-1", "Underwriter"),
    "claims_adjuster_headers": build_user_headers("test-adjuster-1", "ClaimsAdjuster"),
    "finance_officer_headers": build_user_headers("test-finance-1", "FinanceOfficer"),
    "compliance_officer_headers": build_user_headers(
        "test-compliance-1", "ComplianceOfficer"
    ),
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
}


# Per-instance builders — mandatory for entity-backed roles (identity is the
# BusinessAccount id); also handy for opaque roles when a specific operator id
# matters (segregation of duties, review ownership).
def make_policyholder_headers(user_id: str) -> dict:
    """Policyholder is entity-backed: user_id MUST be the BusinessAccount.id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Policyholder")


def make_agent_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Agent")


def make_partner_platform_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PartnerPlatform")


def make_underwriter_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Underwriter")


def make_claims_adjuster_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ClaimsAdjuster")


def make_finance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FinanceOfficer")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")

"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership. Entity-backed roles (DealerPrincipal, Customer) MUST use the
# per-instance builders below whenever the call is ownership-gated.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "regional_manager_headers": build_user_headers("test-rm-1", "RegionalManager"),
    "field_consultant_headers": build_user_headers("test-fc-1", "FieldConsultant"),
    "compliance_auditor_headers": build_user_headers("test-ca-1", "ComplianceAuditor"),
    "survey_vendor_headers": build_user_headers("test-sv-1", "SurveyVendor"),
    # Fallbacks only — never use for ownership-gated calls.
    "dealer_principal_headers": build_user_headers("test-dp-1", "DealerPrincipal"),
    "customer_headers": build_user_headers("test-cust-1", "Customer"),
}


def make_dealer_principal_headers(dealer_id: str) -> dict:
    """DealerPrincipal is entity-backed by Dealer. Pass the real Dealer.id
    whenever the call is ownership-gated (appeals, action plans, own reads)."""
    return build_user_headers(dealer_id, "DealerPrincipal")


def make_customer_headers(customer_id: str) -> dict:
    """Customer is entity-backed by Customer. Pass the real Customer.id
    whenever the call is ownership-gated (respond, opt-out, own invitation)."""
    return build_user_headers(customer_id, "Customer")

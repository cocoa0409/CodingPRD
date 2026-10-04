"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership. Dealer and Customer are entity-backed; for ownership-gated calls use
# the make_* builders below with the real entity id.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "channel_manager_headers": build_user_headers("test-channel-manager-1", "ChannelManager"),
    "funding_analyst_headers": build_user_headers("test-funding-analyst-1", "FundingAnalyst"),
    "compliance_officer_headers": build_user_headers("test-compliance-officer-1", "ComplianceOfficer"),
    "monitoring_operator_headers": build_user_headers("test-monitoring-operator-1", "MonitoringOperator"),
    "service_coordinator_headers": build_user_headers("test-service-coordinator-1", "ServiceCoordinator"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "dealer_headers": build_user_headers("test-dealer-1", "Dealer"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_dealer_headers(user_id: str) -> dict:
    """For Dealer (entity_backed:Dealer). Pass the actual Dealer.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Dealer")


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Customer")


def make_operator_headers(user_id: str, role: str = "ComplianceOfficer") -> dict:
    """Opaque-role header carrying a specific operator id — used where a workflow
    records an operator identifier (e.g. a rescission requestor or approver)."""
    return build_user_headers(user_id, role)
"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not
# exercise ownership. entity_backed roles MUST use the builders below
# whenever the call is ownership-gated.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "compliance_analyst_headers": build_user_headers("test-compliance-analyst-1", "ComplianceAnalyst"),
    "data_ops_headers": build_user_headers("test-data-ops-1", "DataOps"),
    # Fallbacks for non-ownership tests only:
    "broker_admin_headers": build_user_headers("test-broker-admin-1", "BrokerAdmin"),
    "carrier_admin_headers": build_user_headers("test-carrier-admin-1", "CarrierAdmin"),
}


def make_broker_admin_headers(broker_org_id: str) -> dict:
    """For BrokerAdmin (entity_backed:BrokerOrg). Pass the actual BrokerOrg.id
    as user_id whenever the call is ownership-gated."""
    return build_user_headers(broker_org_id, "BrokerAdmin")


def make_carrier_admin_headers(carrier_org_id: str) -> dict:
    """For CarrierAdmin (entity_backed:CarrierOrg). Pass the actual CarrierOrg.id
    as user_id whenever the call is ownership-gated."""
    return build_user_headers(carrier_org_id, "CarrierAdmin")

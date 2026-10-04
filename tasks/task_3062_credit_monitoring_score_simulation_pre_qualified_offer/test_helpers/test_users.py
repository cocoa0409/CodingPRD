"""Pre-built role headers for every role in the PRD (§2.1).

`Consumer` is the sole entity-backed role: when a call is ownership-gated,
X-User-ID must be the acting Consumer's own id — use make_consumer_headers().
Every other role carries an opaque operator identifier.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "consumer_headers": build_user_headers("test-consumer-1", "Consumer"),
    "referee_headers": build_user_headers("test-referee-1", "Referee"),
    "bureau_connector_headers": build_user_headers("test-bureau-1", "BureauConnector"),
    "lender_ops_headers": build_user_headers("test-lenderops-1", "LenderOps"),
    "compliance_officer_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "data_protection_officer_headers": build_user_headers("test-dpo-1", "DataProtectionOfficer"),
    # A caller carrying no role is used only to exercise the missing-header rule.
    "anonymous_headers": {},
}


def make_consumer_headers(user_id: str) -> dict:
    """For Consumer (entity_backed:Consumer). Pass the actual Consumer.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Consumer")
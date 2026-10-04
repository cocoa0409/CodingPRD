"""Pre-built role headers for every role the platform declares."""
from prd_bench_local_runner.testing import (
    build_user_headers,
    build_user_headers as _buh,
)

# Shared constants — safe for opaque roles, and for tests that exercise no
# ownership comparison.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "channel_manager_headers": build_user_headers("test-channel-manager-1", "ChannelManager"),
    "underwriter_headers": build_user_headers("test-underwriter-1", "Underwriter"),
    "compliance_officer_headers": build_user_headers("test-compliance-officer-1", "ComplianceOfficer"),
    "qc_analyst_headers": build_user_headers("test-qc-analyst-1", "QualityControlAnalyst"),
    "any_headers": build_user_headers("test-any-reader-1", "Any"),
    # BrokerUser is entity-backed: this shared constant is a fallback for
    # non-ownership calls only.  Ownership-gated calls MUST use the builder.
    "broker_user_headers": build_user_headers("test-broker-user-fallback", "BrokerUser"),
}

# Named operator identities used where a rule records X-User-ID verbatim.
NAMED_UNDERWRITER_ID = "uw-dana"
NAMED_QC_ANALYST_ID = "qc-priya"


def make_broker_headers(broker_id: str) -> dict:
    """Headers for a BrokerUser acting as the brokerage identified by broker_id.

    Every ownership-gated broker-scoped call must pass the real Broker.id here;
    the shared constant in TEST_USERS never equals any persisted entity id.
    """
    return _buh(broker_id, "BrokerUser")


def make_underwriter_headers(user_id: str = NAMED_UNDERWRITER_ID) -> dict:
    return _buh(user_id, "Underwriter")


def make_qc_analyst_headers(user_id: str = NAMED_QC_ANALYST_ID) -> dict:
    return _buh(user_id, "QualityControlAnalyst")


def make_channel_manager_headers(user_id: str = "cm-operator-1") -> dict:
    return _buh(user_id, "ChannelManager")


def make_compliance_officer_headers(user_id: str = "co-operator-1") -> dict:
    return _buh(user_id, "ComplianceOfficer")


def make_platform_admin_headers(user_id: str = "pa-operator-1") -> dict:
    return _buh(user_id, "PlatformAdmin")


def anonymous_headers() -> dict:
    """Headers with no user context at all — used to assert priority-1 refusal."""
    return {}


def role_only_headers(role: str) -> dict:
    """A role header with no X-User-ID — used to assert missing-context refusal."""
    return {"X-User-Role": role}
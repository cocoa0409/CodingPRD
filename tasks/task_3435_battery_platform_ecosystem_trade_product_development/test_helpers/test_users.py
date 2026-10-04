"""Pre-built role headers for every role in the PRD (§2.1).

Three roles are entity-backed: for them X-User-ID IS the backing entity's id.
Fixtures and ownership-gated tests MUST use the make_*_headers builders with
the real entity id — never the shared constant — or every ownership check
rejects the call.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are canonical.
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "product_engineer_headers": build_user_headers("pe-ana", "ProductEngineer"),
    "compliance_engineer_headers": build_user_headers("ce-bob", "ComplianceEngineer"),
    "field_researcher_headers": build_user_headers("fr-kim", "FieldResearcher"),
    # Entity-backed roles: shared constants are safe only for tests whose
    # success does not depend on ownership of the subject resource.
    "service_agent_headers": build_user_headers("sc-fallback", "ServiceAgent"),
    "account_manager_headers": build_user_headers("ac-fallback", "AccountManager"),
    "channel_manager_headers": build_user_headers("cp-fallback", "ChannelManager"),
}


def make_service_agent_headers(service_center_id: str) -> dict:
    """ServiceAgent identity is the ServiceCenter id (PRD §2.1)."""
    return build_user_headers(service_center_id, "ServiceAgent")


def make_account_manager_headers(asset_account_id: str) -> dict:
    """AccountManager identity is the AssetAccount id (PRD §2.1)."""
    return build_user_headers(asset_account_id, "AccountManager")


def make_channel_manager_headers(channel_partner_id: str) -> dict:
    """ChannelManager identity is the ChannelPartner id (PRD §2.1)."""
    return build_user_headers(channel_partner_id, "ChannelManager")

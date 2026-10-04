"""Pre-built role headers for every role in the PRD.

TEST_USERS holds one shared header dict per role — safe for opaque roles
and for tests that never exercise ownership. DistributorContact is
entity-backed (X-User-ID must equal the Distributor.id), so any
ownership-gated call MUST use make_distributor_contact_headers(dist_id)
with the real entity id, never the shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical default user ids per role.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("platform-admin-1", "PlatformAdmin"),
    "brand_manager_headers": build_user_headers("bm-1", "BrandManager"),
    "trade_secret_officer_headers": build_user_headers("tso-1", "TradeSecretOfficer"),
    "compliance_auditor_headers": build_user_headers("ca-1", "ComplianceAuditor"),
    "channel_manager_headers": build_user_headers("cm-1", "ChannelManager"),
    "pricing_analyst_headers": build_user_headers("pa-1", "PricingAnalyst"),
    "marketing_manager_headers": build_user_headers("mm-1", "MarketingManager"),
    "regulatory_affairs_headers": build_user_headers("ra-1", "RegulatoryAffairs"),
    "supply_planner_headers": build_user_headers("sp-1", "SupplyPlanner"),
    # entity_backed:Distributor — fallback for non-ownership tests ONLY.
    "distributor_contact_headers": build_user_headers("dist-shared-1", "DistributorContact"),
    "consumer_headers": build_user_headers("consumer-1", "Consumer"),
}


def make_platform_admin_headers(user_id: str) -> dict:
    """PlatformAdmin headers for a specific operator id."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_brand_manager_headers(user_id: str) -> dict:
    """BrandManager headers for a specific user id."""
    return build_user_headers(user_id, "BrandManager")


def make_trade_secret_officer_headers(user_id: str) -> dict:
    """TradeSecretOfficer headers; the id is recorded as sponsoring_officer_id / granted_by_user_id."""
    return build_user_headers(user_id, "TradeSecretOfficer")


def make_compliance_auditor_headers(user_id: str) -> dict:
    """ComplianceAuditor headers; for-cause revocation is segregated from granted_by_user_id."""
    return build_user_headers(user_id, "ComplianceAuditor")


def make_channel_manager_headers(user_id: str) -> dict:
    """ChannelManager headers for a specific user id."""
    return build_user_headers(user_id, "ChannelManager")


def make_pricing_analyst_headers(user_id: str) -> dict:
    """PricingAnalyst headers; the id is recorded as promotion created_by_user_id."""
    return build_user_headers(user_id, "PricingAnalyst")


def make_marketing_manager_headers(user_id: str) -> dict:
    """MarketingManager headers; the approve caller is recorded as approved_by_user_id."""
    return build_user_headers(user_id, "MarketingManager")


def make_regulatory_affairs_headers(user_id: str) -> dict:
    """RegulatoryAffairs headers for a specific user id."""
    return build_user_headers(user_id, "RegulatoryAffairs")


def make_supply_planner_headers(user_id: str) -> dict:
    """SupplyPlanner headers for a specific user id."""
    return build_user_headers(user_id, "SupplyPlanner")


def make_distributor_contact_headers(user_id: str) -> dict:
    """DistributorContact headers (entity_backed:Distributor).

    Pass the actual Distributor.id whenever the call is ownership-gated
    (sell-through report creation compares X-User-ID to the path
    distributor id).
    """
    return build_user_headers(user_id, "DistributorContact")


def make_consumer_headers(user_id: str) -> dict:
    """Consumer headers; a use case's submitter_ref must equal this id."""
    return build_user_headers(user_id, "Consumer")

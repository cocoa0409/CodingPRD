"""Pre-built role headers for every role in the PRD.

Seven roles are opaque identities (X-User-ID is not compared against any
entity id). ManufacturerRep is entity-backed: X-User-ID MUST equal the id of
the ContractManufacturer the rep acts for, so ownership-gated calls MUST be
made with make_manufacturer_rep_headers(cm["id"]) — the shared
manufacturer_rep_headers constant is a fallback for non-ownership contexts
only (e.g. 400/404 probes).

The per-role make_*_headers builders also serve tests that need a specific
user id with a role, e.g. segregation-of-duties: approving a discontinuation
with make_retail_planner_headers("pm-nadia") when "pm-nadia" proposed it.
"""
from prd_bench_local_runner.testing import build_user_headers

__all__ = [
    "PLATFORM_ADMIN_USER_ID",
    "TREND_SCOUT_USER_ID",
    "PRODUCT_MANAGER_USER_ID",
    "SOURCING_LEAD_USER_ID",
    "COMPLIANCE_OFFICER_USER_ID",
    "RETAIL_PLANNER_USER_ID",
    "MARKETING_LEAD_USER_ID",
    "TEST_USERS",
    "make_platform_admin_headers",
    "make_trend_scout_headers",
    "make_product_manager_headers",
    "make_sourcing_lead_headers",
    "make_compliance_officer_headers",
    "make_retail_planner_headers",
    "make_marketing_lead_headers",
    "make_manufacturer_rep_headers",
]

#: Canonical opaque user ids used throughout the fixture chains.
PLATFORM_ADMIN_USER_ID = "pa-admin"
TREND_SCOUT_USER_ID = "ts-ivy"
PRODUCT_MANAGER_USER_ID = "pm-nadia"
SOURCING_LEAD_USER_ID = "sl-omar"
COMPLIANCE_OFFICER_USER_ID = "co-lena"
RETAIL_PLANNER_USER_ID = "rp-owen"
MARKETING_LEAD_USER_ID = "ml-kai"

# Shared constants — safe for opaque roles, and for ManufacturerRep only in
# tests that do not exercise CM ownership.
TEST_USERS = {
    "platform_admin_headers": build_user_headers(PLATFORM_ADMIN_USER_ID, "PlatformAdmin"),
    "trend_scout_headers": build_user_headers(TREND_SCOUT_USER_ID, "TrendScout"),
    "product_manager_headers": build_user_headers(PRODUCT_MANAGER_USER_ID, "ProductManager"),
    "sourcing_lead_headers": build_user_headers(SOURCING_LEAD_USER_ID, "SourcingLead"),
    "compliance_officer_headers": build_user_headers(COMPLIANCE_OFFICER_USER_ID, "ComplianceOfficer"),
    "retail_planner_headers": build_user_headers(RETAIL_PLANNER_USER_ID, "RetailPlanner"),
    "marketing_lead_headers": build_user_headers(MARKETING_LEAD_USER_ID, "MarketingLead"),
    # entity_backed role: fallback for non-ownership tests only; never use
    # when submitting/withdrawing a quote or submitting a formula sample,
    # because this id equals no real ContractManufacturer id.
    "manufacturer_rep_headers": build_user_headers("mr-standalone", "ManufacturerRep"),
}


def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_trend_scout_headers(user_id: str = TREND_SCOUT_USER_ID) -> dict:
    return build_user_headers(user_id, "TrendScout")


def make_product_manager_headers(user_id: str = PRODUCT_MANAGER_USER_ID) -> dict:
    return build_user_headers(user_id, "ProductManager")


def make_sourcing_lead_headers(user_id: str = SOURCING_LEAD_USER_ID) -> dict:
    return build_user_headers(user_id, "SourcingLead")


def make_compliance_officer_headers(user_id: str = COMPLIANCE_OFFICER_USER_ID) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_retail_planner_headers(user_id: str = RETAIL_PLANNER_USER_ID) -> dict:
    return build_user_headers(user_id, "RetailPlanner")


def make_marketing_lead_headers(user_id: str = MARKETING_LEAD_USER_ID) -> dict:
    return build_user_headers(user_id, "MarketingLead")


def make_manufacturer_rep_headers(contract_manufacturer_id: str) -> dict:
    """For ManufacturerRep (entity_backed: ContractManufacturer). Pass the
    actual ContractManufacturer.id whenever the call is ownership-gated:
    quote submission/withdrawal and formula-sample submission."""
    return build_user_headers(contract_manufacturer_id, "ManufacturerRep")

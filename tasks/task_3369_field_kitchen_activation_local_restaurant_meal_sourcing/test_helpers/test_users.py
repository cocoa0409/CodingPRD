"""Pre-built role headers for every role named in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants: safe for the eight opaque operator roles, and for
# entity-backed roles in tests whose outcome does not depend on ownership.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "field_coordinator_headers": build_user_headers("test-field-coord-1", "FieldCoordinator"),
    "food_safety_officer_headers": build_user_headers("test-food-safety-1", "FoodSafetyOfficer"),
    "partnership_lead_headers": build_user_headers("test-partnership-1", "PartnershipLead"),
    "production_planner_headers": build_user_headers("test-planner-1", "ProductionPlanner"),
    "sourcing_officer_headers": build_user_headers("test-sourcing-1", "SourcingOfficer"),
    "logistics_coordinator_headers": build_user_headers("test-logistics-1", "LogisticsCoordinator"),
    "donor_liaison_headers": build_user_headers("test-donor-1", "DonorLiaison"),
    # entity-backed fallbacks — only for calls that are not ownership-gated.
    "kitchen_operator_headers": build_user_headers("test-kitchen-op-1", "KitchenOperator"),
    "site_coordinator_headers": build_user_headers("test-site-coord-1", "SiteCoordinator"),
}


# Per-instance builders — mandatory for the entity-backed roles.
def make_kitchen_operator_headers(partner_kitchen_id: str) -> dict:
    """For KitchenOperator (entity_backed:PartnerKitchen).

    Pass the actual PartnerKitchen.id as user_id whenever the call is
    ownership-gated (driving a production batch or a partner kitchen).
    """
    return build_user_headers(partner_kitchen_id, "KitchenOperator")


def make_site_coordinator_headers(distribution_site_id: str) -> dict:
    """For SiteCoordinator (entity_backed:DistributionSite).

    Pass the actual DistributionSite.id as user_id whenever the call is
    ownership-gated (recording a stop outcome at its own site).
    """
    return build_user_headers(distribution_site_id, "SiteCoordinator")

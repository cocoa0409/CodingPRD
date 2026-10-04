"""Pre-built role headers for every role in the PRD (section 2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants for the opaque roles (X-User-ID is not compared to any
# entity id per PRD section 2.1), plus a fallback for DealerPrincipal used
# only by tests that never exercise ownership.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "region_manager_headers": build_user_headers("test-region-manager-1", "RegionManager"),
    "channel_director_headers": build_user_headers("test-channel-director-1", "ChannelDirector"),
    "color_lab_admin_headers": build_user_headers("test-color-lab-admin-1", "ColorLabAdmin"),
    "equipment_tech_headers": build_user_headers("test-equipment-tech-1", "EquipmentTech"),
    # Fallback only: never use for ownership-gated calls.
    "dealer_principal_headers": build_user_headers("test-dealer-principal-1", "DealerPrincipal"),
}


def make_dealer_principal_headers(dealer_id: str) -> dict:
    """DealerPrincipal is entity-backed: X-User-ID must equal the Dealer.id
    whenever the call is ownership-gated (PRD section 2.1)."""
    return build_user_headers(dealer_id, "DealerPrincipal")

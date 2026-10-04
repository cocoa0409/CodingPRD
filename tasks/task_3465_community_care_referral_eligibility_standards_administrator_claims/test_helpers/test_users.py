"""Pre-built role headers for every role in the PRD.

Identity model (PRD): TPAAdministrator, ProviderRep, and Veteran are
entity-backed — X-User-ID must be the id of the acting ThirdPartyAdministrator,
CommunityProvider, or Veteran. The other five roles are opaque operator
identifiers.

The shared constants in TEST_USERS are safe for opaque roles and for tests
whose outcome does not depend on ownership (400/404/RBAC checks). Any
ownership-gated call MUST use the per-instance builders below with the actual
entity's id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — the canonical form.
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "eligibility_clerk_headers": build_user_headers("test-clerk-1", "EligibilityClerk"),
    "care_coordinator_headers": build_user_headers("test-coordinator-1", "CareCoordinator"),
    "network_manager_headers": build_user_headers("test-netmgr-1", "NetworkManager"),
    "system_pharmacist_headers": build_user_headers("test-pharmacist-1", "SystemPharmacist"),
    # Entity-backed roles — fallback for NON-ownership tests only (e.g. a role
    # check that must fail before ownership is examined). Never use these when
    # the call is ownership-gated; use the make_* builders instead.
    "tpa_admin_headers": build_user_headers("test-tpa-admin-1", "TPAAdministrator"),
    "provider_rep_headers": build_user_headers("test-provider-rep-1", "ProviderRep"),
    "veteran_headers": build_user_headers("test-veteran-1", "Veteran"),
}


def make_tpa_admin_headers(tpa_id: str) -> dict:
    """TPAAdministrator is entity-backed: pass the acting TPA's id."""
    return build_user_headers(tpa_id, "TPAAdministrator")


def make_provider_rep_headers(provider_id: str) -> dict:
    """ProviderRep is entity-backed: pass the acting CommunityProvider's id."""
    return build_user_headers(provider_id, "ProviderRep")


def make_veteran_headers(veteran_id: str) -> dict:
    """Veteran is entity-backed: pass the acting Veteran's id."""
    return build_user_headers(veteran_id, "Veteran")

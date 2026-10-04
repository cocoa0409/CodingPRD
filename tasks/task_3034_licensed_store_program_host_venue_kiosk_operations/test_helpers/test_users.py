"""Pre-built role headers for every role in the PRD.

PRD §2.1 splits identity in two. For BrandProgramAdmin and BrandInspector the
``X-User-ID`` is an opaque operator identifier that is never compared against
an entity id (except where a segregation-of-duties rule demands two distinct
inspector identities). For the entity-backed roles — LicenseeManager,
HostVenueManager, DistributorAgent, LoyaltyMember — the ``X-User-ID`` IS the
id of the acting entity, so their headers can only be built once the entity
row exists; use the per-instance builders below.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership.
TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "BrandProgramAdmin"),
    "inspector_p_headers": build_user_headers("insp-P", "BrandInspector"),
    "inspector_q_headers": build_user_headers("insp-Q", "BrandInspector"),
    "inspector_a_headers": build_user_headers("insp-A", "BrandInspector"),
    "inspector_b_headers": build_user_headers("insp-B", "BrandInspector"),
    "inspector_z_headers": build_user_headers("insp-Z", "BrandInspector"),
}


def make_licensee_manager_headers(licensee_id: str) -> dict:
    """LicenseeManager is entity_backed:Licensee — pass the real Licensee.id."""
    return build_user_headers(licensee_id, "LicenseeManager")


def make_host_venue_manager_headers(venue_id: str) -> dict:
    """HostVenueManager is entity_backed:HostVenue — pass the real HostVenue.id."""
    return build_user_headers(venue_id, "HostVenueManager")


def make_distributor_agent_headers(distributor_id: str) -> dict:
    """DistributorAgent is entity_backed:Distributor — pass the real Distributor.id."""
    return build_user_headers(distributor_id, "DistributorAgent")


def make_loyalty_member_headers(member_id: str) -> dict:
    """LoyaltyMember is entity_backed:LoyaltyMember — pass the real member id."""
    return build_user_headers(member_id, "LoyaltyMember")


def make_inspector_headers(inspector_id: str) -> dict:
    """BrandInspector is opaque; segregation rules compare inspector ids."""
    return build_user_headers(inspector_id, "BrandInspector")

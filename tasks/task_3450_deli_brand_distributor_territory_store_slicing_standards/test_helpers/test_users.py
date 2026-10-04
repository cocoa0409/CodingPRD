"""Pre-built role headers for every role in the PRD (§2.1).

Identity model:
- BrandAdmin and SafetyOfficer are OPAQUE: X-User-ID is never compared to
  any entity id, so the shared constants are canonical.
- DistributorRep is entity-backed by Distributor: X-User-ID must equal the
  owning distributor's id on non-read operations.
- RetailManager is entity-backed by Account: X-User-ID must equal the
  owning account's id.
- PlantScheduler is entity-backed by Plant: X-User-ID must equal the
  plant's id.

Fixtures MUST call the make_*_headers builders with the real entity id
whenever the downstream call is ownership-gated. The shared constants for
entity-backed roles are only safe for tests that never depend on ownership
(400/404 checks, read-only listing, negative RBAC probes).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # opaque roles — canonical form
    "brand_admin_headers": build_user_headers("test-brand-admin-1", "BrandAdmin"),
    "safety_officer_headers": build_user_headers("test-safety-officer-1", "SafetyOfficer"),
    # entity-backed roles — fallback only for non-ownership tests
    "distributor_rep_headers": build_user_headers("test-distributor-rep-1", "DistributorRep"),
    "retail_manager_headers": build_user_headers("test-retail-manager-1", "RetailManager"),
    "plant_scheduler_headers": build_user_headers("test-plant-scheduler-1", "PlantScheduler"),
}


def make_brand_admin_headers(user_id="test-brand-admin-1"):
    """BrandAdmin is opaque; any user_id works."""
    return build_user_headers(user_id, "BrandAdmin")


def make_safety_officer_headers(user_id="test-safety-officer-1"):
    """SafetyOfficer is opaque; any user_id works."""
    return build_user_headers(user_id, "SafetyOfficer")


def make_distributor_rep_headers(distributor_id):
    """DistributorRep is entity_backed:Distributor — pass the real
    Distributor.id whenever the call is ownership-gated (orders, deliveries,
    service visits, promo drafts, certifications, account proposals)."""
    return build_user_headers(distributor_id, "DistributorRep")


def make_retail_manager_headers(account_id):
    """RetailManager is entity_backed:Account — pass the real Account.id
    whenever the call is ownership-gated (delivery confirm/reject, slicers,
    opened-product logs)."""
    return build_user_headers(account_id, "RetailManager")


def make_plant_scheduler_headers(plant_id):
    """PlantScheduler is entity_backed:Plant — pass the real Plant.id
    whenever the call is ownership-gated (production run create/complete)."""
    return build_user_headers(plant_id, "PlantScheduler")

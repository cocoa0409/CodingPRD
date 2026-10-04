"""Pre-built role headers for every role in the PRD (§2.1).

Identity semantics (PRD §2.1):
- FleetManager and ServiceAdvisor are entity-backed: X-User-ID must equal the
  acting Fleet.id / ServiceCenter.id on ownership-checked calls. ALWAYS build
  their headers with make_fleet_manager_headers(fleet["id"]) /
  make_service_advisor_headers(center["id"]) when the call touches a resource
  those roles own — the shared constants below are only for tests that do not
  exercise ownership (bad-payload 400s, missing-resource 404s, RBAC 403s).
- The other five roles are opaque: X-User-ID is recorded but never compared
  to an entity id. The shared constants are canonical for them.

Segregation of duties (PRD §3.2): certification is rejected when the
officer's X-User-ID equals the family's submitted_by_user_id. Fixtures and
tests must therefore submit with one distinct user id (e.g.
SUBMITTER_USER_ID) and certify with another (e.g. CERTIFIER_USER_ID) via
make_certification_engineer_headers / make_regulatory_officer_headers.
"""
from prd_bench_local_runner.testing import build_user_headers

# Distinct opaque operator ids — reused across tests is safe because the
# server never compares them to entity ids; they must differ from each other
# wherever segregation of duties is exercised.
ADMIN_USER_ID = "pa-admin-1"
SUBMITTER_USER_ID = "ce-quinn"       # certification engineer who submits for review
ENGINEER_USER_ID = "ce-quinn"
CERTIFIER_USER_ID = "ro-mara"        # regulatory officer who certifies (≠ submitter)
OFFICER_USER_ID = "ro-mara"
ADJUDICATOR_USER_ID = "wa-ines"
PLANNER_USER_ID = "rp-ose"

TEST_USERS = {
    # opaque roles — canonical shared form
    "admin_headers": build_user_headers(ADMIN_USER_ID, "PlatformAdmin"),
    "engineer_headers": build_user_headers(ENGINEER_USER_ID, "CertificationEngineer"),
    "officer_headers": build_user_headers(OFFICER_USER_ID, "RegulatoryOfficer"),
    "adjudicator_headers": build_user_headers(ADJUDICATOR_USER_ID, "WarrantyAdjudicator"),
    "planner_headers": build_user_headers(PLANNER_USER_ID, "RemanPlanner"),
    # entity-backed roles — fallback for non-ownership tests ONLY; use the
    # per-instance builders below whenever ownership is checked
    "fleet_manager_headers": build_user_headers("fm-orphan-1", "FleetManager"),
    "service_advisor_headers": build_user_headers("sa-orphan-1", "ServiceAdvisor"),
}


def make_platform_admin_headers(user_id: str = ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_certification_engineer_headers(user_id: str = ENGINEER_USER_ID) -> dict:
    return build_user_headers(user_id, "CertificationEngineer")


def make_regulatory_officer_headers(user_id: str = CERTIFIER_USER_ID) -> dict:
    return build_user_headers(user_id, "RegulatoryOfficer")


def make_warranty_adjudicator_headers(user_id: str = ADJUDICATOR_USER_ID) -> dict:
    return build_user_headers(user_id, "WarrantyAdjudicator")


def make_reman_planner_headers(user_id: str = PLANNER_USER_ID) -> dict:
    return build_user_headers(user_id, "RemanPlanner")


def make_fleet_manager_headers(fleet_id: str) -> dict:
    """FleetManager is entity_backed:Fleet — pass the acting fleet's id so
    ownership checks (unit.fleet_id == X-User-ID) can pass."""
    return build_user_headers(fleet_id, "FleetManager")


def make_service_advisor_headers(center_id: str) -> dict:
    """ServiceAdvisor is entity_backed:ServiceCenter — pass the acting
    center's id so ownership checks (service_center_id == X-User-ID) pass."""
    return build_user_headers(center_id, "ServiceAdvisor")

"""Pre-built role headers for every role in the PRD.

Two forms per role:

- TEST_USERS shared constants — for opaque roles these are the canonical form.
  For FleetManager (entity_backed by FleetCustomer) the shared constant is a
  fallback for non-ownership tests ONLY; ownership-gated calls must use
  make_fleet_manager_headers(customer["id"]).

- make_<role>_headers(user_id) builders — required whenever a test needs to
  control the exact X-User-ID: segregation-of-duties tests (inspector/auditor/
  adjudicator must differ from, or deliberately equal, a provenance id) and
  every FleetManager ownership-gated call.
"""
from prd_bench_local_runner.testing import build_user_headers

# Stable opaque operator ids used across fixtures and provenance assertions.
PLATFORM_ADMIN_ID = "pa-1"
PRODUCTION_PLANNER_ID = "pp-1"
QUALITY_INSPECTOR_ID = "qi-1"
COMPLIANCE_OFFICER_ID = "co-1"
CHARGING_COORDINATOR_ID = "cc-1"
SERVICE_DISPATCHER_ID = "sd-1"
SERVICE_TECHNICIAN_ID = "st-1"
SERVICE_TECHNICIAN_ALT_ID = "st-2"
CLAIMS_ADJUSTER_ID = "ca-1"
RELEASE_MANAGER_ID = "rm-1"
TELEMATICS_INGESTION_ID = "ti-1"


TEST_USERS = {
    "platform_admin_headers": build_user_headers(PLATFORM_ADMIN_ID, "PlatformAdmin"),
    "production_planner_headers": build_user_headers(PRODUCTION_PLANNER_ID, "ProductionPlanner"),
    "quality_inspector_headers": build_user_headers(QUALITY_INSPECTOR_ID, "QualityInspector"),
    "compliance_officer_headers": build_user_headers(COMPLIANCE_OFFICER_ID, "ComplianceOfficer"),
    "charging_coordinator_headers": build_user_headers(CHARGING_COORDINATOR_ID, "ChargingCoordinator"),
    # entity_backed:FleetCustomer — fallback ONLY for non-ownership assertions
    # (e.g. 400/404 paths); never for depot/order/visit/claim/visit-cancel
    # success paths, which require X-User-ID == FleetCustomer.id.
    "fleet_manager_headers": build_user_headers("test-fleet-manager-1", "FleetManager"),
    "service_dispatcher_headers": build_user_headers(SERVICE_DISPATCHER_ID, "ServiceDispatcher"),
    "service_technician_headers": build_user_headers(SERVICE_TECHNICIAN_ID, "ServiceTechnician"),
    "service_technician_alt_headers": build_user_headers(SERVICE_TECHNICIAN_ALT_ID, "ServiceTechnician"),
    "claims_adjuster_headers": build_user_headers(CLAIMS_ADJUSTER_ID, "ClaimsAdjuster"),
    "release_manager_headers": build_user_headers(RELEASE_MANAGER_ID, "ReleaseManager"),
    "telematics_ingestion_headers": build_user_headers(TELEMATICS_INGESTION_ID, "TelematicsIngestion"),
}


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_production_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProductionPlanner")


def make_quality_inspector_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QualityInspector")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_charging_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ChargingCoordinator")


def make_fleet_manager_headers(user_id: str) -> dict:
    """FleetManager is entity_backed: pass the owning FleetCustomer.id so
    ownership-gated calls (depot/order/visit/claim) succeed."""
    return build_user_headers(user_id, "FleetManager")


def make_service_dispatcher_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ServiceDispatcher")


def make_service_technician_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ServiceTechnician")


def make_claims_adjuster_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ClaimsAdjuster")


def make_release_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ReleaseManager")


def make_telematics_ingestion_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TelematicsIngestion")

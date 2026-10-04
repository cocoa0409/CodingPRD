"""Pre-built role headers for every role in the PRD (section 2.1).

Identity semantics per the PRD:
- CustomerOps is ENTITY-BACKED by Customer: X-User-ID is the id of the acting
  Customer, and ownership checks compare customer references to X-User-ID.
  The shared "customer_ops_headers" constant below is a FALLBACK for tests
  that do not exercise ownership (e.g. role-denial on a foreign endpoint).
  Any ownership-gated call (accepting an evaluation, responding to a
  turnaround) MUST use make_customer_ops_headers(customer["id"]).
- All other roles are OPAQUE: X-User-ID is not tied to any persisted entity;
  the server may record it (e.g. analyst_user_id) but never compares it to an
  entity id.
- Segregation of duties is enforced at BOTH layers: the QualityAnalyst ROLE
  is denied the certify endpoint outright (403), and a QualityCertifier whose
  X-User-ID equals the certificate's analyst_user_id is rejected (422). The
  shared analyst/certifier constants therefore use DIFFERENT user ids
  ("qa-1" vs "qc-9"); tests that need a same-person collision build headers
  with make_quality_analyst_headers / make_quality_certifier_headers around
  one shared id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "supply_planner_headers": build_user_headers("test-supply-planner-1", "SupplyPlanner"),
    # Entity-backed role — fallback only for non-ownership tests; see module docstring.
    "customer_ops_headers": build_user_headers("test-customer-ops-1", "CustomerOps"),
    "plant_operator_headers": build_user_headers("test-plant-operator-1", "PlantOperator"),
    "pipeline_dispatcher_headers": build_user_headers("test-pipeline-dispatcher-1", "PipelineDispatcher"),
    "telemetry_gateway_headers": build_user_headers("test-telemetry-gateway-1", "TelemetryGateway"),
    # Distinct identities so a default certify never collides with the analyst.
    "quality_analyst_headers": build_user_headers("qa-1", "QualityAnalyst"),
    "quality_certifier_headers": build_user_headers("qc-9", "QualityCertifier"),
    "billing_specialist_headers": build_user_headers("test-billing-specialist-1", "BillingSpecialist"),
}


# --- Per-instance builders -------------------------------------------------

def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_supply_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SupplyPlanner")


def make_customer_ops_headers(user_id: str) -> dict:
    """CustomerOps is entity-backed by Customer: pass the actual Customer.id
    whenever the call is ownership-gated (evaluation accept, turnaround
    respond)."""
    return build_user_headers(user_id, "CustomerOps")


def make_plant_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlantOperator")


def make_pipeline_dispatcher_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PipelineDispatcher")


def make_telemetry_gateway_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TelemetryGateway")


def make_quality_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QualityAnalyst")


def make_quality_certifier_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QualityCertifier")


def make_billing_specialist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BillingSpecialist")


__all__ = [
    "TEST_USERS",
    "make_platform_admin_headers",
    "make_supply_planner_headers",
    "make_customer_ops_headers",
    "make_plant_operator_headers",
    "make_pipeline_dispatcher_headers",
    "make_telemetry_gateway_headers",
    "make_quality_analyst_headers",
    "make_quality_certifier_headers",
    "make_billing_specialist_headers",
]

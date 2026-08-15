"""Pre-built role headers for every role in the PRD (§2.1).

PlantManager, ProductionPlanner, LineOperator, QAManager, WarehouseLead, and
ClaimsAdjuster are opaque identities: X-User-ID is not tied to any persisted
entity (though it may be recorded as pasteurized_by / completed_by /
quarantined_by, so segregation-of-duties tests use per-user builders).

CustomerRep is entity-backed by Customer (X-User-ID is the Customer.id);
every ownership-gated call (contract submit, claim file/appeal/withdraw,
complaint withdraw) MUST use make_customer_rep_headers with the real
Customer.id. The shared constant is a fallback for non-ownership tests only.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not
# exercise ownership (400-on-bad-payload, 404-on-missing-resource,
# wrong-role checks).
TEST_USERS = {
    "plant_manager_headers": build_user_headers("pm_1", "PlantManager"),
    "production_planner_headers": build_user_headers("planner_1", "ProductionPlanner"),
    "line_operator_headers": build_user_headers("op_1", "LineOperator"),
    "qa_manager_headers": build_user_headers("qa_1", "QAManager"),
    "warehouse_lead_headers": build_user_headers("wh_1", "WarehouseLead"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "customer_rep_headers": build_user_headers("test-customer-1", "CustomerRep"),
    "claims_adjuster_headers": build_user_headers("adj_1", "ClaimsAdjuster"),
}


def make_plant_manager_headers(user_id: str = "pm_1") -> dict:
    return build_user_headers(user_id, "PlantManager")


def make_production_planner_headers(user_id: str = "planner_1") -> dict:
    return build_user_headers(user_id, "ProductionPlanner")


def make_line_operator_headers(user_id: str = "op_1") -> dict:
    """LineOperator is opaque; pass a distinct user_id per operator when a
    test exercises segregation of duties."""
    return build_user_headers(user_id, "LineOperator")


def make_qa_manager_headers(user_id: str = "qa_1") -> dict:
    """QAManager is opaque; pass a distinct user_id per QA user when a test
    exercises segregation of duties (release/verify/release-quarantine)."""
    return build_user_headers(user_id, "QAManager")


def make_warehouse_lead_headers(user_id: str = "wh_1") -> dict:
    return build_user_headers(user_id, "WarehouseLead")


def make_customer_rep_headers(customer_id: str) -> dict:
    """For CustomerRep (entity_backed:Customer). Pass the acting Customer.id
    whenever the call is ownership-gated."""
    return build_user_headers(customer_id, "CustomerRep")


def make_claims_adjuster_headers(user_id: str = "adj_1") -> dict:
    return build_user_headers(user_id, "ClaimsAdjuster")

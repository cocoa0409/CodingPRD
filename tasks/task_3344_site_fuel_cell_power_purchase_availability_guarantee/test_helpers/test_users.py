"""Pre-built role headers for every role in the PRD (PRD §2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — authoritative for the six opaque operator roles, and a
# fallback for the entity-backed Customer role on calls that are not
# ownership-gated (a missing resource, a malformed payload, a role check).
TEST_USERS = {
    "site_operator_headers": build_user_headers("test-site-operator-1", "SiteOperator"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "customer_service_headers": build_user_headers(
        "test-customer-service-1", "CustomerService"
    ),
    "fuel_coordinator_headers": build_user_headers(
        "test-fuel-coordinator-1", "FuelCoordinator"
    ),
    "service_engineer_headers": build_user_headers(
        "test-service-engineer-1", "ServiceEngineer"
    ),
    "settlement_analyst_headers": build_user_headers(
        "test-settlement-analyst-1", "SettlementAnalyst"
    ),
    "settlement_approver_headers": build_user_headers(
        "test-settlement-approver-1", "SettlementApprover"
    ),
}


def make_customer_headers(customer_id: str) -> dict:
    """For Customer (entity_backed:Customer).

    `X-User-ID` is the id of the acting Customer, not an opaque token, so any
    ownership-gated call MUST pass the actual Customer.id here rather than the
    shared constant above.
    """
    return build_user_headers(customer_id, "Customer")


def make_site_operator_headers(operator_id: str) -> dict:
    """For SiteOperator (opaque identity). One operator identity is as good as
    another for the authority this role carries; this builder exists so a test
    can name the acting operator explicitly where that is meaningful."""
    return build_user_headers(operator_id, "SiteOperator")


def make_customer_service_headers(operator_id: str) -> dict:
    """For CustomerService (opaque identity)."""
    return build_user_headers(operator_id, "CustomerService")


def make_fuel_coordinator_headers(operator_id: str) -> dict:
    """For FuelCoordinator (opaque identity)."""
    return build_user_headers(operator_id, "FuelCoordinator")


def make_service_engineer_headers(operator_id: str) -> dict:
    """For ServiceEngineer (opaque identity)."""
    return build_user_headers(operator_id, "ServiceEngineer")


def make_settlement_analyst_headers(operator_id: str) -> dict:
    """For SettlementAnalyst (opaque identity)."""
    return build_user_headers(operator_id, "SettlementAnalyst")


def make_settlement_approver_headers(operator_id: str) -> dict:
    """For SettlementApprover (opaque identity)."""
    return build_user_headers(operator_id, "SettlementApprover")
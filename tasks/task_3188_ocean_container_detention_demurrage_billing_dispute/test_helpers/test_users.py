"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that don't exercise ownership.
TEST_USERS = {
    "contract_manager_headers": build_user_headers("cm-1", "ContractManager"),
    "terminal_operator_headers": build_user_headers("to-1", "TerminalOperator"),
    "equipment_controller_headers": build_user_headers("ec-1", "EquipmentController"),
    "billing_agent_headers": build_user_headers("ba-1", "BillingAgent"),
    "credit_supervisor_headers": build_user_headers("sup-1", "CreditSupervisor"),
    "credit_director_headers": build_user_headers("dir-1", "CreditDirector"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "customer_rep_headers": build_user_headers("test-customer-rep-1", "CustomerRep"),
}


# Per-instance builders — required for every entity_backed role.
def make_customer_rep_headers(user_id: str) -> dict:
    """For CustomerRep (entity_backed:CustomerAccount). Pass the actual
    CustomerAccount.id as user_id whenever the call is ownership-gated
    (filing disputes, withdrawing, attaching evidence, booking appointments)."""
    return build_user_headers(user_id, "CustomerRep")


def make_contract_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ContractManager")


def make_terminal_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TerminalOperator")


def make_equipment_controller_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "EquipmentController")


def make_billing_agent_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BillingAgent")


def make_credit_supervisor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CreditSupervisor")


def make_credit_director_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CreditDirector")

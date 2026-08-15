"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    USER_ANALYST_1,
    USER_ANALYST_2,
    USER_MANAGER_1,
    USER_ACCOUNTANT_1,
    USER_RECOVERY_1,
    USER_GATEWAY,
)

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # opaque roles: shared constants are the canonical form
    "analyst_headers": build_user_headers(USER_ANALYST_1, "FraudAnalyst"),
    "analyst2_headers": build_user_headers(USER_ANALYST_2, "FraudAnalyst"),
    "manager_headers": build_user_headers(USER_MANAGER_1, "FraudOpsManager"),
    "accountant_headers": build_user_headers(USER_ACCOUNTANT_1, "LossAccountant"),
    "recovery_headers": build_user_headers(USER_RECOVERY_1, "RecoverySpecialist"),
    "gateway_headers": build_user_headers(USER_GATEWAY, "NetworkGateway"),
    # entity_backed role (Cardholder): shared constant is a fallback only for
    # tests that do NOT exercise ownership (e.g. 401/404 checks).
    "cardholder_headers": build_user_headers("test-cardholder-1", "Cardholder"),
}


def make_analyst_headers(user_id: str) -> dict:
    """FraudAnalyst headers with a specific opaque user id."""
    return build_user_headers(user_id, "FraudAnalyst")


def make_manager_headers(user_id: str) -> dict:
    """FraudOpsManager headers with a specific opaque user id."""
    return build_user_headers(user_id, "FraudOpsManager")


def make_accountant_headers(user_id: str) -> dict:
    """LossAccountant headers with a specific opaque user id."""
    return build_user_headers(user_id, "LossAccountant")


def make_recovery_headers(user_id: str) -> dict:
    """RecoverySpecialist headers with a specific opaque user id."""
    return build_user_headers(user_id, "RecoverySpecialist")


def make_gateway_headers(user_id: str = USER_GATEWAY) -> dict:
    """NetworkGateway headers."""
    return build_user_headers(user_id, "NetworkGateway")


def make_cardholder_headers(user_id: str) -> dict:
    """For Cardholder (entity_backed:Account). Pass the actual Account.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Cardholder")

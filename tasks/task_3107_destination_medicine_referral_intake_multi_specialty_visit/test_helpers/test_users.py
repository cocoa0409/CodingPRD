"""Pre-built role headers for every role in the PRD.

All roles are opaque (PRD §2.1): X-User-ID never equals any entity id and is
compared only against recorded operator identifiers (segregation of duties).
Shared constants are therefore canonical for every role.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import OP_ADMIN, OP_CR, OP_FC, OP_IC, OP_IC_B, OP_LC

TEST_USERS = {
    "platform_admin_headers": build_user_headers(OP_ADMIN, "PlatformAdmin"),
    "intake_coordinator_headers": build_user_headers(OP_IC, "IntakeCoordinator"),
    "intake_coordinator_b_headers": build_user_headers(OP_IC_B, "IntakeCoordinator"),
    "case_reviewer_headers": build_user_headers(OP_CR, "CaseReviewer"),
    "financial_counselor_headers": build_user_headers(OP_FC, "FinancialCounselor"),
    "logistics_coordinator_headers": build_user_headers(OP_LC, "LogisticsCoordinator"),
}


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_intake_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "IntakeCoordinator")


def make_case_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CaseReviewer")


def make_financial_counselor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FinancialCounselor")


def make_logistics_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LogisticsCoordinator")

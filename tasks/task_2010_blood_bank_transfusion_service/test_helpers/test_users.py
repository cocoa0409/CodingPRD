"""Pre-built role headers for every role in the PRD.

All five roles are opaque identities per the PRD user/role section: X-User-ID
is an operator identifier never compared against any entity's id. Named
operator constants are therefore the canonical form; segregation-of-duties
scenarios pick two DIFFERENT named operators of the appropriate role.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    COORDINATOR_ID,
    DOC_1_ID,
    DOC_2_ID,
    QO_1_ID,
    QO_2_ID,
    SUPERVISOR_ID,
    TECH_A_ID,
    TECH_B_ID,
    TECH_C_ID,
)

TEST_USERS = {
    "tech_a_headers": build_user_headers(TECH_A_ID, "BloodBankTechnologist"),
    "tech_b_headers": build_user_headers(TECH_B_ID, "BloodBankTechnologist"),
    "tech_c_headers": build_user_headers(TECH_C_ID, "BloodBankTechnologist"),
    "doc_1_headers": build_user_headers(DOC_1_ID, "OrderingPhysician"),
    "doc_2_headers": build_user_headers(DOC_2_ID, "OrderingPhysician"),
    "supervisor_headers": build_user_headers(SUPERVISOR_ID, "BloodBankSupervisor"),
    "coordinator_headers": build_user_headers(COORDINATOR_ID, "SupplierCoordinator"),
    "qo_1_headers": build_user_headers(QO_1_ID, "QualityOfficer"),
    "qo_2_headers": build_user_headers(QO_2_ID, "QualityOfficer"),
}


def make_technologist_headers(user_id: str = TECH_A_ID) -> dict:
    return build_user_headers(user_id, "BloodBankTechnologist")


def make_physician_headers(user_id: str = DOC_1_ID) -> dict:
    return build_user_headers(user_id, "OrderingPhysician")


def make_supervisor_headers(user_id: str = SUPERVISOR_ID) -> dict:
    return build_user_headers(user_id, "BloodBankSupervisor")


def make_coordinator_headers(user_id: str = COORDINATOR_ID) -> dict:
    return build_user_headers(user_id, "SupplierCoordinator")


def make_quality_officer_headers(user_id: str = QO_1_ID) -> dict:
    return build_user_headers(user_id, "QualityOfficer")

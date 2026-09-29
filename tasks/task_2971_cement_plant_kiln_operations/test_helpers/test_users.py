"""Per-role identities.

Internal roles carry an opaque ``X-User-ID`` that is never compared to an entity
id, so each distinct actor gets its own literal here; the two-person controls of
PRD §2.7 compare those literals. The ``Customer`` role is different: its
``X-User-ID`` is the id of the acting ``Customer`` row, so its headers can only
be built per instance, once a customer row exists.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CUSTOMER,
    ROLE_ENVIRONMENTAL_OFFICER,
    ROLE_KILN_OPERATOR,
    ROLE_LAB_TECHNICIAN,
    ROLE_LOGISTICS_PLANNER,
    ROLE_PLANT_ADMIN,
    ROLE_PROCESS_ENGINEER,
    ROLE_QUALITY_MANAGER,
)

ADMIN1_ID = "ADMIN1"
ADMIN2_ID = "ADMIN2"
ENG1_ID = "ENG1"
ENG2_ID = "ENG2"
OPS1_ID = "OPS1"
OPS2_ID = "OPS2"
LAB1_ID = "LAB1"
LAB2_ID = "LAB2"
QM1_ID = "QM1"
QM2_ID = "QM2"
EO1_ID = "EO1"
EO2_ID = "EO2"
LOG1_ID = "LOG1"
LOG2_ID = "LOG2"

TEST_USERS = {
    "plant_admin": build_user_headers(ADMIN1_ID, ROLE_PLANT_ADMIN),
    "plant_admin_2": build_user_headers(ADMIN2_ID, ROLE_PLANT_ADMIN),
    "process_engineer": build_user_headers(ENG1_ID, ROLE_PROCESS_ENGINEER),
    "process_engineer_2": build_user_headers(ENG2_ID, ROLE_PROCESS_ENGINEER),
    "kiln_operator": build_user_headers(OPS1_ID, ROLE_KILN_OPERATOR),
    "kiln_operator_2": build_user_headers(OPS2_ID, ROLE_KILN_OPERATOR),
    "lab_technician": build_user_headers(LAB1_ID, ROLE_LAB_TECHNICIAN),
    "lab_technician_2": build_user_headers(LAB2_ID, ROLE_LAB_TECHNICIAN),
    "quality_manager": build_user_headers(QM1_ID, ROLE_QUALITY_MANAGER),
    "quality_manager_2": build_user_headers(QM2_ID, ROLE_QUALITY_MANAGER),
    "environmental_officer": build_user_headers(EO1_ID, ROLE_ENVIRONMENTAL_OFFICER),
    "environmental_officer_2": build_user_headers(EO2_ID, ROLE_ENVIRONMENTAL_OFFICER),
    "logistics_planner": build_user_headers(LOG1_ID, ROLE_LOGISTICS_PLANNER),
    "logistics_planner_2": build_user_headers(LOG2_ID, ROLE_LOGISTICS_PLANNER),
}

# Convenience aliases used throughout the suite.
ADMIN_HEADERS = TEST_USERS["plant_admin"]
ENGINEER_HEADERS = TEST_USERS["process_engineer"]
ENGINEER2_HEADERS = TEST_USERS["process_engineer_2"]
OPERATOR_HEADERS = TEST_USERS["kiln_operator"]
LAB_HEADERS = TEST_USERS["lab_technician"]
LAB2_HEADERS = TEST_USERS["lab_technician_2"]
QUALITY_HEADERS = TEST_USERS["quality_manager"]
QUALITY2_HEADERS = TEST_USERS["quality_manager_2"]
ENV_HEADERS = TEST_USERS["environmental_officer"]
ENV2_HEADERS = TEST_USERS["environmental_officer_2"]
LOGISTICS_HEADERS = TEST_USERS["logistics_planner"]

INTERNAL_ROLE_HEADERS = {
    "PlantAdmin": ADMIN_HEADERS,
    "ProcessEngineer": ENGINEER_HEADERS,
    "KilnOperator": OPERATOR_HEADERS,
    "LabTechnician": LAB_HEADERS,
    "QualityManager": QUALITY_HEADERS,
    "EnvironmentalOfficer": ENV_HEADERS,
    "LogisticsPlanner": LOGISTICS_HEADERS,
}


def make_customer_headers(customer_id: str) -> dict:
    """Headers for the external ``Customer`` role, whose id is the customer row's id."""
    return build_user_headers(customer_id, ROLE_CUSTOMER)


def make_headers(user_id: str, role: str) -> dict:
    """Headers for an arbitrary user id / role pair."""
    return build_user_headers(user_id, role)


def headers_missing_user_id(role: str) -> dict:
    """Headers whose ``X-User-ID`` is transmitted as an empty string."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_missing_role(user_id: str) -> dict:
    """Headers whose ``X-User-Role`` is transmitted as an empty string."""
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}

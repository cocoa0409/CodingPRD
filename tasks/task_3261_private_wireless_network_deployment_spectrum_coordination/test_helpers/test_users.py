"""Pre-built role headers for every role in the PRD.

All five roles use opaque X-User-ID values (PRD §2.1): the server never
compares X-User-ID to any entity's id for ownership resolution. Where a
workflow ties an action to the same operator (submit/withdraw restricted to
the filing operator), the comparison is between X-User-ID and a recorded
field like surveyor_id / requesting_coordinator_id.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles and non-ownership tests.
TEST_USERS = {
    "network_architect_headers": build_user_headers("arch-001", "NetworkArchitect"),
    "rf_engineer_headers": build_user_headers("rfe-001", "RFEngineer"),
    "spectrum_coordinator_headers": build_user_headers("sc-001", "SpectrumCoordinator"),
    "spectrum_regulator_headers": build_user_headers("reg-001", "SpectrumRegulator"),
    "field_technician_headers": build_user_headers("ft-001", "FieldTechnician"),
}


def make_network_architect_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "NetworkArchitect")


def make_rf_engineer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RFEngineer")


def make_spectrum_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SpectrumCoordinator")


def make_spectrum_regulator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SpectrumRegulator")


def make_field_technician_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FieldTechnician")

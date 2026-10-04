"""Pre-built role headers for every role in the PRD (§2.1).

All eight roles use opaque X-User-ID identifiers: the server never compares
X-User-ID to any persisted entity id (the lone exception is the waiver's
granted_by audit stamp, which is recorded, never ownership-checked). Shared
constants are therefore the canonical form for every role.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "plant_manager_headers": build_user_headers("test-plant-manager-1", "PlantManager"),
    "mill_operator_headers": build_user_headers("test-mill-operator-1", "MillOperator"),
    "scheduler_headers": build_user_headers("test-scheduler-1", "Scheduler"),
    "metallurgist_headers": build_user_headers("test-metallurgist-1", "Metallurgist"),
    "procurement_officer_headers": build_user_headers("test-procurement-officer-1", "ProcurementOfficer"),
    "account_manager_headers": build_user_headers("test-account-manager-1", "AccountManager"),
    "quality_engineer_headers": build_user_headers("test-quality-engineer-1", "QualityEngineer"),
    "energy_dispatcher_headers": build_user_headers("test-energy-dispatcher-1", "EnergyDispatcher"),
}


def make_plant_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlantManager")


def make_mill_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MillOperator")


def make_scheduler_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Scheduler")


def make_metallurgist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Metallurgist")


def make_procurement_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProcurementOfficer")


def make_account_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AccountManager")


def make_quality_engineer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QualityEngineer")


def make_energy_dispatcher_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "EnergyDispatcher")

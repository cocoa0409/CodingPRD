"""Pre-built role headers for every role in the PRD (§2.1).

All five roles use the opaque identity model: X-User-ID is never compared
against any resource id, so shared constants are safe for every call.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "plant_operator_headers": build_user_headers("test-plant-operator-1", "PlantOperator"),
    "contracts_manager_headers": build_user_headers("test-contracts-manager-1", "ContractsManager"),
    "energy_trader_headers": build_user_headers("test-energy-trader-1", "EnergyTrader"),
    "environmental_officer_headers": build_user_headers("test-environmental-officer-1", "EnvironmentalOfficer"),
    "regulator_headers": build_user_headers("test-regulator-1", "Regulator"),
}


def make_plant_operator_headers(user_id: str = "test-plant-operator-1") -> dict:
    return build_user_headers(user_id, "PlantOperator")


def make_contracts_manager_headers(user_id: str = "test-contracts-manager-1") -> dict:
    return build_user_headers(user_id, "ContractsManager")


def make_energy_trader_headers(user_id: str = "test-energy-trader-1") -> dict:
    return build_user_headers(user_id, "EnergyTrader")


def make_environmental_officer_headers(user_id: str = "test-environmental-officer-1") -> dict:
    return build_user_headers(user_id, "EnvironmentalOfficer")


def make_regulator_headers(user_id: str = "test-regulator-1") -> dict:
    return build_user_headers(user_id, "Regulator")

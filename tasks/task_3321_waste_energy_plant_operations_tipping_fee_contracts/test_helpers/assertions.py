"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be an integer >= 1"


def assert_municipality(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["population_served"], int)
    assert isinstance(data["is_host_community"], bool)
    assert data["priority_group"] in ("HOST", "STANDARD")


def assert_waste_supply_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("municipality_id", ""))
    assert data["state"] in ("DRAFT", "ACTIVE", "EXPIRED", "TERMINATED")
    assert isinstance(data["tipping_fee_per_tonne_cents"], int)


def assert_waste_delivery(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("agreement_id", ""))
    assert data["status"] in ("SCHEDULED", "RECEIVED", "REJECTED", "DIVERTED", "ACCEPTED")
    assert data["tonnes"] > 0


def assert_boiler(data: dict):
    _assert_common(data)
    assert data["status"] in ("ONLINE", "OUTAGE", "DERATED", "OFFLINE")
    assert data["max_thermal_capacity_mw"] > 0
    assert data["max_steam_tph"] > 0


def assert_outage_window(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("boiler_id", ""))
    assert data["status"] in ("SCHEDULED", "ACTIVE", "COMPLETED", "CANCELLED")
    assert data["kind"] in ("PLANNED", "EMERGENCY")


def assert_diversion_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["approved"], bool)
    assert data["max_diversion_tpd"] > 0


def assert_daily_throughput_report(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "FINALIZED")
    assert data["capacity_check"] in ("OK", "EXCEEDS")
    assert 0 < data["operating_hours"] <= 24


def assert_landfill(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "CLOSED")
    assert data["remaining_capacity_tonnes"] >= 0


def assert_ash_shipment(data: dict):
    _assert_common(data)
    assert data["status"] in ("PLANNED", "TEST_PENDING", "DISPOSED", "REJECTED")
    assert data["tonnes"] > 0


def assert_metals_recovery_batch(data: dict):
    _assert_common(data)
    assert data["status"] in ("RECORDED", "SETTLED", "DISPUTED")
    assert data["ash_input_tonnes"] > 0


def assert_emissions_reading(data: dict):
    _assert_common(data)
    assert isinstance(data["exceedance"], bool)
    assert data["value"] > 0

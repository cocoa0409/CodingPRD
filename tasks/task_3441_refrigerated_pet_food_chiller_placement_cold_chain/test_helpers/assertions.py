"""Entity assertions and domain invariant checkers (PRD §2.5, §2.11)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a prefix-less UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be an integer >= 1"


def assert_store(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region"], str) and data["region"]
    for field in ("demographic_index", "weekly_category_velocity_index", "competitor_density_index"):
        assert isinstance(data[field], int) and 0 <= data[field] <= 100, f"{field} must be an integer in 0..100"
    assert isinstance(data["available_sqft"], int) and data["available_sqft"] > 0
    assert data["distance_miles_from_plant"] >= 0


def assert_site_evaluation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("store_id", "")), "store_id must be a UUID"
    assert data["model_variant"] in ("DEMOGRAPHIC_LED", "VELOCITY_LED")
    assert data["chiller_model"] in ("STANDARD", "COMPACT")
    assert data["forecast_weekly_units"] > 0
    assert isinstance(data["allocated_sqft"], int) and data["allocated_sqft"] > 0
    assert isinstance(data["install_quote_cents"], int)
    assert data["verdict"] in ("ELIGIBLE", "INELIGIBLE")
    if data["payback_months"] is not None:
        assert isinstance(data["payback_months"], (int, float))


def assert_placement_agreement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("store_id", "")), "store_id must be a UUID"
    assert isinstance(data["allocated_sqft"], int) and data["allocated_sqft"] > 0
    assert isinstance(data["max_capex_cents"], int) and data["max_capex_cents"] > 0
    assert isinstance(data["term_months"], int) and 1 <= data["term_months"] <= 120
    assert data["status"] in ("PROPOSED", "SIGNED", "ACTIVE", "TERMINATED")
    if data["status"] in ("SIGNED", "ACTIVE", "TERMINATED") and data.get("signed_at") is not None:
        assert is_iso8601_timestamp(data["signed_at"])
    if data["status"] == "TERMINATED":
        assert is_iso8601_timestamp(data["terminated_at"])


def assert_chiller(data: dict):
    _assert_common_fields(data)
    assert data["model"] in ("STANDARD", "COMPACT")
    assert isinstance(data["serial_no"], str) and data["serial_no"]
    expected_capacity = 240 if data["model"] == "STANDARD" else 120
    expected_footprint = 8 if data["model"] == "STANDARD" else 5
    assert data["capacity_units"] == expected_capacity, "capacity_units derives from model (PRD §3.3)"
    assert data["footprint_sqft"] == expected_footprint, "footprint_sqft derives from model (PRD §3.3)"
    assert data["status"] in ("IN_STOCK", "INSTALLED", "ACTIVE", "NEEDS_REPAIR", "DECOMMISSIONED")
    assert isinstance(data["excursion_minutes_24h"], int) and data["excursion_minutes_24h"] >= 0


def assert_placement(data: dict):
    _assert_common_fields(data)
    for field in ("store_id", "chiller_id", "agreement_id"):
        assert is_valid_uuid(data.get(field, "")), f"{field} must be a UUID"
    assert data["status"] in ("ACTIVE", "RETIRED")
    assert data["performance_status"] in ("PENDING", "PERFORMING", "UNDERPERFORMING")
    assert data["operational_status"] in ("OK", "SUSPENDED")
    assert isinstance(data["underperforming_streak"], int) and data["underperforming_streak"] >= 0
    assert isinstance(data["standing_deliveries_per_week"], int) and 0 <= data["standing_deliveries_per_week"] <= 5
    assert isinstance(data["safety_stock_units"], int) and data["safety_stock_units"] >= 0
    assert isinstance(data["installed_quote_cents"], int)
    if data["status"] == "RETIRED":
        assert data["retired_reason"] in ("UNDERPERFORMANCE_REMOVAL", "AGREEMENT_TERMINATION", "RELOCATION")


def assert_temperature_reading(data: dict):
    # Append-only record: id + created_at only; NO updated_at, NO version (PRD §2.5).
    assert is_valid_uuid(data.get("id", "")), "id must be a prefix-less UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "temperature readings must not carry updated_at (PRD §2.5)"
    assert "version" not in data, "temperature readings must not carry version (PRD §2.5)"
    assert is_valid_uuid(data.get("chiller_id", "")), "chiller_id must be a UUID"
    assert is_iso8601_timestamp(data.get("recorded_at", "")), "recorded_at must be ISO 8601"
    assert -40.0 <= data["temp_c"] <= 60.0, "temp_c must be within the sensor-plausible range"
    assert isinstance(data["duration_minutes"], int) and 1 <= data["duration_minutes"] <= 1440
    assert isinstance(data["is_excursion"], bool)


def assert_service_ticket(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("chiller_id", "")), "chiller_id must be a UUID"
    assert data["origin"] in ("MANUAL", "AUTO_EXCURSION")
    assert isinstance(data["issue_summary"], str) and data["issue_summary"]
    assert data["status"] in ("OPEN", "DISPATCHED", "RESOLVED", "CANCELLED")


def assert_shipment(data: dict):
    _assert_common_fields(data)
    for field in ("store_id", "lot_id"):
        assert is_valid_uuid(data.get(field, "")), f"{field} must be a UUID"
    assert isinstance(data["quantity_units"], int) and data["quantity_units"] > 0
    assert is_iso8601_timestamp(data.get("departed_at", "")), "departed_at must be ISO 8601"
    assert data["status"] in ("IN_TRANSIT", "DELIVERED", "SPOILED")


def assert_product_lot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert is_iso8601_timestamp(data.get("produced_at", "")), "produced_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("expires_at", "")), "expires_at must be ISO 8601"
    assert isinstance(data["quantity_units"], int) and data["quantity_units"] > 0
    assert data["status"] in ("QUARANTINE", "RELEASED", "REJECTED", "EXPIRED")
    for field in ("unshipped_qty", "in_transit_qty", "in_store_qty", "removed_qty", "spoiled_qty"):
        assert isinstance(data[field], int) and data[field] >= 0, f"{field} must be a non-negative integer"


def assert_lot_conservation(data: dict):
    """PRD §2.11: quantity_units == sum of the five bucket counters, at all times."""
    total = (
        data["unshipped_qty"]
        + data["in_transit_qty"]
        + data["in_store_qty"]
        + data["removed_qty"]
        + data["spoiled_qty"]
    )
    assert total == data["quantity_units"], (
        f"lot conservation violated: buckets sum to {total}, quantity_units is {data['quantity_units']}"
    )


def assert_inventory_position(data: dict):
    _assert_common_fields(data)
    for field in ("store_id", "lot_id"):
        assert is_valid_uuid(data.get(field, "")), f"{field} must be a UUID"
    assert isinstance(data["qty_on_hand"], int) and data["qty_on_hand"] >= 0
    assert is_iso8601_timestamp(data.get("expiry_date", "")), "expiry_date must be ISO 8601"
    assert data["status"] in ("SELLABLE", "QUARANTINED", "REMOVED")
    if data["status"] == "REMOVED":
        assert data["removal_reason"] in ("NEAR_EXPIRY", "EXPIRED", "COLD_CHAIN_BREACH")


def assert_capacity_project(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["capacity_delta_units"], int) and data["capacity_delta_units"] > 0
    assert data["status"] in ("PROPOSED", "APPROVED", "COMMISSIONED")
    if data["status"] in ("APPROVED", "COMMISSIONED"):
        assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]


def assert_trial_campaign(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("store_id", "")), "store_id must be a UUID"
    assert isinstance(data["name"], str) and data["name"]
    assert is_iso8601_timestamp(data.get("start_date", "")), "start_date must be ISO 8601"
    assert is_iso8601_timestamp(data.get("end_date", "")), "end_date must be ISO 8601"
    assert data["status"] in ("ACTIVE", "COMPLETED")

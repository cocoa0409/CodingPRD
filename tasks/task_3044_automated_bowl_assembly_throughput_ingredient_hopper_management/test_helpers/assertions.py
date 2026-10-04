"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_mutable_common_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive integer"
    )


def _assert_append_only_common_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 timestamp"
    )
    assert "version" not in data, f"{label} is append-only: no version field"
    assert "updated_at" not in data, f"{label} is append-only: no updated_at field"


def assert_restaurant(data: dict):
    _assert_mutable_common_fields(data, "restaurant")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["city"], str) and data["city"]


def assert_assembly_line(data: dict):
    _assert_mutable_common_fields(data, "assembly_line")
    assert is_valid_uuid(data.get("restaurant_id", "")), "assembly_line.restaurant_id must be a UUID"
    assert data["line_type"] in ("AUTOMATED", "MANUAL")
    assert isinstance(data["service_rate_seconds_per_bowl"], int)
    assert data["service_rate_seconds_per_bowl"] > 0
    assert data["status"] in ("ACTIVE", "PAUSED", "CLEANING")
    assert data["posture"] in ("OPEN", "RESTRICTED", "FROZEN")


def assert_ingredient(data: dict):
    _assert_mutable_common_fields(data, "ingredient")
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["station_type"] in ("BASE", "PROTEIN", "TOPPING", "DRESSING")
    assert isinstance(data["shelf_life_minutes"], int) and data["shelf_life_minutes"] > 0
    assert data["status"] in ("ACTIVE", "EIGHTY_SIXED")


def assert_recipe(data: dict):
    _assert_mutable_common_fields(data, "recipe")
    assert is_valid_uuid(data.get("restaurant_id", "")), "recipe.restaurant_id must be a UUID"
    assert isinstance(data["portion_spec"], list) and len(data["portion_spec"]) >= 1
    assert isinstance(data["is_available"], bool)


def assert_hopper(data: dict):
    _assert_mutable_common_fields(data, "hopper")
    assert data["status"] in (
        "LOADING", "IN_SERVICE", "DEPLETED", "REFILL_SCHEDULED", "REFILLING", "QUARANTINED",
    )
    assert data["current_grams"] >= 0
    assert data["capacity_grams"] > 0
    assert 0.5 <= data["calibration_coefficient"] <= 2.0


def assert_refill_task(data: dict):
    _assert_mutable_common_fields(data, "refill_task")
    assert data["status"] in ("SCHEDULED", "READY", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    assert isinstance(data["auto_created"], bool)
    assert isinstance(data["allocated_grams"], (int, float))


def assert_prep_batch(data: dict):
    _assert_mutable_common_fields(data, "prep_batch")
    assert data["status"] in ("IN_PREP", "READY", "CONSUMED", "EXPIRED")
    assert data["quantity_grams"] > 0


def assert_prep_batch_quantity_invariant(data: dict):
    """quantity_grams always equals allocated + consumed + available (PRD §3.3)."""
    total = data["allocated_grams"] + data["consumed_grams"] + data["available_grams"]
    assert abs(total - data["quantity_grams"]) < 1e-6, (
        f"batch invariant violated: quantity {data['quantity_grams']} != "
        f"allocated {data['allocated_grams']} + consumed {data['consumed_grams']} "
        f"+ available {data['available_grams']}"
    )


def assert_order(data: dict):
    _assert_mutable_common_fields(data, "order")
    assert data["status"] in ("QUEUED", "ASSEMBLING", "VERIFICATION", "COMPLETED", "CANCELLED")
    assert data["route"] in ("AUTOMATED", "MANUAL")
    assert isinstance(data["remake_count"], int) and data["remake_count"] >= 0


def assert_substitution_rule(data: dict):
    _assert_mutable_common_fields(data, "substitution_rule")
    assert data["status"] in ("PENDING", "ACTIVE", "RETIRED", "REJECTED")


def assert_sanitation_cycle(data: dict):
    _assert_mutable_common_fields(data, "sanitation_cycle")
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "ABORTED")


def assert_labor_assignment(data: dict):
    _assert_mutable_common_fields(data, "labor_assignment")
    assert data["from_role"] == "MAKE_LINE"
    assert data["to_role"] in ("PREP", "HOSPITALITY")
    assert isinstance(data["is_active"], bool)


def assert_portion_verification(data: dict):
    _assert_append_only_common_fields(data, "portion_verification")
    assert data["result"] in ("PASS", "FAIL")
    assert data["actual_grams"] >= 0


def assert_calibration_adjustment(data: dict):
    _assert_append_only_common_fields(data, "calibration_adjustment")
    assert 0.5 <= data["new_coefficient"] <= 2.0


def assert_hopper_mass_balance(data: dict):
    """current + dispensed + waste - refilled == initial_load (PRD §2.6)."""
    total = (
        data["current_grams"]
        + data["cumulative_dispensed_grams"]
        + data["cumulative_waste_grams"]
        - data["cumulative_refilled_grams"]
    )
    assert abs(total - data["initial_load_grams"]) < 1e-6, (
        f"hopper mass balance violated: {data['current_grams']} + "
        f"{data['cumulative_dispensed_grams']} + {data['cumulative_waste_grams']} - "
        f"{data['cumulative_refilled_grams']} != initial_load {data['initial_load_grams']}"
    )

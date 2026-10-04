"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Every entity carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be an integer starting at 1"
    )


def assert_incident(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["country_code"], str) and len(data["country_code"]) == 2
    assert data["disaster_type"] in [
        "EARTHQUAKE", "FLOOD", "HURRICANE", "WILDFIRE", "CONFLICT", "EPIDEMIC",
    ]
    assert 1 <= data["severity_level"] <= 5
    assert data["target_daily_meals"] >= 1
    assert data["funding_ceiling_cents"] >= 0
    assert isinstance(data["currency_code"], str) and len(data["currency_code"]) == 3
    assert data["status"] in ["MONITORING", "ACTIVE", "WINDING_DOWN", "CLOSED"]
    assert isinstance(data["population_dietary_requirements"], list)
    assert isinstance(data["committed_cents"], int) and data["committed_cents"] >= 0
    assert isinstance(data["spent_cents"], int) and data["spent_cents"] >= 0
    assert isinstance(data["delivered_meal_total"], int)
    assert isinstance(data["local_sourcing_pct"], int)
    assert isinstance(data["cost_per_meal_cents"], int)


def assert_assessment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["incident_id"])
    assert is_iso8601_timestamp(data["assessed_at"])
    assert data["population_affected"] >= 0
    assert data["estimated_daily_meal_need"] >= 0
    assert data["access_constraint"] in ["OPEN", "LIMITED", "RESTRICTED", "BLOCKED"]
    assert isinstance(data["water_available"], bool)
    assert isinstance(data["power_available"], bool)
    assert data["partner_kitchens_identified"] >= 0
    assert data["assessment_mode"] in ["RAPID", "DURABLE"]
    assert 0 <= data["feeding_priority_score"] <= 100
    assert data["status"] in ["SUBMITTED", "SUPERSEDED"]


def assert_field_kitchen(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["incident_id"])
    assert is_valid_uuid(data["assessment_id"])
    assert -90.0 <= data["latitude"] <= 90.0
    assert -180.0 <= data["longitude"] <= 180.0
    assert data["power_source"] in ["GRID", "GENERATOR", "SOLAR", "NONE"]
    assert data["water_source"] in ["PIPED", "TRUCKED", "WELL", "NONE"]
    assert data["refrigeration_hours_available"] >= 0
    assert data["daily_capacity_meals"] >= 0
    assert data["site_status"] in [
        "SITED", "UTILITIES_PENDING", "FOOD_SAFETY_CLEARED", "OPERATIONAL",
        "SUSPENDED", "DEMOBILIZED",
    ]
    assert 0 <= data["food_safety_score"] <= 100
    assert isinstance(data["runs_today_count"], int)


def assert_partner_kitchen(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["incident_id"])
    assert isinstance(data["business_name"], str) and data["business_name"]
    assert isinstance(data["cuisine_tags"], list)
    assert data["daily_capacity_meals"] >= 1
    assert data["per_meal_price_cents"] >= 1
    assert isinstance(data["bank_verified"], bool)
    assert 0 <= data["vetting_score"] <= 100
    assert data["contract_status"] in [
        "PROSPECT", "VETTING", "CONTRACTED", "SUSPENDED", "TERMINATED",
    ]
    assert data["production_status"] in ["IDLE", "PRODUCING", "AT_CAPACITY", "COOLDOWN"]
    assert 0 <= data["quality_score"] <= 100
    assert data["meals_produced_total"] >= 0
    assert data["meals_produced_today"] >= 0


def assert_meal_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["incident_id"])
    assert is_valid_uuid(data["partner_kitchen_id"])
    assert data["ordered_meals"] >= 1
    assert data["production_hours"] >= 1
    assert data["status"] in [
        "PLACED", "IN_PRODUCTION", "QUALITY_HOLD", "READY", "DISPATCHED",
        "DELIVERED", "REJECTED", "CANCELLED",
    ]
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["logistics_fee_cents"], int)
    assert isinstance(data["volume_discount_cents"], int)
    assert isinstance(data["provisional_cost_cents"], int)
    assert data["rework_count"] >= 0
    assert data["accepted_meals"] >= 0


def assert_supplier(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["incident_id"])
    assert data["payment_terms_days"] >= 0
    assert data["status"] in ["PROSPECT", "APPROVED", "PREFERRED", "SUSPENDED"]
    assert data["cash_flow_received_cents"] >= 0
    assert 0 <= data["reliability_score"] <= 100
    assert data["delivered_purchase_count"] >= 0
    assert data["disputed_purchase_count"] >= 0


def assert_ingredient_purchase(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["incident_id"])
    assert is_valid_uuid(data["supplier_id"])
    assert is_valid_uuid(data["partner_kitchen_id"])
    assert data["quantity_kg"] > 0
    assert data["unit_price_cents_per_kg"] >= 1
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in [
        "REQUESTED", "CONFIRMED", "DELIVERED", "PAID", "DISPUTED", "CANCELLED",
    ]


def assert_distribution_site(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["incident_id"])
    assert data["site_type"] in [
        "SHELTER", "HOSPITAL", "NEIGHBORHOOD", "SCHOOL", "COMMUNITY_CENTER",
    ]
    assert data["population_served"] >= 0
    assert data["daily_meal_request"] >= 0
    assert data["access_constraint"] in ["OPEN", "LIMITED", "RESTRICTED", "BLOCKED"]
    assert data["status"] in ["REGISTERED", "ACTIVE", "SERVICE_ALERT", "CLOSED"]
    assert data["received_meals_total"] >= 0
    assert data["skipped_stop_count"] >= 0
    assert data["delivered_stop_count"] >= 0


def assert_distribution_run(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["incident_id"])
    assert is_valid_uuid(data["field_kitchen_id"])
    assert isinstance(data["driver_safety_training_completed"], bool)
    assert data["vehicle_type"] in ["CAR", "VAN", "TRUCK", "MOTORCYCLE"]
    assert data["loaded_meals"] >= 0
    assert data["fuel_cost_cents"] >= 0
    assert data["handling_cost_cents"] >= 0
    assert data["status"] in [
        "PLANNED", "LOADING", "EN_ROUTE", "DELIVERING", "COMPLETED", "ABORTED",
    ]
    assert data["total_cost_cents"] == data["fuel_cost_cents"] + data["handling_cost_cents"]
    assert data["delivered_meals"] >= 0
    assert data["returned_meals"] >= 0
    assert data["unallocated_cost_cents"] >= 0


def assert_distribution_stop(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["distribution_run_id"])
    assert is_valid_uuid(data["distribution_site_id"])
    assert data["stop_sequence"] >= 1
    assert data["planned_meals"] >= 0
    assert data["delivered_meals"] >= 0
    assert isinstance(data["allocated_cost_cents"], int)
    assert data["status"] in ["PENDING", "DELIVERED", "FAILED", "SKIPPED"]


def assert_donor_commitment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["incident_id"])
    assert data["amount_cents"] >= 1
    assert data["earmark"] in [
        "UNRESTRICTED", "FIELD_KITCHENS", "RESTAURANT_ACTIVATION",
        "INGREDIENT_SOURCING", "LOGISTICS",
    ]
    assert data["status"] in [
        "PLEDGED", "RECEIVED", "ALLOCATED", "PARTIALLY_DISBURSED", "CLOSED", "WITHDRAWN",
    ]
    assert data["allocated_cents"] >= 0
    assert data["disbursed_cents"] >= 0
    assert data["remaining_cents"] == data["amount_cents"] - data["disbursed_cents"]


def assert_run_meal_conservation(run: dict, pending_planned_meals: int):
    """loaded_meals == delivered_meals + returned_meals + pending planned meals."""
    assert run["loaded_meals"] == (
        run["delivered_meals"] + run["returned_meals"] + pending_planned_meals
    ), (
        "meal conservation violated: loaded="
        f"{run['loaded_meals']} delivered={run['delivered_meals']} "
        f"returned={run['returned_meals']} pending={pending_planned_meals}"
    )


def assert_commitment_conservation(commitment: dict):
    assert commitment["remaining_cents"] >= 0
    assert commitment["disbursed_cents"] <= commitment["amount_cents"]

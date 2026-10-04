"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a positive integer"
    )


def assert_yard(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["yard_code"], str) and data["yard_code"]
    assert data["dwell_benchmark_hours"] > 0
    assert isinstance(data["classification_capacity_cars"], int)
    assert data["classification_capacity_cars"] >= 1
    assert data["posture"] in ("OPEN", "CONGESTED", "EMBARGOED")
    assert data["current_dwell_overage_hours"] >= 0


def assert_train_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["train_symbol"], str) and data["train_symbol"]
    assert data["origin_yard_id"] != data["destination_yard_id"]
    assert isinstance(data["cutoff_minutes"], int) and data["cutoff_minutes"] >= 1
    assert isinstance(data["frequency_mask"], list) and len(data["frequency_mask"]) >= 1
    for day in data["frequency_mask"]:
        assert day in ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
    assert data["route_distance_miles"] > 0
    assert data["dwell_benchmark_hours"] >= 0
    assert data["status"] in ("DRAFT", "ACTIVE", "RETIRED")


def assert_crew_pool(data: dict):
    _assert_common_fields(data)
    assert data["craft"] in ("CONDUCTOR", "ENGINEER")
    assert isinstance(data["service_date"], str) and len(data["service_date"]) == 10
    assert isinstance(data["crews_available"], int) and data["crews_available"] >= 1
    assert isinstance(data["crews_booked"], int) and data["crews_booked"] >= 0
    assert data["crews_booked"] <= data["crews_available"]
    assert data["status"] in ("OPEN", "EXHAUSTED", "CLOSED", "REOPENED")


def assert_locomotive(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["unit_number"], str) and data["unit_number"]
    assert isinstance(data["horsepower"], int) and data["horsepower"] >= 1000
    assert data["status"] in ("AVAILABLE", "ASSIGNED", "BAD_ORDER")


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["customer_code"], str) and data["customer_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["service_credit_balance"], int)
    assert data["service_credit_balance"] >= 0


def assert_shipment(data: dict):
    _assert_common_fields(data)
    assert data["origin_yard_id"] != data["destination_yard_id"]
    assert isinstance(data["car_count"], int) and data["car_count"] >= 1
    assert data["committed_route_miles"] > 0
    assert data["trip_plan_status"] in (
        "UNASSIGNED", "ASSIGNED", "MISSED_CONNECTION", "REPLANNED",
    )
    assert data["compliance_status"] in ("ON_PLAN", "AT_RISK", "OFF_PLAN")
    assert isinstance(data["total_missed_connections"], int)
    assert data["total_missed_connections"] >= 0
    assert data["status"] in ("OPEN", "IN_TRANSIT", "DELIVERED", "CANCELLED")


def assert_trip_leg(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["leg_sequence"], int) and data["leg_sequence"] >= 1
    assert data["connection_status"] in ("PENDING", "MADE", "MISSED", "NOT_APPLICABLE")
    assert data["status"] in ("PLANNED", "EN_ROUTE", "COMPLETED", "MISSED", "REPLACED")


def assert_train_departure(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["car_count_planned"], int) and data["car_count_planned"] >= 1
    assert data["crew_hours_estimated"] > 0
    assert data["status"] in ("SCHEDULED", "DEPARTED", "CANCELLED")


def assert_car_event(data: dict):
    # Append-only event log: id + created_at only beyond declared fields.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "car events must not carry updated_at"
    assert "version" not in data, "car events must not carry version"
    assert data["event_type"] in (
        "TRAIN_DEPARTURE", "YARD_ARRIVAL", "CLASSIFICATION_COMPLETE", "PLACED_DELIVERED",
    )
    assert isinstance(data["car_count"], int) and data["car_count"] >= 1


def assert_service_exception(data: dict):
    _assert_common_fields(data)
    assert data["exception_type"] in (
        "MISSED_CONNECTION", "DWELL_OVERAGE", "DEPARTURE_DELAY",
        "PICKUP_MISS", "DELIVERY_MISS",
    )
    assert data["status"] in ("OPEN", "INVESTIGATING", "RESOLVED")


def assert_pool_invariants(pool: dict):
    """Crew-pool invariants that must hold after any operation."""
    assert 0 <= pool["crews_booked"] <= pool["crews_available"]
    if pool["status"] == "EXHAUSTED":
        assert pool["crews_booked"] == pool["crews_available"]

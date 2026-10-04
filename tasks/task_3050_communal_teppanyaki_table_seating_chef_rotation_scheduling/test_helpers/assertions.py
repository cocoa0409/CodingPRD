"""Entity assertions and domain invariant checkers for the service floor."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

COMMON_FIELDS = ("id", "created_at", "updated_at", "version")


def assert_common_fields(data: dict):
    """Every resource family carries the four system-managed properties."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def assert_venue(data: dict):
    assert_common_fields(data)
    assert isinstance(data["venue_name"], str) and data["venue_name"]
    assert isinstance(data["city_code"], str) and data["city_code"]
    assert data["ventilation_zone"] in ["ZONE_A", "ZONE_B", "ZONE_C", "ZONE_D"]
    assert data["status"] in ["ACTIVE", "VENTILATION_HOLD"]
    assert isinstance(data["occupancy_freeze"], bool)
    assert isinstance(data["hood_filter_life_index"], int)
    assert isinstance(data["filter_service_threshold_index"], int)
    assert isinstance(data["ops_epoch"], int)
    assert isinstance(data["shortfall_turn_debt_minutes"], int)
    assert isinstance(data["restaurant_charge_cents"], int)
    assert data["shortfall_turn_debt_minutes"] >= 0


def assert_party(data: dict):
    assert_common_fields(data)
    assert isinstance(data["lead_guest_name"], str) and data["lead_guest_name"]
    assert isinstance(data["contact_phone"], str)
    assert data["loyalty_tier"] in ["NONE", "SILVER", "GOLD", "PLATINUM"]
    assert data["status"] in ["ACTIVE", "RESTRICTED"]
    assert isinstance(data["no_show_count"], int) and data["no_show_count"] >= 0
    assert isinstance(data["loyalty_credit_cents"], int)
    assert data["loyalty_credit_cents"] >= 0, "loyalty_credit_cents is strictly non-negative"


def assert_tier(data: dict):
    assert_common_fields(data)
    assert data["tier_code"] in ["T2", "T4", "T6", "T8", "T10"]
    assert isinstance(data["seat_capacity"], int) and data["seat_capacity"] > 0
    assert isinstance(data["base_rate_per_guest_cents"], int)
    assert isinstance(data["minimum_bill_cents"], int)
    assert isinstance(data["protein_gram_standard"], int)
    assert isinstance(data["chef_show_minutes"], int)
    assert isinstance(data["turn_time_standard_minutes"], int)
    assert isinstance(data["turn_time_celebration_minutes"], int)
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_table(data: dict):
    assert_common_fields(data)
    assert data["tier_code"] in ["T2", "T4", "T6", "T8", "T10"]
    assert data["status"] in ["AVAILABLE", "SEATED", "TURNING", "MAINTENANCE"]
    assert isinstance(data["seat_capacity"], int)
    assert isinstance(data["guests_seated"], int) and data["guests_seated"] >= 0
    assert isinstance(data["pending_turn"], bool)
    if data["status"] != "MAINTENANCE":
        assert data.get("maintenance_resume_at") is None, \
            "maintenance_resume_at is null unless status is MAINTENANCE"


def assert_reservation(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["DRAFT", "REQUESTED", "HELD", "SEATED", "CLOSED",
                              "NO_SHOW", "ABANDONED"]
    assert data["payment_mode"] in ["CARD_ONLY", "CARD_THEN_CREDIT", "CREDIT_ONLY"]
    assert data["celebration"] in ["NONE", "BIRTHDAY", "ANNIVERSARY",
                                   "GRADUATION", "CORPORATE"]
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1
    assert isinstance(data["hold_count"], int) and data["hold_count"] >= 0
    for field in ("quote_final_cents", "final_bill_cents", "check_cents",
                  "seat_surcharge_cents", "credit_applied_cents",
                  "celebration_fee_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_seating(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["ACTIVE", "VACATED"]
    assert isinstance(data["guest_count"], int) and data["guest_count"] >= 0
    assert is_iso8601_timestamp(data["seated_at"])
    assert is_iso8601_timestamp(data["expected_vacate_at"])
    assert isinstance(data["occupied_minutes"], int) and data["occupied_minutes"] >= 0
    if data["status"] == "VACATED":
        assert data.get("actual_vacated_at") is not None
    else:
        assert data.get("actual_vacated_at") is None


def assert_chef(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["OFF_SHIFT", "ON_STATION", "CLEARING"]
    assert data["station_zone"] in ["ZONE_A", "ZONE_B", "ZONE_C", "ZONE_D"]
    assert isinstance(data["completed_show_count"], int)
    assert isinstance(data["minutes_since_show"], int)
    assert float(data["pounds_protein_issued"]) >= 0
    if data["status"] != "OFF_SHIFT":
        assert isinstance(data["sequence_index"], int) and data["sequence_index"] >= 1
    else:
        assert data.get("sequence_index") is None


def assert_show(data: dict):
    assert_common_fields(data)
    assert data["course_phase"] in ["SUSHI", "GRILL", "DESSERT", "CELEBRATION"]
    assert data["status"] in ["PLANNED", "STARTED", "FINISHED", "SKIPPED"]
    assert is_iso8601_timestamp(data["planned_start_at"])
    assert isinstance(data["duration_minutes"], int)
    assert isinstance(data["protein_grams_served"], int)


def assert_maintenance_window(data: dict):
    assert_common_fields(data)
    assert data["maintenance_kind"] in ["VENTILATION_SERVICE", "GRILL_REBUILD",
                                        "HOOD_DEEP_CLEAN"]
    assert data["status"] in ["SCHEDULED", "ACTIVE", "COMPLETED"]
    assert is_iso8601_timestamp(data["planned_start_at"])
    assert is_iso8601_timestamp(data["planned_end_at"])


def assert_sushi_ticket(data: dict):
    assert_common_fields(data)
    assert data["prep_phase"] in ["RAW_CUT", "ROLLED", "PLATED"]
    assert data["status"] in ["OPEN", "VOIDED"]
    assert isinstance(data["quantity"], int)
    assert isinstance(data["unit_price_cents"], int)


def assert_ledger_entry(data: dict):
    assert_common_fields(data)
    assert data["entry_kind"] in ["SEAT_SURCHARGE", "CELEBRATION_CHARGE",
                                  "TABLE_MINIMUM_TRUEUP"]
    assert data["status"] in ["POSTED", "VOIDED"]
    assert isinstance(data["amount_cents"], int)


def assert_protein_ticket(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["POSTED", "VOIDED"]
    assert isinstance(data["standard_grams"], int)
    assert isinstance(data["issued_grams"], int)
    assert data["variance_grams"] == data["issued_grams"] - data["standard_grams"], \
        "variance_grams must be issued_grams - standard_grams"
    assert float(data["cost_cents"]) >= 0


def assert_venue_invariants(data: dict):
    """Venue-level invariants after any operation."""
    assert data["shortfall_turn_debt_minutes"] >= 0
    assert data["occupancy_freeze"] == (data["status"] == "VENTILATION_HOLD")
    assert data["hood_filter_life_index"] >= 0
    assert float(data["protein_cost_cents"]) >= 0


def assert_reservation_invariants(data: dict):
    """Reservation-level invariants after any operation."""
    assert data["hold_count"] <= 3
    assert data["credit_applied_cents"] >= 0
    if data["status"] == "HELD":
        assert data.get("hold_until") is not None
    if data["status"] in ("CLOSED", "NO_SHOW"):
        assert data.get("hold_until") is None


def assert_zeros(data: dict, *fields):
    for field in fields:
        assert data[field] == 0, f"Expected {field} == 0, got {data[field]}"
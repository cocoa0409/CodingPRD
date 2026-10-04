"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data, msg_prefix=""):
    assert is_valid_uuid(data.get("id", "")), f"{msg_prefix}id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{msg_prefix}created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{msg_prefix}updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{msg_prefix}version must be a positive integer"


def assert_location(data: dict):
    _assert_common(data, "Location: ")
    assert isinstance(data["location_code"], str) and data["location_code"]
    assert isinstance(data["city"], str) and data["city"]
    assert data["geo_zone"] in ["NORTH", "SOUTH", "EAST", "WEST", "CENTRAL"]
    assert isinstance(data["storage_capacity"], int) and data["storage_capacity"] >= 0
    assert data["status"] in ["OPEN", "CLOSED"]


def assert_dealer(data: dict):
    _assert_common(data, "Dealer: ")
    assert isinstance(data["dealer_code"], str) and data["dealer_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert is_valid_uuid(data.get("location_id", ""))
    assert data["status"] in ["ACTIVE", "SUSPENDED", "DEACTIVATED"]
    assert isinstance(data["allocated_unit_count"], int)
    assert isinstance(data["performance_score"], (int, float))


def assert_equipment_unit(data: dict):
    _assert_common(data, "EquipmentUnit: ")
    assert isinstance(data["unit_code"], str) and data["unit_code"]
    assert data["equipment_type"] in [
        "TRUCK_10FT", "TRUCK_15FT", "TRUCK_26FT",
        "TRAILER_4X8", "TRAILER_6X12", "TOW_DOLLY",
    ]
    assert data["status"] in [
        "AVAILABLE", "HELD", "OUT", "REPOSITIONING", "MAINTENANCE", "RETIRED",
    ]


def assert_vehicle_profile(data: dict):
    _assert_common(data, "VehicleProfile: ")
    assert isinstance(data["label"], str) and data["label"]
    assert isinstance(data["year"], int) and data["year"] >= 1980
    assert isinstance(data["curb_weight_lbs"], int) and data["curb_weight_lbs"] >= 1000
    assert isinstance(data["tow_capacity_lbs"], int) and data["tow_capacity_lbs"] >= 0
    assert data["hitch_class"] in ["CLASS_I", "CLASS_II", "CLASS_III", "CLASS_IV", "NONE"]


def assert_customer(data: dict):
    _assert_common(data, "Customer: ")
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert is_valid_uuid(data.get("vehicle_profile_id", ""))
    assert isinstance(data["driver_license_verified"], bool)


def assert_lane_rate(data: dict):
    _assert_common(data, "LaneRate: ")
    assert data["equipment_type"] in [
        "TRUCK_10FT", "TRUCK_15FT", "TRUCK_26FT",
        "TRAILER_4X8", "TRAILER_6X12", "TOW_DOLLY",
    ]
    assert data["season"] in ["PEAK", "SHOULDER", "OFF_PEAK"]
    assert isinstance(data["base_rate_cents"], int) and data["base_rate_cents"] >= 0
    assert isinstance(data["reposition_surcharge_cents"], int)
    assert 0 <= data["commission_rate"] <= 1
    assert data["status"] in ["DRAFT", "ACTIVE", "SUPERSEDED"]


def assert_reservation(data: dict):
    _assert_common(data, "Reservation: ")
    assert data["equipment_type"] in [
        "TRUCK_10FT", "TRUCK_15FT", "TRUCK_26FT",
        "TRAILER_4X8", "TRAILER_6X12", "TOW_DOLLY",
    ]
    assert data["rental_kind"] in ["ROUND_TRIP", "ONE_WAY"]
    assert data["season"] in ["PEAK", "SHOULDER", "OFF_PEAK"]
    assert isinstance(data["rental_days"], int) and data["rental_days"] >= 1
    assert data["status"] in [
        "QUOTED", "CONFIRMED", "REASSIGNED", "FULFILLED",
        "CANCELLED", "EXPIRED", "NO_SHOW",
    ]
    assert data["tow_check_result"] in ["PASS", "FAIL", "NOT_REQUIRED"]
    snapshot = data["price_snapshot"]
    assert isinstance(snapshot, dict)
    assert isinstance(snapshot["quoted_rate_cents_per_day"], int)
    assert isinstance(snapshot["total_quoted_cents"], int)
    assert "applied_imbalance_factor" in snapshot
    assert "commission_rate" in snapshot


def assert_rental_agreement(data: dict):
    _assert_common(data, "RentalAgreement: ")
    assert is_valid_uuid(data.get("reservation_id", ""))
    assert is_valid_uuid(data.get("equipment_unit_id", ""))
    assert data["status"] in ["ACTIVE", "RETURNED", "SETTLED"]
    assert is_iso8601_timestamp(data.get("checkout_at", ""))
    assert isinstance(data["late_fee_cents"], int)
    assert isinstance(data["damage_charge_cents"], int)


def assert_damage_protection_plan(data: dict):
    _assert_common(data, "DamageProtectionPlan: ")
    assert is_valid_uuid(data.get("agreement_id", ""))
    assert data["tier"] in ["BASIC", "STANDARD", "PREMIUM"]
    assert isinstance(data["premium_cents"], int) and data["premium_cents"] >= 0
    assert data["status"] in ["ACTIVE", "EXPIRED", "CANCELLED"]


def assert_damage_claim(data: dict):
    _assert_common(data, "DamageClaim: ")
    assert is_valid_uuid(data.get("agreement_id", ""))
    assert isinstance(data["claimed_amount_cents"], int) and data["claimed_amount_cents"] > 0
    assert data["status"] in ["FILED", "APPROVED", "DENIED", "PAID"]
    assert isinstance(data["filer_user_id"], str) and data["filer_user_id"]


def assert_reposition_task(data: dict):
    _assert_common(data, "RepositionTask: ")
    assert is_valid_uuid(data.get("equipment_unit_id", ""))
    assert is_valid_uuid(data.get("from_location_id", ""))
    assert is_valid_uuid(data.get("to_location_id", ""))
    assert data["status"] in ["OPEN", "ASSIGNED", "COMPLETED", "CANCELLED"]
    assert isinstance(data["estimated_reposition_cost_cents"], int)


def assert_reservation_event(data: dict):
    """Append-only audit row: id + created_at, NO updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "ReservationEvent id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "ReservationEvent created_at must be ISO 8601"
    assert "version" not in data, "ReservationEvent must not carry version"
    assert "updated_at" not in data, "ReservationEvent must not carry updated_at"
    assert data["event_type"] in [
        "CREATED", "CONFIRMED", "REASSIGNED", "CANCELLED", "EXPIRED", "NO_SHOW",
    ]


def assert_cross_sell_order(data: dict):
    _assert_common(data, "CrossSellOrder: ")
    assert is_valid_uuid(data.get("dealer_id", ""))
    assert isinstance(data["line_items"], list)
    assert isinstance(data["storage_months"], int) and data["storage_months"] >= 0
    assert isinstance(data["supplies_subtotal_cents"], int)
    assert isinstance(data["storage_charge_cents"], int)
    assert isinstance(data["bundle_discount_cents"], int)
    assert isinstance(data["total_cents"], int)


def assert_dealer_settlement(data: dict):
    _assert_common(data, "DealerSettlement: ")
    assert is_valid_uuid(data.get("dealer_id", ""))
    assert isinstance(data["period"], str) and data["period"]
    assert data["status"] in ["DRAFT", "APPROVED", "PAID", "DISPUTED"]
    for field in ("gross_rental_cents", "commission_cents",
                  "cross_sell_commission_cents", "clawback_cents", "net_cents"):
        assert isinstance(data[field], int), f"DealerSettlement {field} must be int cents"

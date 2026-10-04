"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)

from .types import (
    Accommodation, AssignmentSource, AssignmentStatus, BagStatus, BoardingGroup,
    BookingStatus, CreditStatus, CrewStatus, DelayCause, JourneyStatus,
    LegStatus, MaintenanceState, PassengerStanding, PairingStatus,
    RedemptionStatus, ReleaseReason, RoutingStatus, StationStatus, StatusTier,
    UpgradeStatus, UpgradeType,
)


def _assert_common(data):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_station(data: dict):
    _assert_common(data)
    assert isinstance(data["iata_code"], str) and data["iata_code"]
    assert isinstance(data["bag_weight_limit_lbs"], int)
    assert isinstance(data["min_connection_minutes"], int)
    assert data["station_status"] in [s.value for s in StationStatus]


def assert_fare_class(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["included_bags"], int)
    assert isinstance(data["change_fee_cents"], int)
    assert isinstance(data["upgrade_discount_pct"], int)
    assert isinstance(data["credit_validity_days"], int)
    assert isinstance(data["preboard_eligible"], bool)
    assert isinstance(data["is_active"], bool)


def assert_passenger(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["status_tier"] in [s.value for s in StatusTier]
    assert isinstance(data["is_min_eligible"], bool)
    assert data["standing"] in [s.value for s in PassengerStanding]
    assert isinstance(data["no_show_count"], int)


def assert_aircraft(data: dict):
    _assert_common(data)
    assert isinstance(data["tail_number"], str) and data["tail_number"]
    assert isinstance(data["seat_count"], int)
    assert data["fleet_type"] == "SINGLE_FLEET"
    assert data["maintenance_state"] in [s.value for s in MaintenanceState]


def assert_crew_member(data: dict):
    _assert_common(data)
    assert isinstance(data["employee_ref"], str) and data["employee_ref"]
    assert data["crew_role"] in ["CAPTAIN", "FIRST_OFFICER", "FLIGHT_ATTENDANT"]
    assert data["qualified_fleet"] == "SINGLE_FLEET"
    assert data["crew_status"] in [s.value for s in CrewStatus]
    assert isinstance(data["base_station_code"], str)


def assert_flight_leg(data: dict):
    _assert_common(data)
    assert isinstance(data["flight_number"], str) and data["flight_number"]
    assert data["leg_status"] in [s.value for s in LegStatus]
    assert isinstance(data["delay_minutes"], int)
    assert data["delay_cause"] in [s.value for s in DelayCause]
    assert isinstance(data["delay_propagated"], bool)
    assert isinstance(data["capacity_seats"], int)
    assert isinstance(data["turn_target_minutes"], int)


def assert_routing(data: dict):
    _assert_common(data)
    assert isinstance(data["routing_date"], str)
    assert isinstance(data["leg_ids"], list)
    assert data["routing_status"] in [s.value for s in RoutingStatus]


def assert_pairing(data: dict):
    _assert_common(data)
    assert isinstance(data["pairing_date"], str)
    assert isinstance(data["leg_ids"], list)
    assert data["pairing_status"] in [s.value for s in PairingStatus]


def assert_booking(data: dict):
    _assert_common(data)
    assert isinstance(data["record_locator"], str) and data["record_locator"]
    assert data["booking_status"] in [s.value for s in BookingStatus]
    assert isinstance(data["journey_count"], int)
    assert isinstance(data["journey_ids"], list)
    assert data["journey_count"] == len(data["journey_ids"])


def assert_journey(data: dict):
    _assert_common(data)
    assert data["journey_status"] in [s.value for s in JourneyStatus]
    assert data["accommodation"] in [s.value for s in Accommodation]
    assert isinstance(data["base_fare_cents"], int)
    assert data["base_fare_cents"] >= 0


def assert_boarding_assignment(data: dict):
    _assert_common(data)
    assert data["boarding_group"] in [s.value for s in BoardingGroup]
    assert isinstance(data["boarding_position"], int)
    assert data["boarding_position"] >= 1
    assert data["assignment_source"] in [s.value for s in AssignmentSource]
    assert data["assignment_status"] in [s.value for s in AssignmentStatus]
    assert data["release_reason"] in [s.value for s in ReleaseReason]


def assert_boarding_upgrade(data: dict):
    _assert_common(data)
    assert data["upgrade_type"] in [s.value for s in UpgradeType]
    assert isinstance(data["price_cents"], int)
    assert data["upgrade_status"] in [s.value for s in UpgradeStatus]


def assert_bag(data: dict):
    _assert_common(data)
    assert isinstance(data["weight_lbs"], int)
    assert data["bag_status"] in [s.value for s in BagStatus]
    assert isinstance(data["bag_fee_cents"], int)


def assert_travel_credit(data: dict):
    _assert_common(data)
    assert isinstance(data["initial_amount_cents"], int)
    assert data["initial_amount_cents"] > 0
    assert isinstance(data["remaining_amount_cents"], int)
    assert 0 <= data["remaining_amount_cents"] <= data["initial_amount_cents"]
    assert data["credit_status"] in [s.value for s in CreditStatus]
    assert isinstance(data["expires_on"], str)


def assert_credit_redemption(data: dict):
    _assert_common(data)
    assert isinstance(data["amount_cents"], int)
    assert data["amount_cents"] > 0
    assert data["redemption_status"] in [s.value for s in RedemptionStatus]


def assert_disruption_event(data: dict):
    _assert_common(data)
    assert data["disruption_type"] in ["DELAY", "CANCELLATION"]
    assert data["cause"] in ["WEATHER", "INBOUND_DELAY", "CREW", "MAINTENANCE"]
    assert isinstance(data["propagation_depth"], int)
    assert is_iso8601_timestamp(data.get("posted_utc", ""))


def assert_credit_balance_invariant(credit: dict, active_redemptions: list):
    """remaining + sum(ACTIVE redemption amounts) == initial, with zero drift."""
    active_total = sum(r["amount_cents"] for r in active_redemptions
                       if r["redemption_status"] == "ACTIVE")
    assert credit["remaining_amount_cents"] + active_total == \
        credit["initial_amount_cents"], (
            "credit balance invariant broken: "
            f"{credit['remaining_amount_cents']} + {active_total} != "
            f"{credit['initial_amount_cents']}")

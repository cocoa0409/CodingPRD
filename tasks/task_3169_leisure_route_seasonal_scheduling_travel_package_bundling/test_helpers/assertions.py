"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AssignmentStatus,
    BookingStatus,
    BundleStatus,
    FlightStatus,
    PublicationStatus,
    PurchaseStatus,
    RoutePosture,
    SettlementStatus,
    WindowStatus,
)


def _assert_common_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}: id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}: created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{label}: updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}: version must be a positive integer"
    )


def assert_station(data: dict):
    _assert_common_fields(data, "Station")
    assert isinstance(data.get("iata_code"), str) and len(data["iata_code"]) == 3
    assert data.get("station_kind") in ("ORIGIN_SMALL_CITY", "LEISURE_DESTINATION")
    assert isinstance(data.get("timezone"), str) and len(data["timezone"]) > 0
    assert isinstance(data.get("single_station_flag"), bool)


def assert_route(data: dict):
    _assert_common_fields(data, "Route")
    assert is_valid_uuid(data.get("origin_station_id", ""))
    assert is_valid_uuid(data.get("destination_station_id", ""))
    assert data.get("route_posture") in [s.value for s in RoutePosture]
    assert isinstance(data.get("base_fare_cents"), int)
    assert isinstance(data.get("weekly_frequency_cap"), int)
    assert isinstance(data.get("suspended_seasons_count"), int)


def assert_season_window(data: dict):
    _assert_common_fields(data, "SeasonWindow")
    assert is_valid_uuid(data.get("route_id", ""))
    assert isinstance(data.get("season_label"), str)
    assert isinstance(data.get("window_start_date"), str)
    assert isinstance(data.get("window_end_date"), str)
    assert data.get("window_status") in [s.value for s in WindowStatus]


def assert_schedule_publication(data: dict):
    _assert_common_fields(data, "SchedulePublication")
    assert is_valid_uuid(data.get("route_id", ""))
    assert is_valid_uuid(data.get("season_window_id", ""))
    assert isinstance(data.get("operating_days_mask"), list)
    for day in data["operating_days_mask"]:
        assert isinstance(day, int) and 1 <= day <= 7
    assert isinstance(data.get("first_operating_date"), str)
    assert isinstance(data.get("last_operating_date"), str)
    assert isinstance(data.get("departure_time_local"), str)
    assert isinstance(data.get("block_minutes"), int)
    assert data.get("publication_status") in [s.value for s in PublicationStatus]


def assert_aircraft(data: dict):
    _assert_common_fields(data, "Aircraft")
    assert isinstance(data.get("tail_number"), str) and len(data["tail_number"]) > 0
    assert isinstance(data.get("seat_capacity"), int) and data["seat_capacity"] > 0
    assert isinstance(data.get("daily_utilization_cap_minutes"), int)
    assert isinstance(data.get("peak_day_cap_minutes"), int)
    assert data["peak_day_cap_minutes"] >= data["daily_utilization_cap_minutes"]
    assert data.get("aircraft_status") in ("IN_SERVICE", "OUT_OF_SERVICE")


def assert_flight_instance(data: dict):
    _assert_common_fields(data, "FlightInstance")
    assert is_valid_uuid(data.get("publication_id", ""))
    assert is_valid_uuid(data.get("route_id", ""))
    assert isinstance(data.get("flight_date"), str)
    assert isinstance(data.get("is_peak_day"), bool)
    assert isinstance(data.get("seats_sold"), int) and data["seats_sold"] >= 0
    assert data.get("flight_status") in [s.value for s in FlightStatus]


def assert_crew_base(data: dict):
    _assert_common_fields(data, "CrewBase")
    assert is_valid_uuid(data.get("base_station_id", ""))
    assert isinstance(data.get("base_code"), str)
    assert data.get("base_status") in ("ACTIVE", "CLOSED")


def assert_crew_member(data: dict):
    _assert_common_fields(data, "CrewMember")
    assert is_valid_uuid(data.get("crew_base_id", ""))
    assert isinstance(data.get("employee_number"), str)
    assert data.get("crew_role") in ("CAPTAIN", "FIRST_OFFICER", "FLIGHT_ATTENDANT")
    assert data.get("member_status") in ("ACTIVE", "FURLOUGHED")


def assert_crew_assignment(data: dict):
    _assert_common_fields(data, "CrewAssignment")
    assert is_valid_uuid(data.get("flight_instance_id", ""))
    assert is_valid_uuid(data.get("crew_member_id", ""))
    assert data.get("assignment_status") in [s.value for s in AssignmentStatus]


def assert_supplier_offer(data: dict):
    _assert_common_fields(data, "SupplierOffer")
    assert isinstance(data.get("supplier_code"), str)
    assert data.get("component_kind") in ("HOTEL", "RENTAL_CAR", "ATTRACTION_TICKET")
    assert is_valid_uuid(data.get("destination_station_id", ""))
    assert isinstance(data.get("net_cost_cents"), int)
    assert isinstance(data.get("sell_price_cents"), int)
    assert data.get("offer_status") in ("OPEN", "WITHDRAWN")


def assert_booking(data: dict):
    _assert_common_fields(data, "Booking")
    assert is_valid_uuid(data.get("flight_instance_id", ""))
    assert isinstance(data.get("passenger_count"), int) and data["passenger_count"] >= 1
    assert data.get("booking_kind") in ("AIR_ONLY", "PACKAGE")
    assert isinstance(data.get("base_fare_total_cents"), int)
    assert isinstance(data.get("ancillary_total_cents"), int)
    assert data.get("booking_status") in [s.value for s in BookingStatus]


def assert_package_bundle(data: dict):
    _assert_common_fields(data, "PackageBundle")
    assert is_valid_uuid(data.get("booking_id", ""))
    assert is_valid_uuid(data.get("hotel_offer_id", ""))
    assert isinstance(data.get("bundle_price_cents"), int)
    assert data.get("bundle_status") in [s.value for s in BundleStatus]


def assert_ancillary_purchase(data: dict):
    _assert_common_fields(data, "AncillaryPurchase")
    assert is_valid_uuid(data.get("booking_id", ""))
    assert data.get("ancillary_kind") in (
        "SEAT_ASSIGNMENT",
        "CHECKED_BAG",
        "CARRY_ON_BAG",
        "PRIORITY_BOARDING",
    )
    assert isinstance(data.get("amount_cents"), int) and data["amount_cents"] > 0
    assert data.get("purchase_status") in [s.value for s in PurchaseStatus]


def assert_disruption_event(data: dict):
    _assert_common_fields(data, "DisruptionEvent")
    assert is_valid_uuid(data.get("route_id", ""))
    assert is_valid_uuid(data.get("flight_instance_id", ""))
    assert data.get("reason_code") in (
        "WEATHER",
        "MAINTENANCE",
        "CREW_SHORTAGE",
        "LOW_DEMAND",
    )
    assert data.get("disruption_status") in ("DECLARED", "RECOVERED")


def assert_supplier_settlement(data: dict):
    _assert_common_fields(data, "SupplierSettlement")
    assert isinstance(data.get("supplier_code"), str)
    assert isinstance(data.get("period_start_date"), str)
    assert isinstance(data.get("period_end_date"), str)
    assert isinstance(data.get("gross_payable_cents"), int)
    assert isinstance(data.get("clawback_cents"), int)
    assert data.get("settlement_status") in [s.value for s in SettlementStatus]

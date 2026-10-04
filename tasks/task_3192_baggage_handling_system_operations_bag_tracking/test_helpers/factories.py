"""Payload factories — one per entity, input fields only."""
from .constants import (
    STATION_SEA, AIRLINE_DL, FLIGHT_DL1423_DEP, MAKEUP_BUFFER_MINUTES,
)


def create_station_payload(**overrides) -> dict:
    defaults = dict(STATION_SEA)
    defaults.update(overrides)
    return defaults


def create_airline_payload(**overrides) -> dict:
    defaults = dict(AIRLINE_DL)
    defaults.update(overrides)
    return defaults


def create_flight_payload(station_id, airline_id, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "airline_id": airline_id,
        "flight_number": "DL1423",
        "bank_code": "B1",
        "scheduled_departure_utc": FLIGHT_DL1423_DEP,
    }
    defaults.update(overrides)
    return defaults


def create_makeup_area_payload(station_id, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "code": "MA-3",
        "capacity_slots": 2,
        "buffer_minutes": MAKEUP_BUFFER_MINUTES,
    }
    defaults.update(overrides)
    return defaults


def create_screening_lane_payload(station_id, **overrides) -> dict:
    defaults = {"station_id": station_id, "lane_code": "EDS-2"}
    defaults.update(overrides)
    return defaults


def create_bag_payload(station_id, **overrides) -> dict:
    defaults = {
        "passenger_name": "Reyes, Ana",
        "passenger_ref": "PNR7X2Q",
        "itinerary_type": "DOMESTIC",
        "weight_lb": 48,
        "length_in": 20,
        "width_in": 14,
        "height_in": 16,
    }
    if station_id is not None:
        defaults["station_id"] = station_id
    defaults.update(overrides)
    return defaults


def create_special_item_payload(**overrides) -> dict:
    defaults = {"item_type": "OVERSIZE", "declared_value_cents": 120000}
    defaults.update(overrides)
    return defaults


def create_connection_payload(bag_id, inbound_flight_id, onward_flight_id, **overrides) -> dict:
    defaults = {
        "bag_id": bag_id,
        "inbound_flight_id": inbound_flight_id,
        "onward_flight_id": onward_flight_id,
        "required_mct_minutes": 75,
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(bag_id, station_id, **overrides) -> dict:
    defaults = {
        "bag_id": bag_id,
        "station_id": station_id,
        "report_type": "DAMAGED",
    }
    defaults.update(overrides)
    return defaults


def create_scan_payload(**overrides) -> dict:
    defaults = {"scan_point": "SORTATION"}
    defaults.update(overrides)
    return defaults


def create_screening_payload(bag_id, lane_id, start_utc, **overrides) -> dict:
    defaults = {"bag_id": bag_id, "lane_id": lane_id, "start_utc": start_utc}
    defaults.update(overrides)
    return defaults


def create_assign_makeup_payload(bag_version, makeup_area_id, induction_utc,
                                 interval_minutes=120, **overrides) -> dict:
    defaults = {
        "expected_bag_version": bag_version,
        "makeup_area_id": makeup_area_id,
        "induction_utc": induction_utc,
        "makeup_interval_minutes": interval_minutes,
    }
    defaults.update(overrides)
    return defaults


def create_bulk_assign_item(bag_id, bag_version, makeup_area_id, induction_utc,
                            interval_minutes=120, **overrides) -> dict:
    """One entry of the bulk-assign `assignments` collection.

    PRD §3.6: "Each item in the batch is validated exactly as the single-bag
    claim is", and the single-bag claim names its target in the path — so the
    batch item carries that same identifier as `bag_id` alongside the claim's
    body fields.
    """
    defaults = create_assign_makeup_payload(bag_version, makeup_area_id,
                                            induction_utc, interval_minutes)
    defaults["bag_id"] = bag_id
    defaults.update(overrides)
    return defaults


def create_arrange_delivery_payload(**overrides) -> dict:
    defaults = {"delivery_method": "COURIER", "scheduled_utc": "2026-09-01T14:20:00Z"}
    defaults.update(overrides)
    return defaults
"""Payload factories — one per entity, input fields only."""
from .constants import (
    AC1_CAPACITY_GRAMS,
    AC1_SCHEDULED_ARRIVAL,
    AC2_SCHEDULED_ARRIVAL,
    BANK_CODE,
    BANK_END,
    BANK_START,
    HUB_WINDOW_CLOSE,
    HUB_WINDOW_OPEN,
    LANE_CAPACITY_STANDARD,
    LANE_CERTIFIED_UNTIL,
    SHIFT_CODE,
    SHIFT_END,
    SHIFT_FORECAST,
    SHIFT_HEADCOUNT,
    SHIFT_PRODUCTIVITY,
    SHIFT_START,
    TEST_DEFAULTS,
)

DEFAULTS = {
    "HUB_IATA": "SDF",
    "HUB_NAME": "Worldport Louisville",
    "ALT_HUB_IATA": "IND",
    "ALT_HUB_NAME": "Indianapolis Gateway",
    "TRACKING_NUMBER": "1Z-TEST-0001",
    "TAIL_NUMBER": "N701UP",
    "ORIGIN_STATION": "LAX",
    "DESTINATION_HUB": "LAX",
    "LANE_CODE": "P-01",
    "FEEDER_CODE": "F-1",
}


def create_hub_payload(**overrides) -> dict:
    payload = {
        "iata_code": DEFAULTS["HUB_IATA"],
        "name": DEFAULTS["HUB_NAME"],
        "sort_window_open_minutes": HUB_WINDOW_OPEN,
        "sort_window_close_minutes": HUB_WINDOW_CLOSE,
    }
    payload.update(overrides)
    return payload


def create_alternate_hub_payload(**overrides) -> dict:
    payload = {
        "iata_code": DEFAULTS["ALT_HUB_IATA"],
        "name": DEFAULTS["ALT_HUB_NAME"],
        "sort_window_open_minutes": HUB_WINDOW_OPEN,
        "sort_window_close_minutes": HUB_WINDOW_CLOSE,
    }
    payload.update(overrides)
    return payload


def create_bank_payload(hub_id: str, **overrides) -> dict:
    payload = {
        "hub_id": hub_id,
        "bank_code": BANK_CODE,
        "scheduled_start_minutes": BANK_START,
        "scheduled_end_minutes": BANK_END,
        "hydraulic_crew_available": True,
    }
    payload.update(overrides)
    return payload


def create_aircraft_payload(bank_id: str, **overrides) -> dict:
    payload = {
        "bank_id": bank_id,
        "tail_number": DEFAULTS["TAIL_NUMBER"],
        "origin_station_code": DEFAULTS["ORIGIN_STATION"],
        "scheduled_arrival_minutes": AC1_SCHEDULED_ARRIVAL,
        "capacity_weight_grams": AC1_CAPACITY_GRAMS,
    }
    payload.update(overrides)
    return payload


def create_package_payload(hub_id: str, aircraft_id: str, **overrides) -> dict:
    payload = {
        "hub_id": hub_id,
        "aircraft_id": aircraft_id,
        "tracking_number": DEFAULTS["TRACKING_NUMBER"],
        "commodity_class": "GENERAL",
        "destination_hub_code": DEFAULTS["DESTINATION_HUB"],
        "service_level": "NEXT_DAY_AIR",
        "planned_weight_grams": TEST_DEFAULTS["PLANNED_WEIGHT_GRAMS"],
        "dimension_weight_grams": TEST_DEFAULTS["DIMENSION_WEIGHT_GRAMS"],
    }
    payload.update(overrides)
    return payload


def create_lane_payload(hub_id: str, **overrides) -> dict:
    payload = {
        "hub_id": hub_id,
        "lane_code": DEFAULTS["LANE_CODE"],
        "lane_kind": "PRIMARY",
        "commodity_capability": "GENERAL",
        "capacity_weight_grams": LANE_CAPACITY_STANDARD,
        "certified_until_minutes": LANE_CERTIFIED_UNTIL,
        "turnout_start_minutes": 1400,
        "turnout_end_minutes": 1500,
    }
    payload.update(overrides)
    return payload


def create_move_payload(hub_id: str, aircraft_id: str, **overrides) -> dict:
    payload = {
        "hub_id": hub_id,
        "aircraft_id": aircraft_id,
        "weight_limit_grams": TEST_DEFAULTS["WEIGHT_LIMIT_GRAMS"],
    }
    payload.update(overrides)
    return payload


def create_buildup_payload(hub_id: str, load_move_id: str, **overrides) -> dict:
    payload = {
        "hub_id": hub_id,
        "load_move_id": load_move_id,
        "destination_gateway_code": DEFAULTS["DESTINATION_HUB"],
        "container_limit_grams": TEST_DEFAULTS["CONTAINER_LIMIT_GRAMS"],
    }
    payload.update(overrides)
    return payload


def create_feeder_payload(hub_id: str, **overrides) -> dict:
    payload = {
        "hub_id": hub_id,
        "feeder_code": DEFAULTS["FEEDER_CODE"],
        "origin_station_code": "LEX",
        "scheduled_departure_minutes": 1420,
        "stage_capacity_grams": 100000,
        "window_minutes": 10,
    }
    payload.update(overrides)
    return payload


def create_shift_payload(hub_id: str, **overrides) -> dict:
    payload = {
        "hub_id": hub_id,
        "shift_code": SHIFT_CODE,
        "start_minutes": SHIFT_START,
        "end_minutes": SHIFT_END,
        "headcount": SHIFT_HEADCOUNT,
        "productivity_grams_per_operator_hour": SHIFT_PRODUCTIVITY,
        "forecast_volume_grams": SHIFT_FORECAST,
        "certified_for_hazmat": True,
    }
    payload.update(overrides)
    return payload


def create_failure_payload(hub_id: str, package_id: str, **overrides) -> dict:
    payload = {
        "hub_id": hub_id,
        "package_id": package_id,
        "cause_code": "SORT_MISS",
        "failure_minutes": 1500,
    }
    payload.update(overrides)
    return payload


def create_claim_payload(**overrides) -> dict:
    payload = {"outcome": "FINALIZED", "note": "test claim"}
    payload.update(overrides)
    return payload


def create_ops_run_payload(**overrides) -> dict:
    payload = {"minute_of_day": 1400, "level": "MAJOR"}
    payload.update(overrides)
    return payload
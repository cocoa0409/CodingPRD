"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_network_payload(**overrides) -> dict:
    defaults = {"network_code": "NET-1", "display_name": "Test Network"}
    defaults.update(overrides)
    return defaults


def create_hub_payload(**overrides) -> dict:
    defaults = {
        "hub_code": "HUB-1",
        "daily_capacity_dozens": TEST_DEFAULTS["HUB_CAPACITY_DOZENS"],
        "territory_region": TEST_DEFAULTS["REGION"],
    }
    defaults.update(overrides)
    return defaults


def create_line_payload(**overrides) -> dict:
    defaults = {
        "line_kind": "CONTINUOUS_FRYER",
        "rated_dozens_per_hour": TEST_DEFAULTS["LINE_RATED_DOZENS_PER_HOUR"],
        "service_interval_hours": TEST_DEFAULTS["LINE_SERVICE_INTERVAL_HOURS"],
    }
    defaults.update(overrides)
    return defaults


def create_door_payload(**overrides) -> dict:
    defaults = {
        "door_kind": "THEATER",
        "ownership": "COMPANY",
        "territory_region": TEST_DEFAULTS["REGION"],
    }
    defaults.update(overrides)
    return defaults


def create_variety_payload(**overrides) -> dict:
    defaults = {
        "variety_code": "GLAZED",
        "collection_kind": "CORE",
        "active_from": TEST_DEFAULTS["VARIETY_ACTIVE_FROM"],
        "active_until": TEST_DEFAULTS["VARIETY_ACTIVE_UNTIL"],
        "unit_cost_cents": 80,
    }
    defaults.update(overrides)
    return defaults


def create_mix_plan_payload(**overrides) -> dict:
    defaults = {"effective_date": TEST_DEFAULTS["PRODUCTION_DATE"]}
    defaults.update(overrides)
    return defaults


def create_mix_plan_line_payload(**overrides) -> dict:
    defaults = {"variety_id": "", "planned_dozens": 10}
    defaults.update(overrides)
    return defaults


def create_batch_payload(**overrides) -> dict:
    defaults = {
        "equipment_line_id": "",
        "production_date": TEST_DEFAULTS["PRODUCTION_DATE"],
        "planned_dozens": 50,
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(**overrides) -> dict:
    defaults = {
        "route_code": "RT-1",
        "service_date": TEST_DEFAULTS["PRODUCTION_DATE"],
        "vehicle_capacity_dozens": TEST_DEFAULTS["VEHICLE_CAPACITY_DOZENS"],
    }
    defaults.update(overrides)
    return defaults


def create_route_stop_payload(**overrides) -> dict:
    defaults = {
        "door_id": "",
        "sequence_no": 1,
        "window_start": "2026-09-01T08:00:00Z",
        "window_end": "2026-09-01T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(**overrides) -> dict:
    defaults = {"production_batch_id": "", "dozens_shipped": 10}
    defaults.update(overrides)
    return defaults


def create_stale_credit_payload(**overrides) -> dict:
    defaults = {"shipment_id": "", "pulled_dozens": 5}
    defaults.update(overrides)
    return defaults


def create_fundraiser_order_payload(**overrides) -> dict:
    defaults = {
        "organization_name": "Test Org",
        "requested_dozens": 10,
        "pickup_at": "2026-09-03T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_hot_light_window_payload(**overrides) -> dict:
    defaults = {
        "lit_start": "2026-09-01T06:00:00Z",
        "lit_end": "2026-09-01T08:00:00Z",
    }
    defaults.update(overrides)
    return defaults

"""Payload factories — one per resource, required input fields only.

Every factory returns a fresh dict so callers can mutate it freely; pass
``**overrides`` to steer any single field.  Optional fields with a declared
server-side default are omitted by default so a test that cares about the
default can prove it.
"""

from . import constants as c

DEFAULTS = {
    "TERRITORY_NAME": "Phoenix Metro",
    "REGION_CODE": "PHX-METRO",
    "DEPOT_NAME": "Depot A",
    "VIN": "VIN-0001",
    "SOFTWARE_VERSION": "sw-2026.1",
    "TARGET_SOFTWARE_VERSION": "sw-2026.1",
    "RIDER_NAME": "Rider One",
    "TEAM_CODE": "T-ARTERIAL-1",
    "CURB_SEGMENT_CODE": "CURB-A1",
    "INCIDENT_DESCRIPTION": "Curb contact, no structural damage",
}

# Depot with eight bay positions split evenly across the four service kinds.
DEPOT_TOTAL_8 = {
    "charge_positions": 2,
    "cleaning_positions": 2,
    "calib_positions": 2,
    "software_positions": 2,
}


def create_territory_payload(**overrides):
    """ServiceTerritory create body. mapped_pct/validation_hours/road_type_risk
    are optional at creation; omit them to exercise the declared defaults."""
    payload = {"name": DEFAULTS["TERRITORY_NAME"], "region_code": DEFAULTS["REGION_CODE"]}
    payload.update(overrides)
    return payload


def create_active_territory_payload(**overrides):
    """Territory that satisfies the ACTIVE posture gates as supplied."""
    payload = {
        "name": DEFAULTS["TERRITORY_NAME"],
        "region_code": DEFAULTS["REGION_CODE"],
        "mapped_pct": 100,
        "validation_hours": 120,
        "road_type_risk": "LOW",
    }
    payload.update(overrides)
    return payload


def create_depot_payload(**overrides):
    payload = {"name": DEFAULTS["DEPOT_NAME"]}
    payload.update(DEPOT_TOTAL_8)
    payload.update(overrides)
    return payload


def create_vehicle_payload(**overrides):
    """Vehicle registration body. cleanliness_score and calib_valid are
    optional; they are omitted by default so the declared defaults surface."""
    payload = {
        "vin": DEFAULTS["VIN"],
        "battery_pct": 90,
        "software_version": DEFAULTS["SOFTWARE_VERSION"],
        "target_software_version": DEFAULTS["TARGET_SOFTWARE_VERSION"],
    }
    payload.update(overrides)
    return payload


def create_service_ready_vehicle_payload(**overrides):
    """A vehicle that satisfies all four readiness predicates outright."""
    payload = {
        "vin": DEFAULTS["VIN"],
        "battery_pct": 90,
        "cleanliness_score": 90,
        "calib_valid": True,
        "software_version": DEFAULTS["SOFTWARE_VERSION"],
        "target_software_version": DEFAULTS["TARGET_SOFTWARE_VERSION"],
    }
    payload.update(overrides)
    return payload


def create_bay_slot_payload(**overrides):
    payload = {
        "service_type": c.KIND_CHARGE,
        "bay_index": 1,
        "start_utc": c.BASE_INSTANT,
        "duration_seconds": 1800,
        "vehicle_id": None,
        "cycle_id": None,
    }
    payload.update(overrides)
    return payload


def create_cycle_payload(**overrides):
    payload = {"vehicle_id": None, "service_kind": c.KIND_CHARGE}
    payload.update(overrides)
    return payload


def create_demand_signal_payload(**overrides):
    payload = {"window_code": c.WINDOW_MIDDAY, "projected_rides": 40, "manual_only_rides": 10}
    payload.update(overrides)
    return payload


def create_wave_payload(**overrides):
    payload = {"window_code": c.WINDOW_MIDDAY, "planned_vehicle_count": 1}
    payload.update(overrides)
    return payload


def create_area_rule_payload(**overrides):
    payload = {"route_class": c.ROUTE_ARTERIAL, "allowed": True}
    payload.update(overrides)
    return payload


def create_exclusion_zone_payload(**overrides):
    payload = {
        "kind": "CONSTRUCTION",
        "route_class": c.ROUTE_FREEWAY,
        "start_utc": c.BASE_INSTANT,
        "duration_seconds": 86400,
    }
    payload.update(overrides)
    return payload


def create_expansion_request_payload(**overrides):
    payload = {"target_region_code": "PHX-NORTH", "expected_territory_version": 1}
    payload.update(overrides)
    return payload


def create_ride_payload(**overrides):
    payload = {
        "rider_name": DEFAULTS["RIDER_NAME"],
        "sub_service_type": c.SUB_SERVICE_STANDARD,
        "idempotency_key": "idem-1",
    }
    payload.update(overrides)
    return payload


def create_pickup_location_payload(**overrides):
    payload = {"curb_segment_code": DEFAULTS["CURB_SEGMENT_CODE"], "curb_access": c.CURB_SAFE}
    payload.update(overrides)
    return payload


def create_curb_rule_payload(**overrides):
    payload = {
        "curb_access": c.CURB_SAFE,
        "sub_service_type": c.SUB_SERVICE_STANDARD,
        "allowed": True,
    }
    payload.update(overrides)
    return payload


def create_assistance_session_payload(**overrides):
    payload = {"reason": "STUCK"}
    payload.update(overrides)
    return payload


def create_incident_payload(**overrides):
    payload = {"severity": "MINOR", "description": DEFAULTS["INCIDENT_DESCRIPTION"]}
    payload.update(overrides)
    return payload


def create_roadside_team_payload(**overrides):
    payload = {"team_code": DEFAULTS["TEAM_CODE"], "road_class": c.ROUTE_ARTERIAL}
    payload.update(overrides)
    return payload


def create_roadside_case_payload(**overrides):
    payload = {"road_class": c.ROUTE_ARTERIAL}
    payload.update(overrides)
    return payload
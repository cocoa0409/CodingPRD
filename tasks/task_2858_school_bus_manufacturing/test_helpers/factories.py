"""Payload factories — one per resource, carrying only client-supplied fields."""

from typing import List, Optional

# --------------------------------------------------------------------------
# Catalogue
# --------------------------------------------------------------------------
def bus_model_payload(**overrides) -> dict:
    """A conventional Type C body: 71 seats, five exits, 58.0 kN joints."""
    payload = {
        "model_code": "TYPE_C_CONV",
        "body_class": "TYPE_C",
        "base_seat_capacity": 71,
        "base_emergency_exit_count": 5,
        "base_price_cents": 12_750_000,
        "body_joint_strength_kn": 58.0,
        "max_battery_bays": 6,
        "curb_weight_lb": 21_500,
    }
    payload.update(overrides)
    return payload


def type_a_mini_model_payload(**overrides) -> dict:
    variant = {
        "model_code": "TYPE_A_MINI",
        "body_class": "TYPE_A",
        "base_seat_capacity": 24,
        "base_emergency_exit_count": 3,
        "base_price_cents": 5_800_000,
        "body_joint_strength_kn": 40.0,
        "max_battery_bays": 3,
        "curb_weight_lb": 12_000,
    }
    variant.update(overrides)
    return bus_model_payload(**variant)


def type_c_alt_model_payload(**overrides) -> dict:
    variant = {
        "model_code": "TYPE_C_ALT",
        "body_class": "TYPE_C",
        "base_seat_capacity": 77,
        "base_emergency_exit_count": 6,
        "base_price_cents": 13_400_000,
        "body_joint_strength_kn": 60.0,
        "max_battery_bays": 6,
        "curb_weight_lb": 22_400,
    }
    variant.update(overrides)
    return bus_model_payload(**variant)


def type_d_transit_model_payload(**overrides) -> dict:
    variant = {
        "model_code": "TYPE_D_TRANSIT",
        "body_class": "TYPE_D",
        "base_seat_capacity": 84,
        "base_emergency_exit_count": 6,
        "base_price_cents": 16_400_000,
        "body_joint_strength_kn": 66.0,
        "max_battery_bays": 8,
        "curb_weight_lb": 26_800,
    }
    variant.update(overrides)
    return bus_model_payload(**variant)


def electric_package_payload(compatible_bus_model_id: str, **overrides) -> dict:
    """155 kWh electric package: the PRD's worked range example."""
    payload = {
        "package_code": "ELEC-155",
        "compatible_bus_model_id": compatible_bus_model_id,
        "propulsion_type": "ELECTRIC",
        "option_price_cents": 14_900_000,
        "cold_weather_derate_pct": 0.12,
        "reserve_floor_pct": 0.10,
        "battery_pack_count": 4,
        "usable_kwh": 155.0,
        "nominal_consumption_kwh_per_mi": 1.05,
        "hvac_load_kw": 7.5,
    }
    payload.update(overrides)
    return payload


def diesel_package_payload(compatible_bus_model_id: str, **overrides) -> dict:
    """100 gallon diesel package at 7.2 mpg."""
    payload = {
        "package_code": "DSL-100",
        "compatible_bus_model_id": compatible_bus_model_id,
        "propulsion_type": "DIESEL",
        "option_price_cents": 1_250_000,
        "cold_weather_derate_pct": 0.03,
        "reserve_floor_pct": 0.05,
        "fuel_capacity_gal": 100.0,
        "rated_mpg": 7.2,
    }
    payload.update(overrides)
    return payload


def propane_package_payload(compatible_bus_model_id: str, **overrides) -> dict:
    variant = {
        "package_code": "PROP-98",
        "propulsion_type": "PROPANE",
        "option_price_cents": 2_950_000,
        "cold_weather_derate_pct": 0.04,
        "reserve_floor_pct": 0.05,
        "fuel_capacity_gal": 98.0,
        "rated_mpg": 5.4,
    }
    variant.update(overrides)
    return diesel_package_payload(compatible_bus_model_id, **variant)


def mini_diesel_package_payload(compatible_bus_model_id: str, **overrides) -> dict:
    variant = {
        "package_code": "MINI-DSL-40",
        "option_price_cents": 100_000,
        "fuel_capacity_gal": 40.0,
        "rated_mpg": 9.0,
    }
    variant.update(overrides)
    return diesel_package_payload(compatible_bus_model_id, **variant)


# --------------------------------------------------------------------------
# Specification profiles
# --------------------------------------------------------------------------
def spec_profile_payload(**overrides) -> dict:
    """A profile carrying only the six mandatory inputs, so the seven optional
    fields take their stated defaults."""
    payload = {
        "state_code": "OK",
        "school_year": "2026-2027",
        "min_seat_capacity": 24,
        "min_emergency_exit_count": 3,
        "min_joint_strength_kn": 35.0,
        "required_route_range_mi": 300.0,
    }
    payload.update(overrides)
    return payload


def tx_profile_payload(**overrides) -> dict:
    """Texas: flat terrain, crossview mirrors, a 400 mile route requirement."""
    payload = {
        "state_code": "TX",
        "school_year": "2026-2027",
        "min_seat_capacity": 71,
        "min_emergency_exit_count": 5,
        "min_joint_strength_kn": 55.0,
        "required_route_range_mi": 400.0,
        "requires_eight_lamp_system": True,
        "requires_crossing_arm": True,
        "required_mirror_config": "CROSSVIEW",
        "terrain_class": "FLAT",
    }
    payload.update(overrides)
    return payload


def ca_profile_payload(**overrides) -> dict:
    """California: every optional mandate switched on, rolling terrain."""
    payload = {
        "state_code": "CA",
        "school_year": "2026-2027",
        "min_seat_capacity": 78,
        "min_emergency_exit_count": 6,
        "min_joint_strength_kn": 62.5,
        "required_route_range_mi": 75.0,
        "requires_eight_lamp_system": True,
        "requires_crossing_arm": True,
        "required_mirror_config": "CROSSVIEW_HEATED",
        "requires_lap_shoulder_belts": True,
        "requires_rollover_protection": True,
        "requires_joint_strength_test": True,
        "terrain_class": "ROLLING",
    }
    payload.update(overrides)
    return payload


def nv_profile_payload(**overrides) -> dict:
    """Nevada: a short 75 mile route requirement, flat by default."""
    payload = {
        "state_code": "NV",
        "school_year": "2026-2027",
        "min_seat_capacity": 71,
        "min_emergency_exit_count": 5,
        "min_joint_strength_kn": 55.0,
        "required_route_range_mi": 75.0,
        "terrain_class": "FLAT",
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Solicitations and bids
# --------------------------------------------------------------------------
def solicitation_payload(spec_profile_id: str, **overrides) -> dict:
    payload = {
        "solicitation_code": "SOL-001",
        "buyer_type": "DISTRICT",
        "buyer_name": "Plano ISD",
        "spec_profile_id": spec_profile_id,
        "unit_count": 1,
        "required_delivery_date": "2026-12-01",
        "price_cap_cents_per_unit": 40_000_000,
    }
    payload.update(overrides)
    return payload


def bid_payload(solicitation_id: str, bus_model_id: str, propulsion_package_id: str,
                **overrides) -> dict:
    """A base-configuration bid: no options beyond the body's own equipment."""
    payload = {
        "solicitation_id": solicitation_id,
        "bus_model_id": bus_model_id,
        "propulsion_package_id": propulsion_package_id,
        "unit_count": 1,
        "offered_seat_capacity": 71,
        "offered_emergency_exit_count": 5,
        "offered_mirror_config": "STANDARD",
        "offered_lap_shoulder_belts": False,
        "offered_eight_lamp_system": False,
        "offered_crossing_arm": False,
        "offered_rollover_reinforcement": False,
    }
    payload.update(overrides)
    return payload


def bid_revision_payload(expected_bid_version: int, **overrides) -> dict:
    payload = {
        "expected_bid_version": expected_bid_version,
        "offered_seat_capacity": 71,
        "offered_emergency_exit_count": 5,
        "offered_mirror_config": "STANDARD",
        "offered_lap_shoulder_belts": False,
        "offered_eight_lamp_system": False,
        "offered_crossing_arm": False,
        "offered_rollover_reinforcement": False,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Plant
# --------------------------------------------------------------------------
def production_line_payload(**overrides) -> dict:
    payload = {
        "line_code": "L-A1",
        "plant_code": "PLANT-A",
        "supported_body_classes": ["TYPE_C", "TYPE_D"],
        "horizon_slot_day_capacity": 30,
        "changeover_buffer_days": 3,
    }
    payload.update(overrides)
    return payload


def build_slot_payload(expected_production_line_version: int, production_line_id: str,
                       bus_unit_id: str, start_date: str, end_date: str,
                       **overrides) -> dict:
    payload = {
        "expected_production_line_version": expected_production_line_version,
        "production_line_id": production_line_id,
        "bus_unit_id": bus_unit_id,
        "start_date": start_date,
        "end_date": end_date,
    }
    payload.update(overrides)
    return payload


def test_bay_payload(**overrides) -> dict:
    payload = {
        "bay_code": "TB-1",
        "plant_code": "PLANT-A",
        "supported_test_types": [
            "BRAKE", "EMERGENCY_EXIT", "ELECTRICAL", "JOINT_STRENGTH", "ROLLOVER",
        ],
        "max_concurrent_electrical": 2,
    }
    payload.update(overrides)
    return payload


def quality_test_payload(bus_unit_id: str, test_bay_id: str, test_type: str,
                         window_start: str, window_end: str, **overrides) -> dict:
    payload = {
        "bus_unit_id": bus_unit_id,
        "test_bay_id": test_bay_id,
        "test_type": test_type,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def record_result_payload(outcome: str, measured_value: Optional[float] = None,
                          result_notes: Optional[str] = None, **overrides) -> dict:
    payload = {"outcome": outcome}
    if measured_value is not None:
        payload["measured_value"] = measured_value
    if result_notes is not None:
        payload["result_notes"] = result_notes
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Delivery network and recalls
# --------------------------------------------------------------------------
def dealer_payload(**overrides) -> dict:
    payload = {
        "dealer_code": "D-TX-01",
        "dealer_name": "Lone Star Bus Sales",
        "licensed_state_codes": ["TX", "OK"],
        "training_capacity_per_month": 20,
    }
    payload.update(overrides)
    return payload


def legacy_fleet_record_payload(bus_model_id: str, propulsion_package_id: str,
                                spec_profile_id: str, vin: str,
                                delivered_at: str, **overrides) -> dict:
    """`delivered_at` is an ISO-8601 UTC instant, compared against the clock."""
    payload = {
        "bus_model_id": bus_model_id,
        "propulsion_package_id": propulsion_package_id,
        "spec_profile_id": spec_profile_id,
        "vin": vin,
        "delivered_at": delivered_at,
    }
    payload.update(overrides)
    return payload


def recall_campaign_payload(affected_bus_model_id: str, **overrides) -> dict:
    payload = {
        "campaign_code": "RC-DSL-01",
        "affected_bus_model_id": affected_bus_model_id,
        "affected_propulsion_type": "DIESEL",
        "defect_category": "BRAKE_LINE_CORROSION",
        "build_window_start": "2026-01-01",
        "build_window_end": "2026-07-31",
        "kits_per_unit": 1,
        "total_kits": 5,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Convenience
# --------------------------------------------------------------------------
def instant(date_str: str) -> str:
    """Render a calendar date as the midnight UTC instant the API expects."""
    return f"{date_str}T00:00:00Z"


def vins(prefix: str, count: int, start: int = 1) -> List[str]:
    """A run of distinct vehicle identification numbers."""
    return [f"{prefix}{start + i:04d}" for i in range(count)]

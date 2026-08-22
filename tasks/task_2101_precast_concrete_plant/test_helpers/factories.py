"""Payload factories -- one per entity, client-supplied input fields only."""

from .constants import (
    CURE_END,
    CURE_START,
    MEASURED_ELONGATION_IN,
    RUN_END,
    RUN_START,
)

DEFAULTS = {
    "PROJECT_NAME": "Riverfront Garage",
    "JOBSITE_CITY": "Nashville",
    "ERECTION_START_DATE": "2026-09-15",
    "MIX_CODE": "M40-STD",
    "ZONE_CODE": "Z1",
    "BED_CODE": "B1",
    "SLOT_CODE": "S1",
    "PIECE_MARK": "DT-101",
    "PERMIT_NUMBER": "TN-8891",
}


def create_project_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["PROJECT_NAME"],
        "jobsite_city": DEFAULTS["JOBSITE_CITY"],
        "erection_start_date": DEFAULTS["ERECTION_START_DATE"],
    }
    payload.update(overrides)
    return payload


def create_mix_design_payload(**overrides) -> dict:
    """The canonical C40 plant mix: 6000 psi at 28 days, releasing at 3500 psi."""
    payload = {
        "code": DEFAULTS["MIX_CODE"],
        "strength_class": "C40",
        "design_28day_psi": 6000,
        "required_release_psi": 3500,
        "w_c_ratio": 0.38,
        "cement_lb_per_cy": 705,
        "unit_cost_cents_per_cy": 14500,
    }
    payload.update(overrides)
    return payload


def create_high_performance_mix_payload(**overrides) -> dict:
    """The canonical C60 plant mix, whose strength class shifts the tensioning
    arithmetic away from the C40 answer."""
    payload = {
        "code": "M60-HP",
        "strength_class": "C60",
        "design_28day_psi": 9000,
        "required_release_psi": 4500,
        "w_c_ratio": 0.32,
        "cement_lb_per_cy": 800,
        "unit_cost_cents_per_cy": 19200,
    }
    payload.update(overrides)
    return payload


def create_steam_zone_payload(**overrides) -> dict:
    payload = {
        "zone_code": DEFAULTS["ZONE_CODE"],
        "boiler_capacity_bhp": 100,
        "therm_rate_cents_per_therm": 95,
    }
    payload.update(overrides)
    return payload


def create_casting_bed_payload(steam_zone_id: str, **overrides) -> dict:
    payload = {
        "bed_code": DEFAULTS["BED_CODE"],
        "steam_zone_id": steam_zone_id,
        "bed_type": "LONG_LINE_PRESTRESS",
        "length_ft": 400,
        "max_strand_force_kips": 900,
        "turnaround_buffer_hours": 6,
    }
    payload.update(overrides)
    return payload


def create_yard_slot_payload(**overrides) -> dict:
    payload = {
        "slot_code": DEFAULTS["SLOT_CODE"],
        "bay_code": "A",
        "capacity_weight_lb": 120000,
        "max_stack_count": 3,
    }
    payload.update(overrides)
    return payload


def create_bed_run_payload(bed_id: str, mix_design_id: str, **overrides) -> dict:
    payload = {
        "bed_id": bed_id,
        "mix_design_id": mix_design_id,
        "scheduled_start": RUN_START,
        "scheduled_end": RUN_END,
    }
    payload.update(overrides)
    return payload


def create_piece_payload(project_id: str, mix_design_id: str, **overrides) -> dict:
    """The canonical oversize double tee: 53.10 x 9.50 x 13.70 ft at 48200 lb."""
    payload = {
        "project_id": project_id,
        "mix_design_id": mix_design_id,
        "piece_mark": DEFAULTS["PIECE_MARK"],
        "erection_sequence_no": 10,
        "length_ft": 53.10,
        "width_ft": 9.50,
        "height_ft": 13.70,
        "weight_lb": 48200,
        "concrete_volume_cy": 12.50,
    }
    payload.update(overrides)
    return payload


def create_legal_piece_payload(project_id: str, mix_design_id: str, **overrides) -> dict:
    """A piece exactly on every legal limit: 53.00 x 8.50 x 13.50 ft at 22000 lb."""
    payload = {
        "project_id": project_id,
        "mix_design_id": mix_design_id,
        "piece_mark": "LEGAL-1",
        "erection_sequence_no": 10,
        "length_ft": 53.00,
        "width_ft": 8.50,
        "height_ft": 13.50,
        "weight_lb": 22000,
        "concrete_volume_cy": 8.00,
    }
    payload.update(overrides)
    return payload


def tension_payload(**overrides) -> dict:
    payload = {
        "strand_count": 24,
        "strand_diameter_in": 0.500,
        "measured_elongation_in": MEASURED_ELONGATION_IN,
    }
    payload.update(overrides)
    return payload


def create_cylinder_set_payload(**overrides) -> dict:
    payload = {"purpose": "RELEASE", "specimen_count": 2, "cured_with_member": True}
    payload.update(overrides)
    return payload


def cylinder_break_payload(load_lbf: float, **overrides) -> dict:
    payload = {"load_lbf": load_lbf, "diameter_in": 4.00}
    payload.update(overrides)
    return payload


def create_curing_cycle_payload(steam_zone_id: str, **overrides) -> dict:
    """A 40 bhp cycle soaking at 150 F for 8 h with a 30 F/hr ramp."""
    payload = {
        "steam_zone_id": steam_zone_id,
        "planned_start": CURE_START,
        "planned_end": CURE_END,
        "ramp_rate_f_per_hr": 30,
        "soak_temp_f": 150,
        "soak_hours": 8,
        "steam_demand_bhp": 40,
    }
    payload.update(overrides)
    return payload


def create_yard_placement_payload(
    piece_id: str, yard_slot_id: str, expected_yard_slot_version: int, **overrides
) -> dict:
    payload = {
        "piece_id": piece_id,
        "yard_slot_id": yard_slot_id,
        "stack_level": 1,
        "expected_yard_slot_version": expected_yard_slot_version,
    }
    payload.update(overrides)
    return payload


def create_haul_permit_payload(project_id: str, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "permit_number": DEFAULTS["PERMIT_NUMBER"],
        "issuing_state": "TN",
        "max_width_ft": 10.00,
        "max_height_ft": 14.00,
        "max_length_ft": 60.00,
        "max_gross_weight_lb": 140000,
        "valid_from": "2026-08-01T00:00:00Z",
        "valid_to": "2026-08-31T00:00:00Z",
        "escort_count": 1,
    }
    payload.update(overrides)
    return payload


def create_shipment_payload(project_id: str, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "scheduled_departure": "2026-08-04T13:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_shipment_line_payload(piece_id: str, load_position: int, **overrides) -> dict:
    payload = {"piece_id": piece_id, "load_position": load_position}
    payload.update(overrides)
    return payload


def create_repair_disposition_payload(
    piece_id: str, expected_piece_version: int, **overrides
) -> dict:
    payload = {
        "piece_id": piece_id,
        "defect_type": "SPALL",
        "severity": "MINOR",
        "description": "Edge spall at south bearing",
        "expected_piece_version": expected_piece_version,
    }
    payload.update(overrides)
    return payload

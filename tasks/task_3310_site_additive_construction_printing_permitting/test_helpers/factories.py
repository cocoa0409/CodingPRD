"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_jurisdiction_payload(**overrides) -> dict:
    defaults = {
        "code": "TEST-JUR",
        "name": "Test Jurisdiction",
        "permits_prescriptive_printed_path": True,
        "alternative_means_review_days": TEST_DEFAULTS["AM_REVIEW_DAYS"],
        "weather_station_id": "WX-TEST",
    }
    defaults.update(overrides)
    return defaults


def create_site_payload(jurisdiction_id, **overrides) -> dict:
    defaults = {
        "jurisdiction_id": jurisdiction_id,
        "address": "1 Test Way",
        "soil_class": "A",
        "foundation_kind": "SLAB",
    }
    defaults.update(overrides)
    return defaults


def create_community_deployment_payload(jurisdiction_id, plan_id, **overrides) -> dict:
    defaults = {
        "name": "Test Deployment",
        "jurisdiction_id": jurisdiction_id,
        "plan_id": plan_id,
        "planned_unit_count": 5,
    }
    defaults.update(overrides)
    return defaults


def create_structural_plan_payload(**overrides) -> dict:
    defaults = {
        "title": "Test Plan",
        "structural_system": "PRINTED_WALL",
        "wall_thickness_mm": TEST_DEFAULTS["WALL_THICKNESS_MM"],
        "wall_height_mm": TEST_DEFAULTS["WALL_HEIGHT_MM"],
        "plan_area_m2": TEST_DEFAULTS["PLAN_AREA_M2"],
    }
    defaults.update(overrides)
    return defaults


def create_plan_revision_payload(**overrides) -> dict:
    defaults = {
        "engineering_notes": "Initial revision",
        "required_code_path": "PRESCRIPTIVE",
    }
    defaults.update(overrides)
    return defaults


def create_permit_application_payload(plan_revision_id, **overrides) -> dict:
    defaults = {
        "plan_revision_id": plan_revision_id,
        "requested_path": "PRESCRIPTIVE",
    }
    defaults.update(overrides)
    return defaults


def create_printer_setup_payload(expected_site_version, **overrides) -> dict:
    defaults = {
        "gantry_model": "VULCAN_II",
        "rail_span_mm": TEST_DEFAULTS["RAIL_SPAN_MM"],
        "leveling_tolerance_mm": TEST_DEFAULTS["LEVELING_TOLERANCE_MM"],
        "measured_level_deviation_mm": TEST_DEFAULTS["MEASURED_DEVIATION_MM"],
        "expected_site_version": expected_site_version,
    }
    defaults.update(overrides)
    return defaults


def create_material_batch_payload(**overrides) -> dict:
    defaults = {
        "mix_code": "LAVACRETE_A",
        "water_cement_ratio": 0.45,
        "target_slump_mm": TEST_DEFAULTS["TARGET_SLUMP_MM"],
        "measured_slump_mm": TEST_DEFAULTS["TARGET_SLUMP_MM"],
        "pump_consistency_kg_per_min": 50,
    }
    defaults.update(overrides)
    return defaults


def create_weather_observation_payload(observed_at, **overrides) -> dict:
    """Defaults describe fully print-permissible weather (PRD §3.6)."""
    defaults = {
        "observed_at": observed_at,
        "air_temp_c": 22.0,
        "relative_humidity_pct": 50.0,
        "wind_speed_mps": 3.0,
        "precipitation_mm": 0,
    }
    defaults.update(overrides)
    return defaults


def create_print_job_payload(plan_revision_id, printer_setup_id, expected_site_version, **overrides) -> dict:
    defaults = {
        "plan_revision_id": plan_revision_id,
        "printer_setup_id": printer_setup_id,
        "scheduled_start_at": "2026-09-04T08:00:00Z",
        "scheduled_end_at": "2026-09-04T16:00:00Z",
        "total_layers_planned": TEST_DEFAULTS["TOTAL_LAYERS_PLANNED"],
        "expected_site_version": expected_site_version,
    }
    defaults.update(overrides)
    return defaults


def create_layer_inspection_payload(**overrides) -> dict:
    defaults = {
        "layer_index_start": 1,
        "layer_index_end": 5,
        "bond_strength_mpa": 2.0,
        "dimensional_deviation_mm": 4,
    }
    defaults.update(overrides)
    return defaults


def create_trade_task_payload(depends_on_print_job_id, expected_site_version, **overrides) -> dict:
    defaults = {
        "trade": "ROOF",
        "sequence_rank": 1,
        "earliest_start_at": "2026-09-06T08:00:00Z",
        "latest_end_at": "2026-09-10T16:00:00Z",
        "depends_on_print_job_id": depends_on_print_job_id,
        "expected_site_version": expected_site_version,
    }
    defaults.update(overrides)
    return defaults

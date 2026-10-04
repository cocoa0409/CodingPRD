"""Payload factories — one per creatable resource, input fields only.

Defaults mirror the canonical fixture chain (PRD §3/§4 values); every field
is overridable via **overrides. Fields the server assigns (ids, status,
computed values, accountability stamps) are never part of these payloads.
"""
from .constants import FIXTURE_CLOCK_START


def create_site_payload(**overrides) -> dict:
    defaults = {
        "name": "Providence Biologics",
        "region": "US-RI",
        "monthly_capacity_hours": 5000,
        "cold_storage_capacity_units": 10000000,
        "licensed_authorities": ["FDA", "EMA"],
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "product_code": "MAB-001",
        "molecule_type": "MONOCLONAL_ANTIBODY",
        "market_scope": "BOTH",
        "requires_cold_chain": True,
        "min_storage_temp_c": 2.0,
        "max_storage_temp_c": 8.0,
        "shelf_life_hours": 2160,
        "changeover_hours": 14,
        "same_product_turnaround_hours": 6,
        "required_materials": [],
    }
    defaults.update(overrides)
    return defaults


def create_train_payload(**overrides) -> dict:
    defaults = {
        "train_code": "TR-1",
        "capacity_liters": 2000,
        "supported_molecule_types": ["MONOCLONAL_ANTIBODY"],
    }
    defaults.update(overrides)
    return defaults


def create_material_payload(**overrides) -> dict:
    defaults = {
        "material_name": "MEDIA-X",
        "is_single_source": False,
        "quantity": 100,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(**overrides) -> dict:
    defaults = {"authority": "FDA"}
    defaults.update(overrides)
    return defaults


def create_comparability_study_payload(candidate_batch_ids=None, **overrides) -> dict:
    defaults = {
        "change_type": "PROCESS_CHANGE",
        "baseline_attribute_values": [98.0, 98.2, 97.8],
        "candidate_batch_ids": list(candidate_batch_ids or []),
    }
    defaults.update(overrides)
    return defaults


def create_campaign_payload(product_id, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "demand_type": "COMMERCIAL",
        "planned_start_utc": FIXTURE_CLOCK_START,
        "planned_end_utc": "2026-10-20T00:00:00Z",
        "upstream_hours": 20,
        "downstream_hours": 30,
    }
    defaults.update(overrides)
    return defaults


def create_seed_stage_payload(**overrides) -> dict:
    defaults = {"stage_index": 1, "planned_duration_hours": 10}
    defaults.update(overrides)
    return defaults


def create_batch_payload(**overrides) -> dict:
    defaults = {"lot_number": "LOT-0001"}
    defaults.update(overrides)
    return defaults


def create_test_payload(expected_batch_version, **overrides) -> dict:
    defaults = {
        "test_type": "CELL_VIABILITY",
        "phase": "UPSTREAM",
        "measured_value": 85.0,
        "unit": "PCT",
        "spec_min": 80.0,
        "spec_max": 100.0,
        "expected_batch_version": expected_batch_version,
    }
    defaults.update(overrides)
    return defaults


def create_deviation_payload(**overrides) -> dict:
    defaults = {
        "kind": "PROCESS",
        "severity": "MINOR",
        "description": "Deviation under test",
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(**overrides) -> dict:
    defaults = {
        "destination_region": "IE-DUB",
        "market_type": "COMMERCIAL",
        "quantity_units": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_reading_payload(**overrides) -> dict:
    defaults = {
        "recorded_at": "2026-10-02T01:00:00Z",
        "temperature_c": 5.0,
    }
    defaults.update(overrides)
    return defaults

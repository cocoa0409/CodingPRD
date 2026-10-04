"""Payload factories — one per entity, input fields only (PRD §3/§4)."""
from .constants import (
    DEFAULT_PROGRAM_PAYLOAD,
    LINK_CALIBRATED_DATE,
    LINK_DUE_DATE,
)


def create_program_payload(**overrides) -> dict:
    defaults = dict(DEFAULT_PROGRAM_PAYLOAD)
    defaults.update(overrides)
    return defaults


def create_material_lot_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "material_code": "SRM-9090",
        "matrix_description": "matrix",
        "total_units_produced": 10,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Customer",
        "tier": "GENERAL",
        "credit_limit_cents": 1000000,
    }
    defaults.update(overrides)
    return defaults


def create_method_payload(lot_id, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "method_code": "ID-ICP-MS",
        "method_mean": 100.0,
        "method_std_uncertainty": 2.0,
    }
    defaults.update(overrides)
    return defaults


def create_certificate_payload(lot_id, expected_lot_version, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "certificate_code": "CERT-1",
        "value_assignment_variant": "WEIGHTED_MEAN",
        "uncertainty_components": [],
        "validity_days": 365,
        "expected_lot_version": expected_lot_version,
    }
    defaults.update(overrides)
    return defaults


def create_sales_order_payload(lot_id, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "quantity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_service_payload(**overrides) -> dict:
    defaults = {
        "service_code": "DCV-1",
        "measurand": "DC voltage",
        "base_fee_cents": 20000,
        "per_point_fee_cents": 1500,
        "standard_turnaround_days": 5,
    }
    defaults.update(overrides)
    return defaults


def create_calibration_order_payload(service_id, **overrides) -> dict:
    defaults = {
        "service_id": service_id,
        "artifact_description": "artifact",
        "measurement_points": 4,
    }
    defaults.update(overrides)
    return defaults


def create_traceability_link_payload(service_id, **overrides) -> dict:
    defaults = {
        "service_id": service_id,
        "standard_description": "Fluke 5720A working standard",
        "calibrated_by_lab": "NIST-EE",
        "calibrated_date": LINK_CALIBRATED_DATE,
        "calibration_due_date": LINK_DUE_DATE,
        "uncertainty_contribution": 0.1,
    }
    defaults.update(overrides)
    return defaults


def create_pt_round_payload(lot_id, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "round_code": "PT-2026-04",
        "round_type": "PROFICIENCY_TEST",
        "sample_units_reserved": 1,
    }
    defaults.update(overrides)
    return defaults


def create_participant_result_payload(**overrides) -> dict:
    defaults = {
        "lab_code": "LAB-1",
        "measured_value": 100.0,
        "measurement_uncertainty": 1.0,
    }
    defaults.update(overrides)
    return defaults

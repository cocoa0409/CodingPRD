"""Payload factories — one per entity, input fields only."""

import copy

from .constants import (
    RUN_WINDOW_END,
    RUN_WINDOW_START,
    STANDARD_COMPONENTS,
    TEST_DEFAULTS,
    WINDOW_A_END,
    WINDOW_A_START,
)


def create_customer_payload(**overrides) -> dict:
    payload = {
        "name": "Bravo Distribution",
        "customer_type": "PRIVATE_LABEL",
        "contract_tier": "TIER_B",
        "credit_limit_cents": TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_component_lot_payload(**overrides) -> dict:
    payload = {
        "component_type": "BASE_OIL",
        "component_code": "GRP2-150N",
        "received_kg": 400.0,
        "unit_cost_cents_per_kg": 210,
        "kv100_cst": 5.200,
        "density_kg_per_l": 0.855,
        "additive_family": "NONE",
        "coa_viscosity_verified": True,
    }
    payload.update(overrides)
    return payload


def create_product_spec_payload(**overrides) -> dict:
    payload = {
        "product_code": TEST_DEFAULTS["SPEC_PRODUCT_CODE"],
        "sae_grade": "0W-20",
        "target_kv100_cst": TEST_DEFAULTS["SPEC_TARGET_KV100"],
        "kv100_tolerance_pct": TEST_DEFAULTS["SPEC_TOLERANCE_PCT"],
        "min_additive_treat_pct": TEST_DEFAULTS["SPEC_MIN_TREAT_PCT"],
        "base_stock_group": "GROUP_II",
        "additive_family": "ZDDP_PCMO",
    }
    payload.update(overrides)
    return payload


def standard_components() -> list:
    """A fresh copy of the canonical 84 / 6 / 10 formulation."""
    return copy.deepcopy(STANDARD_COMPONENTS)


def create_blend_recipe_payload(product_spec_id, components=None, **overrides) -> dict:
    payload = {
        "product_spec_id": product_spec_id,
        "total_mass_basis_kg": 1000.0,
        "components": components if components is not None else standard_components(),
    }
    payload.update(overrides)
    return payload


def create_blend_tank_payload(**overrides) -> dict:
    payload = {
        "tank_code": TEST_DEFAULTS["TANK_CODE"],
        "capacity_l": TEST_DEFAULTS["TANK_CAPACITY_L"],
        "heel_volume_l": TEST_DEFAULTS["TANK_HEEL_L"],
        "heel_additive_family": "HDEO_API_CK4",
        "heel_product_code": "HDEO-15W40",
    }
    payload.update(overrides)
    return payload


def create_blend_batch_payload(blend_recipe_id, **overrides) -> dict:
    payload = {
        "blend_recipe_id": blend_recipe_id,
        "batch_code": TEST_DEFAULTS["BATCH_CODE"],
        "planned_volume_l": TEST_DEFAULTS["BATCH_PLANNED_VOLUME_L"],
    }
    payload.update(overrides)
    return payload


def charge_payload(blend_tank_id, **overrides) -> dict:
    payload = {
        "blend_tank_id": blend_tank_id,
        "charge_volume_l": TEST_DEFAULTS["CHARGE_VOLUME_L"],
        "window_start": WINDOW_A_START,
        "window_end": WINDOW_A_END,
    }
    payload.update(overrides)
    return payload


def create_qc_result_payload(**overrides) -> dict:
    payload = {"test_type": "KV100", "measured_value": 7.610}
    payload.update(overrides)
    return payload


def create_retain_sample_payload(**overrides) -> dict:
    payload = {"retain_code": "R-0001-A", "volume_ml": 250.0}
    payload.update(overrides)
    return payload


def create_approval_claim_payload(product_spec_id, **overrides) -> dict:
    payload = {
        "product_spec_id": product_spec_id,
        "claim_body": "API",
        "claim_code": "API SP",
    }
    payload.update(overrides)
    return payload


def create_package_configuration_payload(product_spec_id, **overrides) -> dict:
    payload = {
        "product_spec_id": product_spec_id,
        "package_type": "PAIL_20L",
        "label_brand": "House Pail",
        "fill_volume_l": 20.0,
        "private_label": False,
        "claim_codes": [],
    }
    payload.update(overrides)
    return payload


def create_packaging_line_payload(**overrides) -> dict:
    payload = {"line_code": TEST_DEFAULTS["LINE_CODE"], "max_concurrent_runs": 2}
    payload.update(overrides)
    return payload


def create_packaging_run_payload(
    blend_batch_id, package_configuration_id, packaging_line_id, **overrides
) -> dict:
    payload = {
        "blend_batch_id": blend_batch_id,
        "package_configuration_id": package_configuration_id,
        "packaging_line_id": packaging_line_id,
        "window_start": RUN_WINDOW_START,
        "window_end": RUN_WINDOW_END,
        "planned_units": 500,
    }
    payload.update(overrides)
    return payload


def create_order_payload(customer_id, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "delivery_mode": "PACKAGED",
        "takeback_linked": False,
    }
    payload.update(overrides)
    return payload


def create_order_line_payload(package_configuration_id, quantity_units, **overrides) -> dict:
    payload = {
        "package_configuration_id": package_configuration_id,
        "quantity_units": quantity_units,
    }
    payload.update(overrides)
    return payload


def create_takeback_collection_payload(customer_id, **overrides) -> dict:
    payload = {"customer_id": customer_id, "scheduled_volume_l": 1200.0}
    payload.update(overrides)
    return payload


def create_spec_change_request_payload(expected_product_spec_version, **overrides) -> dict:
    payload = {
        "requested_kv100_cst": 7.700,
        "requested_kv100_tolerance_pct": 3.0,
        "requested_min_additive_treat_pct": 8.00,
        "requested_additive_family": "ZDDP_PCMO",
        "expected_product_spec_version": expected_product_spec_version,
    }
    payload.update(overrides)
    return payload

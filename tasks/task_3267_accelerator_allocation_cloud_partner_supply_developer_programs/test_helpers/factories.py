"""Payload factories — one per entity, input fields only.

Each factory returns a dict with the entity's PRD-declared input fields and
accepts ``**overrides`` so tests can control the values under assertion.
"""
from .constants import TEST_DEFAULTS as D


def create_partner_payload(**overrides) -> dict:
    """Body for POST /accelerators/partners."""
    payload = {
        "legal_name": D["PARTNER_LEGAL_NAME"],
        "partner_type": D["PARTNER_TYPE"],
        "destination_country": D["PARTNER_DESTINATION"],
        "export_restriction_tier": "LICENSE_EXCEPTION",
        "origin_epoch_index": D["PARTNER_ORIGIN_EPOCH_INDEX"],
    }
    payload.update(overrides)
    return payload


def create_product_payload(**overrides) -> dict:
    """Body for POST /accelerators/allocations."""
    payload = {
        "sku_code": D["SKU_CODE"],
        "product_family": "DATACENTER",
        "form_factor": "PCLE",
        "hbm_capacity_gb": 80,
        "tdp_watts": D["TDP_WATTS"],
        "supply_ceiling_units": D["SUPPLY_CEILING_UNITS"],
        "long_term_availability_through": D["LONG_TERM_AVAILABILITY_THROUGH"],
    }
    payload.update(overrides)
    return payload


def create_supply_node_payload(product_sku_id: str, **overrides) -> dict:
    """Body for POST /accelerators/supply-nodes."""
    payload = {
        "node_code": "POOL-AMER-1",
        "product_sku_id": product_sku_id,
        "node_region": D["NODE_REGION"],
        "capacity_units": D["NODE_CAPACITY_UNITS"],
        "requested_hotness_tier": "COOL",
    }
    payload.update(overrides)
    return payload


def create_blueprint_payload(**overrides) -> dict:
    """Body for POST /accelerators/blueprints."""
    payload = {
        "blueprint_code": D["BLUEPRINT_CODE"],
        "blueprint_type": D["BLUEPRINT_TYPE"],
        "target_tdp_watts": D["BLUEPRINT_TARGET_TDP_WATTS"],
        "required_validation_minutes": D["BLUEPRINT_REQUIRED_VALIDATION_MINUTES"],
        "evaluation_deadline_days": D["BLUEPRINT_EVALUATION_DEADLINE_DAYS"],
    }
    payload.update(overrides)
    return payload


def create_validation_payload(blueprint_id: str, **overrides) -> dict:
    """Body for POST /accelerators/partners/{id}/validations."""
    payload = {
        "validation_minutes": D["VALIDATION_MINUTES"],
        "test_count": D["VALIDATION_TEST_COUNT"],
        "blueprint_id": blueprint_id,
    }
    payload.update(overrides)
    return payload


def create_allocation_hold_payload(product_sku_id, supply_node_id, quantity_units,
                                   expected_partner_version, expected_allocated_units,
                                   **overrides) -> dict:
    """Body for POST /accelerators/allocation-holds."""
    payload = {
        "product_sku_id": product_sku_id,
        "supply_node_id": supply_node_id,
        "quantity_units": quantity_units,
        "hold_friction_tier": "COOL",
        "expected_partner_version": expected_partner_version,
        "expected_allocated_units": expected_allocated_units,
    }
    payload.update(overrides)
    return payload


def create_stack_license_payload(product_sku_id, **overrides) -> dict:
    """Body for POST /accelerators/stack-licenses."""
    payload = {
        "license_code": "SL-TRAIN-1",
        "product_sku_id": product_sku_id,
        "stack_name": "Training Suite",
        "entitlement_units": D["STACK_ENTITLEMENT_UNITS"],
        "min_package_version": D["STACK_MIN_PACKAGE_VERSION"],
        "preview_stack_flag": False,
    }
    payload.update(overrides)
    return payload


def create_deployment_payload(product_sku_id, stack_manifest=None, **overrides) -> dict:
    """Body for POST /accelerators/deployments."""
    payload = {
        "product_sku_id": product_sku_id,
        "destination_country_code": D["DEPLOYMENT_DESTINATION"],
        "stack_manifest": stack_manifest if stack_manifest is not None else [],
    }
    payload.update(overrides)
    return payload


def create_subscription_payload(deployment_id, licence_group, **overrides) -> dict:
    """Body for POST /accelerators/subscriptions. ``licence_group`` is a list
    of ``{"license_id": ...}`` entries."""
    payload = {
        "deployment_id": deployment_id,
        "support_tier": D["SUBSCRIPTION_SUPPORT_TIER"],
        "seat_count": D["SUBSCRIPTION_SEAT_COUNT"],
        "licence_group": licence_group,
        "trial_flag": True,
    }
    payload.update(overrides)
    return payload


def create_demand_forecast_payload(product_sku_id, expected_partner_version, **overrides) -> dict:
    """Body for POST /accelerators/demand-forecasts."""
    payload = {
        "product_sku_id": product_sku_id,
        "requested_quantity_units": 1000,
        "expected_partner_version": expected_partner_version,
    }
    payload.update(overrides)
    return payload


def create_evaluation_loan_payload(product_sku_id, blueprint_id, **overrides) -> dict:
    """Body for POST /accelerators/evaluation-loans."""
    payload = {
        "product_sku_id": product_sku_id,
        "blueprint_id": blueprint_id,
        "loan_units": 50,
    }
    payload.update(overrides)
    return payload


def create_lifecycle_commitment_payload(product_sku_id, embedded_partner_id, **overrides) -> dict:
    """Body for POST /accelerators/lifecycle-commitments."""
    payload = {
        "product_sku_id": product_sku_id,
        "embedded_partner_id": embedded_partner_id,
        "availability_through": "2029-05-29T00:00:00Z",
        "covered_units": 500,
    }
    payload.update(overrides)
    return payload


def create_supply_contract_payload(product_sku_id, **overrides) -> dict:
    """Body for POST /accelerators/supply-contracts."""
    payload = {
        "product_sku_id": product_sku_id,
        "start_month": "2026-01",
        "end_month": "2026-03",
        "contracted_units": 500,
    }
    payload.update(overrides)
    return payload


def create_membership_payload(**overrides) -> dict:
    """Body for POST /accelerators/developer-memberships."""
    payload = {"requested_tier": "ELITE"}
    payload.update(overrides)
    return payload


def create_confidentiality_ack_payload(membership_id, stack_license_id, **overrides) -> dict:
    """Body for POST /accelerators/confidentiality-acks."""
    payload = {
        "membership_id": membership_id,
        "stack_license_id": stack_license_id,
        "acknowledged_at": "2026-09-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_preview_grant_payload(stack_license_id, confidentiality_ack_id, **overrides) -> dict:
    """Body for POST /accelerators/preview-grants."""
    payload = {
        "stack_license_id": stack_license_id,
        "device_serial": "EVAL-0001",
        "commitment_boundary_at": "2026-09-01T00:00:00Z",
        "commitment_expires_at": "2026-09-30T00:00:00Z",
        "confidentiality_ack_id": confidentiality_ack_id,
    }
    payload.update(overrides)
    return payload


def create_export_license_payload(product_sku_id, **overrides) -> dict:
    """Body for POST /accelerators/export-licenses."""
    payload = {
        "product_sku_id": product_sku_id,
        "destination_country_code": "FR",
        "granted_units": 1000,
    }
    payload.update(overrides)
    return payload


def create_milestone_payload(**overrides) -> dict:
    """Body for POST /accelerators/evaluation-loans/{id}/milestones."""
    payload = {"milestone_type": "KICKOFF", "milestone_result": "PASSED"}
    payload.update(overrides)
    return payload
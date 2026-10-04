"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _unique(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_organization_payload(**overrides) -> dict:
    defaults = {
        "legal_name": _unique("Org"),
        "qualified_device_count": TEST_DEFAULTS["DEVICE_COUNT_LEVEL_A"],
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(organization_id: str, **overrides) -> dict:
    defaults = {
        "organization_id": organization_id,
        "enrollment_number": _unique("E"),
        "start_date": TEST_DEFAULTS["DEFAULT_START_DATE"],
        "end_date": TEST_DEFAULTS["DEFAULT_END_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku": _unique("SKU"),
        "name": _unique("Product"),
        "license_model": "PER_USER",
        "license_kind": "SUBSCRIPTION",
        "edition": "STANDARD",
        "family": "CAL",
        "annual_unit_price_cents": TEST_DEFAULTS["UNIT_PRICE"],
        "license_mobility": False,
    }
    defaults.update(overrides)
    return defaults


def create_anniversary_payload(**overrides) -> dict:
    defaults = {
        "year_index": 1,
        "period_start": TEST_DEFAULTS["DEFAULT_START_DATE"],
        "period_end": "2027-08-31",
    }
    defaults.update(overrides)
    return defaults


def create_entitlement_payload(product_id: str, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "quantity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_user_deployment_payload(product_id: str, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "scope": "USER",
        "deployment_date": TEST_DEFAULTS["DEPLOYMENT_DATE"],
        "user_count": 1,
        "hosting": "ON_PREMISES",
    }
    defaults.update(overrides)
    return defaults


def create_device_deployment_payload(product_id: str, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "scope": "DEVICE",
        "deployment_date": TEST_DEFAULTS["DEPLOYMENT_DATE"],
        "device_count": 1,
        "hosting": "ON_PREMISES",
    }
    defaults.update(overrides)
    return defaults


def create_server_deployment_payload(product_id: str, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "scope": "SERVER",
        "deployment_date": TEST_DEFAULTS["DEPLOYMENT_DATE"],
        "physical_cores_per_server": 32,
        "core_factor": 1.0,
        "vm_count": 0,
        "licensing_mode": "PER_HOST",
        "hosting": "ON_PREMISES",
    }
    defaults.update(overrides)
    return defaults


def create_true_up_line_payload(product_id: str, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "months_growth": 1,
        "pricing_variant": "FULL_YEAR_RETROACTIVE",
    }
    defaults.update(overrides)
    return defaults


def create_benefit_grant_payload(**overrides) -> dict:
    defaults = {
        "benefit_type": "TRAINING_VOUCHER",
        "quantity_granted": 1,
        "expires_on": "2028-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_cloud_commitment_payload(**overrides) -> dict:
    defaults = {
        "committed_amount_cents": 100_000,
        "expires_on": "2028-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_hosting_authorization_payload(product_id: str, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "provider_name": "HosterCo",
        "effective_on": TEST_DEFAULTS["DEFAULT_START_DATE"],
    }
    defaults.update(overrides)
    return defaults

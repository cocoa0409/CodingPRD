"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import CONTRACT_END, CONTRACT_START

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_smart_account_payload(**overrides) -> dict:
    defaults = {"account_ref": _uniq("ACCT"), "display_name": "Test Account"}
    defaults.update(overrides)
    return defaults


def create_partner_org_payload(**overrides) -> dict:
    defaults = {"partner_ref": _uniq("PO"), "display_name": "Test Partner"}
    defaults.update(overrides)
    return defaults


def create_partner_delegation_payload(partner_org_id, smart_account_id, scope="FULL", **overrides) -> dict:
    defaults = {"partner_org_id": partner_org_id, "smart_account_id": smart_account_id, "scope": scope}
    defaults.update(overrides)
    return defaults


def create_virtual_account_payload(smart_account_id, **overrides) -> dict:
    defaults = {"smart_account_id": smart_account_id, "name": _uniq("VA")}
    defaults.update(overrides)
    return defaults


def create_license_pool_payload(virtual_account_id, **overrides) -> dict:
    defaults = {
        "virtual_account_id": virtual_account_id,
        "sku": _uniq("SKU"),
        "license_model": "PERPETUAL",
        "feature_tier": "ESSENTIALS",
        "purchased_quantity": 10,
    }
    defaults.update(overrides)
    return defaults


def create_device_payload(virtual_account_id, **overrides) -> dict:
    defaults = {
        "virtual_account_id": virtual_account_id,
        "serial_number": _uniq("SN"),
        "product_family": _uniq("PF"),
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(device_id, license_pool_id, **overrides) -> dict:
    defaults = {"device_id": device_id, "license_pool_id": license_pool_id, "quantity": 1}
    defaults.update(overrides)
    return defaults


def create_usage_report_payload(license_pool_id, quantity, **overrides) -> dict:
    defaults = {
        "reported_at": "2026-09-02T00:00:00Z",
        "lines": [{"license_pool_id": license_pool_id, "quantity": quantity}],
    }
    defaults.update(overrides)
    return defaults


def create_lifecycle_milestone_payload(product_family, milestone_type, effective_date, **overrides) -> dict:
    defaults = {
        "product_family": product_family,
        "milestone_type": milestone_type,
        "effective_date": effective_date,
    }
    defaults.update(overrides)
    return defaults


def create_service_contract_payload(smart_account_id, **overrides) -> dict:
    defaults = {
        "smart_account_id": smart_account_id,
        "contract_number": _uniq("CTR"),
        "service_level": "ADVANCE_NBD",
        "support_tier": "FULL",
        "start_date": CONTRACT_START,
        "end_date": CONTRACT_END,
    }
    defaults.update(overrides)
    return defaults


def create_contract_coverage_payload(service_contract_id, device_id, **overrides) -> dict:
    defaults = {"service_contract_id": service_contract_id, "device_id": device_id}
    defaults.update(overrides)
    return defaults


def create_rma_case_payload(contract_coverage_id, **overrides) -> dict:
    defaults = {"contract_coverage_id": contract_coverage_id, "failure_description": "unit failure"}
    defaults.update(overrides)
    return defaults


def create_transfer_request_payload(source_pool_id, target_virtual_account_id, **overrides) -> dict:
    defaults = {
        "source_pool_id": source_pool_id,
        "target_virtual_account_id": target_virtual_account_id,
        "quantity": 1,
        "reason": "ACCOUNT_REORG",
    }
    defaults.update(overrides)
    return defaults

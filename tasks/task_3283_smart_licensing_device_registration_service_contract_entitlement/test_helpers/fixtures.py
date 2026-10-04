"""Composite setup helpers: multi-step state builders used by the test suite.

Every helper builds preconditions from scratch against a freshly restarted server
and uses get_success_data() so setup failures surface as clear errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CONTRACT_END, CONTRACT_START
from .factories import (
    create_assignment_payload,
    create_contract_coverage_payload,
    create_device_payload,
    create_license_pool_payload,
    create_lifecycle_milestone_payload,
    create_partner_delegation_payload,
    create_partner_org_payload,
    create_rma_case_payload,
    create_service_contract_payload,
    create_smart_account_payload,
    create_transfer_request_payload,
    create_virtual_account_payload,
)
from .test_users import TEST_USERS, make_account_admin_headers, make_partner_manager_headers

ADMIN = TEST_USERS["platform_admin_headers"]
LOGISTICS = TEST_USERS["logistics_agent_headers"]


def set_clock(to_iso8601: str):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def make_account(**overrides):
    """Create a smart account. Returns the account dict."""
    return get_success_data(api_client.create_smart_account(create_smart_account_payload(**overrides), ADMIN))


def make_va(smart_account_id, **overrides):
    return get_success_data(api_client.create_virtual_account(
        create_virtual_account_payload(smart_account_id, **overrides), ADMIN))


def make_account_with_va(**overrides):
    """Smart account + one virtual account. Returns (account, virtual_account)."""
    account = make_account(**overrides)
    va = make_va(account["id"])
    return account, va


def make_pool(virtual_account_id, **overrides):
    return get_success_data(api_client.create_license_pool(
        create_license_pool_payload(virtual_account_id, **overrides), ADMIN))


def make_device(virtual_account_id, **overrides):
    return get_success_data(api_client.create_device(
        create_device_payload(virtual_account_id, **overrides), ADMIN))


def make_registered_device(virtual_account_id, **overrides):
    """Device shell walked PENDING -> REGISTERED. Returns activated device."""
    device = make_device(virtual_account_id, **overrides)
    return get_success_data(api_client.activate_device(device["id"], ADMIN))


def make_assignment(device_id, license_pool_id, **overrides):
    return get_success_data(api_client.create_license_assignment(
        create_assignment_payload(device_id, license_pool_id, **overrides), ADMIN))


def setup_pool_with_assignment(purchased=10, assign_qty=1, pool_overrides=None, **account_overrides):
    """Account + VA + pool + REGISTERED device + one ACTIVE assignment.

    Returns (account, va, pool, device, assignment).
    """
    account, va = make_account_with_va(**account_overrides)
    pool = make_pool(va["id"], purchased_quantity=purchased, **(pool_overrides or {}))
    device = make_registered_device(va["id"])
    assignment = make_assignment(device["id"], pool["id"], quantity=assign_qty)
    return account, va, pool, device, assignment


def setup_pool_in_grace(purchased=1, assign_qty=2, **account_overrides):
    """Pool driven into overage (consumed > purchased): state IN_GRACE.

    Returns (account, va, pool, device, assignment).
    """
    return setup_pool_with_assignment(
        purchased=purchased, assign_qty=assign_qty, **account_overrides)


def make_service_contract(smart_account_id, **overrides):
    return get_success_data(api_client.create_service_contract(
        create_service_contract_payload(smart_account_id, **overrides), ADMIN))


def make_coverage(service_contract_id, device_id, **overrides):
    return get_success_data(api_client.create_contract_coverage(
        create_contract_coverage_payload(service_contract_id, device_id, **overrides), ADMIN))


def setup_covered_device(service_level="ADVANCE_NBD", support_tier="FULL", **account_overrides):
    """Account + VA + REGISTERED device + ACTIVE contract + ACTIVE coverage.

    Returns (account, va, device, contract, coverage).
    """
    account, va = make_account_with_va(**account_overrides)
    device = make_registered_device(va["id"])
    contract = make_service_contract(
        account["id"], service_level=service_level, support_tier=support_tier)
    coverage = make_coverage(contract["id"], device["id"])
    return account, va, device, contract, coverage


def setup_open_rma(service_level="ADVANCE_NBD", support_tier="FULL", failure_description="unit failure",
                   **account_overrides):
    """Covered device with an OPENED RMA case.

    Returns (account, va, device, contract, coverage, rma).
    """
    account, va, device, contract, coverage = setup_covered_device(
        service_level=service_level, support_tier=support_tier, **account_overrides)
    rma = get_success_data(api_client.create_rma_case(
        create_rma_case_payload(coverage["id"], failure_description=failure_description), ADMIN))
    return account, va, device, contract, coverage, rma


def make_partner_org(**overrides):
    return get_success_data(api_client.create_partner_org(create_partner_org_payload(**overrides), ADMIN))


def make_delegation(partner_org_id, smart_account_id, scope="FULL"):
    """Grant a delegation as the account's AccountAdmin."""
    return get_success_data(api_client.create_partner_delegation(
        create_partner_delegation_payload(partner_org_id, smart_account_id, scope),
        make_account_admin_headers(smart_account_id)))


def setup_partner_with_delegation(scope="FULL", **account_overrides):
    """Partner org + account (managing partner linked) + ACTIVE delegation.

    Returns (partner_org, account).
    """
    partner = make_partner_org()
    account = make_account(managing_partner_id=partner["id"], **account_overrides)
    make_delegation(partner["id"], account["id"], scope)
    return partner, account


def make_transfer_request(source_pool_id, target_va_id, headers=None, **overrides):
    return get_success_data(api_client.create_license_transfer_request(
        create_transfer_request_payload(source_pool_id, target_va_id, **overrides),
        headers or ADMIN))


def approve_transfer(transfer, headers=None):
    """Approve a PENDING transfer using its current version. Returns updated request."""
    return get_success_data(api_client.approve_license_transfer_request(
        transfer["id"], {"expected_transfer_version": transfer["version"]}, headers or ADMIN))


def setup_approved_transfer(quantity=5, purchased=10, assign_qty=0, **account_overrides):
    """Account with VA1 (pool) and VA2 (empty); transfer created and APPROVED.

    Returns (account, va1, va2, pool, transfer).
    """
    account = make_account(**account_overrides)
    va1 = make_va(account["id"])
    va2 = make_va(account["id"])
    pool = make_pool(va1["id"], purchased_quantity=purchased)
    if assign_qty:
        device = make_registered_device(va1["id"])
        make_assignment(device["id"], pool["id"], quantity=assign_qty)
    transfer = make_transfer_request(pool["id"], va2["id"], quantity=quantity)
    transfer = approve_transfer(transfer)
    return account, va1, va2, pool, transfer

"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test). Setup calls
use get_success_data() so failures surface as clear setup errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_device_payload,
    create_employee_payload,
    create_help_desk_case_payload,
    create_key_batch_payload,
    create_key_model_payload,
    create_organization_payload,
    create_purchase_order_payload,
    create_subscription_payload,
    create_temporary_access_payload,
)
from .test_users import TEST_USERS

PA = TEST_USERS["platform_admin_headers"]
SA = TEST_USERS["security_admin_headers"]
PROC = TEST_USERS["procurement_admin_headers"]
LOG = TEST_USERS["logistics_coordinator_headers"]
HD = TEST_USERS["helpdesk_agent_headers"]
HD2 = TEST_USERS["helpdesk_agent_2_headers"]


# --- Tier 1: single-entity creation ---------------------------------------


def create_org(**overrides):
    resp = api_client.create_organization(create_organization_payload(**overrides), PA)
    return get_success_data(resp)


def create_model(**overrides):
    resp = api_client.create_key_model(create_key_model_payload(**overrides), PA)
    return get_success_data(resp)


def create_employee(org_id, **overrides):
    resp = api_client.create_employee(org_id, create_employee_payload(**overrides), SA)
    return get_success_data(resp)


def create_device(org_id, **overrides):
    resp = api_client.create_device(org_id, create_device_payload(**overrides), SA)
    return get_success_data(resp)


def create_subscription(org_id, **overrides):
    resp = api_client.create_subscription(org_id, create_subscription_payload(**overrides), PROC)
    return get_success_data(resp)


def create_pending_order(org_id, lines, shipping_location="HQ", creator_headers=None):
    """Create a PENDING_APPROVAL order. Returns the order dict."""
    resp = api_client.create_purchase_order(
        org_id,
        {"lines": lines, "shipping_location": shipping_location},
        creator_headers or PROC,
    )
    return get_success_data(resp)


def approve_order(org_id, po_id, version, approver_headers=None):
    resp = api_client.approve_purchase_order(
        org_id, po_id, version, approver_headers or SA
    )
    return get_success_data(resp)


def create_approved_order(org_id, lines, shipping_location="HQ", creator_headers=None,
                          approver_headers=None):
    """Tier 1 state progression: PENDING_APPROVAL -> APPROVED."""
    po = create_pending_order(org_id, lines, shipping_location, creator_headers)
    return approve_order(org_id, po["id"], po["version"], approver_headers)


# --- Tier 2: order pipeline with keys -------------------------------------


def create_received_order_with_keys(org_id, lines, serials, firmware_version="5.4.3",
                                    supply_chain_cert_id=None, creator_headers=None,
                                    approver_headers=None, ship_headers=None,
                                    receive_headers=None, keys_headers=None):
    """Create an order, drive it to RECEIVED, and pre-register the given keys.

    Returns (order, keys) where order is re-fetched post-receive via list and
    keys is the list of created SecurityKey dicts.
    """
    po = create_approved_order(org_id, lines, creator_headers=creator_headers,
                               approver_headers=approver_headers)
    # PRD §3.6: keys are pre-registered against an APPROVED order —
    # pre-registration against an order in any other state is ERR_ORDER_STATE.
    keys = get_success_data(api_client.preregister_keys(
        org_id, po["id"],
        create_key_batch_payload(*serials, firmware_version=firmware_version),
        keys_headers or LOG,
    ))
    get_success_data(api_client.ship_purchase_order(
        org_id, po["id"], ship_headers or LOG,
        supply_chain_cert_id=supply_chain_cert_id,
    ))
    po_received = get_success_data(
        api_client.receive_purchase_order(org_id, po["id"], receive_headers or LOG)
    )
    return po_received, keys


def setup_org_model_employee(org_overrides=None, model_overrides=None, employee_overrides=None):
    """Org + key model + employee (with auto-created account). Returns
    (org, model, employee, account_id)."""
    org = create_org(**(org_overrides or {}))
    model = create_model(**(model_overrides or {}))
    emp = create_employee(org["id"], **(employee_overrides or {}))
    return org, model, emp, emp["identity_account_id"]


def setup_received_key_for_account(org_overrides=None, model_overrides=None,
                                   employee_overrides=None, serial="K-001",
                                   firmware_version="5.4.3", quantity=1,
                                   supply_chain_cert_id=None):
    """Org + model + employee + RECEIVED order + one PRE_REGISTERED key.

    Returns dict with org, model, employee, account_id, order, key.
    """
    org, model, emp, acct = setup_org_model_employee(
        org_overrides, model_overrides, employee_overrides
    )
    order, keys = create_received_order_with_keys(
        org["id"],
        [{"model_code": model["model_code"], "quantity": quantity}],
        [serial] if quantity == 1 else [f"{serial}-{i}" for i in range(quantity)],
        firmware_version=firmware_version,
        supply_chain_cert_id=supply_chain_cert_id,
    )
    return {
        "org": org, "model": model, "employee": emp, "account_id": acct,
        "order": order, "key": keys[0], "keys": keys,
    }


# --- Tier 3: full lifecycle shortcuts -------------------------------------


def attest_and_assign(org_id, key_id, account_id, attest_headers=None,
                      assign_headers=None):
    """Attest (UNVERIFIED -> VERIFIED) then assign (PRE_REGISTERED -> ASSIGNED)."""
    attested = get_success_data(
        api_client.attest_security_key(org_id, key_id, attest_headers or SA)
    )
    assigned = get_success_data(
        api_client.assign_security_key(org_id, key_id, account_id, assign_headers or SA)
    )
    return attested, assigned


def attest_assign_distribute(org_id, key_id, account_id):
    """Full key preparation: VERIFIED + DISTRIBUTED to account."""
    attest_and_assign(org_id, key_id, account_id)
    distributed = get_success_data(api_client.mark_distributed(org_id, key_id, LOG))
    return distributed


def account_version(account_id):
    acct = get_success_data(api_client.get_identity_account(account_id, SA))
    return acct["version"]


def create_and_activate_enrollment(account_id, key_id):
    """Create a PENDING ceremony and activate it (OCC with current account
    version). Returns the activated ceremony."""
    ceremony = get_success_data(api_client.create_enrollment(account_id, key_id, SA))
    activated = get_success_data(api_client.activate_enrollment(
        account_id, ceremony["id"], account_version(account_id), SA
    ))
    return activated


def setup_active_enrollment(org_overrides=None, model_overrides=None,
                            backup_key_minimum=2, serial="K-001",
                            supply_chain_cert_id=None, employee_overrides=None):
    """Full setup to one ACTIVE enrollment on a DISTRIBUTED + VERIFIED key.

    Returns dict with org, model, employee, account_id, order, key, enrollment.
    """
    ov = dict(org_overrides or {})
    ov.setdefault("backup_key_minimum", backup_key_minimum)
    env = setup_received_key_for_account(
        org_overrides=ov, model_overrides=model_overrides,
        employee_overrides=employee_overrides,
        serial=serial, supply_chain_cert_id=supply_chain_cert_id,
    )
    attest_assign_distribute(env["org"]["id"], env["key"]["id"], env["account_id"])
    enrollment = create_and_activate_enrollment(env["account_id"], env["key"]["id"])
    env["enrollment"] = enrollment
    return env


def setup_account_with_active_enrollments(count, org_overrides=None,
                                          model_overrides=None, serial_prefix="K"):
    """One account with `count` ACTIVE enrollments (one key each, single order).

    Returns dict with org, model, employee, account_id, order, keys, enrollments.
    """
    org, model, emp, acct = setup_org_model_employee(org_overrides, model_overrides)
    order, keys = create_received_order_with_keys(
        org["id"],
        [{"model_code": model["model_code"], "quantity": count}],
        [f"{serial_prefix}-{i:03d}" for i in range(1, count + 1)],
    )
    enrollments = []
    for k in keys:
        attest_assign_distribute(org["id"], k["id"], acct)
        enrollments.append(create_and_activate_enrollment(acct, k["id"]))
    return {
        "org": org, "model": model, "employee": emp, "account_id": acct,
        "order": order, "keys": keys, "enrollments": enrollments,
    }


# --- Tier 4: help-desk scenarios ------------------------------------------


def setup_pending_review_case(account_id, category="LOST_KEY", opener_headers=None):
    """Open a case and submit it for review. Returns the case dict."""
    case = get_success_data(api_client.create_help_desk_case(
        create_help_desk_case_payload(account_id, category=category),
        opener_headers or HD,
    ))
    reviewed = get_success_data(api_client.submit_case_review(case["id"], opener_headers or HD))
    return reviewed


# --- Tier 5: clock / periodic ----------------------------------------------


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, PA))


def run_periodic(organization_id=None):
    payload = {}
    if organization_id is not None:
        payload["organization_id"] = organization_id
    return get_success_data(api_client.run_periodic(PA, payload))

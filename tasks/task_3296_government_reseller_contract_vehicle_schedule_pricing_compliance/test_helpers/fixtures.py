"""Composite setup helpers.

Every fixture builds its preconditions from scratch via PRD-declared
endpoints; the server is restarted before each test, so nothing carries
over. Setup calls use the lenient get_success_data() so a setup failure
surfaces as a clear "Setup failed" error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_agreement_payload,
    create_audit_payload,
    create_dispute_payload,
    create_invoice_payload,
    create_manufacturer_payload,
    create_order_payload,
    create_price_list_payload,
    create_sales_report_payload,
    create_teaming_payload,
    create_vehicle_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
CM = TEST_USERS["contracts_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
OPS = TEST_USERS["reseller_ops_headers"]
FIN = TEST_USERS["finance_ops_headers"]
AUD = TEST_USERS["auditor_headers"]
INT = TEST_USERS["integrator_headers"]


def set_clock(iso8601=TEST_DEFAULTS["CLOCK_TEST"]):
    resp = api_client.set_clock(iso8601, ADMIN)
    assert resp.status_code == 200, f"Setup failed: set_clock -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def create_manufacturer(**overrides):
    resp = api_client.create_manufacturer(create_manufacturer_payload(**overrides), ADMIN)
    assert resp.status_code == 201, f"Setup failed: create_manufacturer -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def create_active_agreement(manufacturer_id=None, **overrides):
    """Manufacturer + DRAFT agreement + activate. Returns (manufacturer, agreement)."""
    m = manufacturer_id
    manufacturer = None
    if m is None:
        manufacturer = create_manufacturer(**overrides.pop("manufacturer_overrides", {}))
        m = manufacturer["id"]
    resp = api_client.create_agreement(create_agreement_payload(m, **overrides), CM)
    assert resp.status_code == 201, f"Setup failed: create_agreement -> {resp.status_code} {resp.text}"
    agreement = get_success_data(resp)
    resp = api_client.activate_agreement(agreement["id"], CM)
    assert resp.status_code == 200, f"Setup failed: activate_agreement -> {resp.status_code} {resp.text}"
    agreement = get_success_data(resp)
    return manufacturer, agreement


def create_authorized_vehicle(agreement_id, **overrides):
    resp = api_client.create_vehicle(create_vehicle_payload(agreement_id, **overrides), CM)
    assert resp.status_code == 201, f"Setup failed: create_vehicle -> {resp.status_code} {resp.text}"
    vehicle = get_success_data(resp)
    resp = api_client.authorize_vehicle(vehicle["id"], CM)
    assert resp.status_code == 200, f"Setup failed: authorize_vehicle -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def create_submitted_price_list(vehicle_id, lines=None, **overrides):
    resp = api_client.create_price_list(
        create_price_list_payload(vehicle_id, lines=lines, **overrides), CM,
    )
    assert resp.status_code == 201, f"Setup failed: create_price_list -> {resp.status_code} {resp.text}"
    price_list = get_success_data(resp)
    resp = api_client.submit_price_list(price_list["id"], CM)
    assert resp.status_code == 200, f"Setup failed: submit_price_list -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def activate_price_list(price_list_id):
    resp = api_client.activate_price_list(price_list_id, CO)
    assert resp.status_code == 200, f"Setup failed: activate_price_list -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def create_active_price_list(vehicle_id, lines=None, **overrides):
    price_list = create_submitted_price_list(vehicle_id, lines=lines, **overrides)
    return activate_price_list(price_list["id"])


def setup_active_chain(**overrides):
    """Manufacturer + ACTIVE agreement + AUTHORIZED vehicle + ACTIVE price list.

    Returns (manufacturer, agreement, vehicle, price_list).
    """
    set_clock(overrides.pop("clock", TEST_DEFAULTS["CLOCK_TEST"]))
    manufacturer, agreement = create_active_agreement(
        manufacturer_overrides=overrides.pop("manufacturer_overrides", {}),
        **overrides.pop("agreement_overrides", {}),
    )
    vehicle = create_authorized_vehicle(agreement["id"], **overrides.pop("vehicle_overrides", {}))
    price_list = create_active_price_list(
        vehicle["id"],
        lines=overrides.pop("lines", None),
        **overrides.pop("price_list_overrides", {}),
    )
    return manufacturer, agreement, vehicle, price_list


def create_order(vehicle_id, price_list_id, lines=None, headers=OPS, **overrides):
    resp = api_client.create_order(
        create_order_payload(vehicle_id, price_list_id, lines=lines, **overrides), headers,
    )
    assert resp.status_code == 201, f"Setup failed: create_order -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def create_cleared_order(vehicle_id, price_list_id, lines=None, headers=OPS, **overrides):
    """Create + submit; asserts the order auto-cleared screening. Returns the order."""
    order = create_order(vehicle_id, price_list_id, lines=lines, headers=headers, **overrides)
    resp = api_client.submit_order(order["id"], headers)
    assert resp.status_code == 200, f"Setup failed: submit_order -> {resp.status_code} {resp.text}"
    order = get_success_data(resp)
    assert order["compliance_status"] == "CLEARED", (
        f"Setup failed: order did not clear screening, got {order['compliance_status']}"
    )
    return order


def create_delivered_order(vehicle_id, price_list_id, lines=None, headers=OPS, **overrides):
    order = create_cleared_order(vehicle_id, price_list_id, lines=lines, headers=headers, **overrides)
    resp = api_client.deliver_order(order["id"], OPS)
    assert resp.status_code == 200, f"Setup failed: deliver_order -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def create_approved_teaming(agreement_id, vehicle_id, **overrides):
    resp = api_client.create_teaming(
        create_teaming_payload(agreement_id, vehicle_id, **overrides), CM,
    )
    assert resp.status_code == 201, f"Setup failed: create_teaming -> {resp.status_code} {resp.text}"
    teaming = get_success_data(resp)
    resp = api_client.approve_teaming(teaming["id"], CO)
    assert resp.status_code == 200, f"Setup failed: approve_teaming -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def create_dispute(order_id, **overrides):
    resp = api_client.create_dispute(create_dispute_payload(order_id, **overrides), CO)
    assert resp.status_code == 201, f"Setup failed: create_dispute -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def drive_agreement_on_hold(agreement_id, vehicle_id, price_list_id, debt_cents=-200000):
    """Raise a debt dispute on a throwaway order to push posture to ON_HOLD.

    PRD §2.6: dispute_credit_cents strictly less than -100000 -> ON_HOLD.
    """
    ref_order = create_order(vehicle_id, price_list_id)
    dispute = create_dispute(ref_order["id"], amount_cents=debt_cents)
    return ref_order, dispute


def create_issued_invoice(order_id, headers=OPS, **overrides):
    resp = api_client.create_invoice(create_invoice_payload(order_id, **overrides), headers)
    assert resp.status_code == 201, f"Setup failed: create_invoice -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def create_sales_report(agreement_id, **overrides):
    resp = api_client.create_sales_report(create_sales_report_payload(agreement_id, **overrides), FIN)
    assert resp.status_code == 201, f"Setup failed: create_sales_report -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def create_finalized_sales_report(agreement_id, period_label="2026-08"):
    """Open + finalize a report for a period already closed at the test clock."""
    report = create_sales_report(agreement_id, period_label=period_label)
    resp = api_client.finalize_sales_report(report["id"], FIN)
    assert resp.status_code == 200, f"Setup failed: finalize_sales_report -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def create_audit(agreement_id, **overrides):
    resp = api_client.create_audit(create_audit_payload(agreement_id, **overrides), AUD)
    assert resp.status_code == 201, f"Setup failed: create_audit -> {resp.status_code} {resp.text}"
    return get_success_data(resp)

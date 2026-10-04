"""Composite setup helpers for the Online Vehicle Purchase API."""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_customer_payload,
    create_vehicle_payload,
    create_center_payload,
    create_order_payload,
    create_appointment_payload,
    create_prequalify_payload,
)
from .test_users import TEST_USERS, make_customer_headers


def create_customer(**overrides):
    """Create a customer; returns (customer_dict, customer_headers)."""
    resp = api_client.create_customer(
        create_customer_payload(**overrides), TEST_USERS["platform_admin_headers"]
    )
    data = get_success_data(resp)
    return data, make_customer_headers(data["id"])


def create_center(**overrides):
    """Create a reconditioning center; returns center dict."""
    resp = api_client.create_center(
        create_center_payload(**overrides), TEST_USERS["platform_admin_headers"]
    )
    return get_success_data(resp)


def create_listed_vehicle(**overrides):
    """Create a vehicle, walk it through recon (center + intake workflow), list it.

    Per PRD, the direct INTAKE -> IN_RECON transition requires the vehicle's
    center_id to reference an existing center, and listing requires every linked
    ReconIntake to be COMPLETE or CANCELLED. Supplying center_id at vehicle
    intake auto-creates a ReconIntake in PENDING_ARRIVAL, so the full workflow
    arrive -> start-work -> complete must run before listing.
    Returns vehicle dict.
    """
    market_code = overrides.get("market_code", "ATL-A")
    if "center_id" not in overrides:
        center = create_center(market_code=market_code)
        overrides["center_id"] = center["id"]
    resp = api_client.create_vehicle(
        create_vehicle_payload(**overrides), TEST_USERS["platform_admin_headers"]
    )
    vehicle = get_success_data(resp)
    recon_headers = TEST_USERS["recon_operator_headers"]
    intakes = get_success_data(
        api_client.get_vehicle_recon_intakes(vehicle["id"], recon_headers)
    )
    for intake in intakes:
        if intake["status"] == "PENDING_ARRIVAL":
            get_success_data(api_client.arrive_recon_intake(intake["id"], recon_headers))
            get_success_data(api_client.start_work_recon_intake(intake["id"], recon_headers))
            get_success_data(api_client.complete_recon_intake(intake["id"], recon_headers))
    resp = api_client.list_vehicle(vehicle["id"], recon_headers)
    return get_success_data(resp)


def create_and_reserve_order(customer_id, vehicle_id, **overrides):
    """Create a DRAFT order and reserve it. Returns order dict."""
    customer_headers = make_customer_headers(customer_id)
    payload = create_order_payload(**overrides)
    payload["vehicle_id"] = vehicle_id
    resp = api_client.create_order(payload, customer_headers)
    order = get_success_data(resp)
    vehicle = get_success_data(api_client.get_vehicle(vehicle_id, customer_headers))
    resp = api_client.reserve_order(
        order["id"],
        {"expected_vehicle_version": vehicle["version"]},
        customer_headers,
    )
    return get_success_data(resp)


def create_structured_order(customer_id, vehicle_id, financing_id=None, down_payment_cents=0, **overrides):
    """Create order, reserve, structure. Returns order dict."""
    order = create_and_reserve_order(customer_id, vehicle_id, **overrides)
    customer_headers = make_customer_headers(customer_id)
    payload = {}
    if financing_id:
        payload["financing_id"] = financing_id
        payload["down_payment_cents"] = down_payment_cents
    resp = api_client.structure_order(order["id"], payload, customer_headers)
    return get_success_data(resp)


def create_appointment_set_order(customer_id, vehicle_id, financing_id=None, down_payment_cents=0, appointment_overrides=None, **overrides):
    """Create order, reserve, structure, book appointment. Returns (order, appointment)."""
    order = create_structured_order(customer_id, vehicle_id, financing_id, down_payment_cents, **overrides)
    customer_headers = make_customer_headers(customer_id)
    appt_payload = create_appointment_payload(**(appointment_overrides or {}))
    if order.get("fulfillment_choice") == "VENDING_MACHINE":
        # PRD: vending-machine bookings carry vending_site_code instead of address_region.
        appt_payload.pop("address_region", None)
        appt_payload.setdefault("vending_site_code", "ATL-VM-1")
    appt_payload["expected_order_version"] = order["version"]
    resp = api_client.book_appointment(order["id"], appt_payload, customer_headers)
    appointment = get_success_data(resp)
    order = get_success_data(api_client.get_order(order["id"], customer_headers))
    return order, appointment


def create_completed_order(customer_id, vehicle_id, financing_id=None, down_payment_cents=0, appointment_overrides=None, odometer_at_delivery=10000, **overrides):
    """Create order through COMPLETED. Returns (order, appointment)."""
    order, appointment = create_appointment_set_order(
        customer_id, vehicle_id, financing_id, down_payment_cents, appointment_overrides, **overrides
    )
    complete_payload = {"odometer_at_delivery": odometer_at_delivery}
    if order.get("fulfillment_choice") == "HOME_DELIVERY":
        # PRD: home-delivery completion requires the payment_confirmed acknowledgement.
        complete_payload["payment_confirmed"] = True
    resp = api_client.complete_order(
        order["id"],
        complete_payload,
        TEST_USERS["platform_admin_headers"],
    )
    order = get_success_data(resp)
    return order, appointment


def create_returned_order(customer_id, vehicle_id, return_mileage=10400, **overrides):
    """Create a COMPLETED order then initiate return. Returns order dict."""
    order, _ = create_completed_order(customer_id, vehicle_id, **overrides)
    customer_headers = make_customer_headers(customer_id)
    resp = api_client.return_order(
        order["id"],
        {"return_mileage": return_mileage, "reason_code": "CHANGED_MIND"},
        customer_headers,
    )
    return get_success_data(resp)


def create_returned_order_with_transit(customer_id, vehicle_id, return_mileage=10400, **overrides):
    """Create COMPLETED order, return it, schedule pickup, pick up, arrive. Returns order dict."""
    order = create_returned_order(customer_id, vehicle_id, return_mileage, **overrides)
    advocate_headers = TEST_USERS["customer_advocate_headers"]
    api_client.schedule_pickup(
        order["id"],
        {"start_at": "2026-09-03T09:00:00Z", "end_at": "2026-09-03T10:00:00Z"},
        advocate_headers,
    )
    api_client.transit_pickup(order["id"], advocate_headers)
    api_client.transit_arrive(order["id"], advocate_headers)
    return get_success_data(api_client.get_order(order["id"], TEST_USERS["platform_admin_headers"]))


def create_prequalification(customer_id, **overrides):
    """Create a prequalification for a customer. Returns prequal dict."""
    customer_headers = make_customer_headers(customer_id)
    resp = api_client.prequalify(create_prequalify_payload(**overrides), customer_headers)
    return get_success_data(resp)


def create_financed_structured_order(customer_id, vehicle_id, income=8000000, band="A", down_payment_cents=300000, **overrides):
    """Create prequal, order, reserve, structure with financing. Returns (order, prequal)."""
    prequal = create_prequalification(customer_id, annual_income_cents=income, credit_band=band)
    order = create_structured_order(customer_id, vehicle_id, financing_id=prequal["id"], down_payment_cents=down_payment_cents, **overrides)
    return order, prequal

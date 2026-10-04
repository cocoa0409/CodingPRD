"""Composite setup helpers for drive-in stall order and carhop dispatch tests.

Every fixture builds its preconditions from scratch through the public API —
the server is restarted before every test, so nothing carries over.
"""
from prd_bench_local_runner.testing import get_success_data, is_valid_uuid

from .api_client import api_client
from .factories import (
    create_carhop_payload,
    create_drive_thru_order_payload,
    create_location_payload,
    create_menu_item_payload,
    create_service_target_payload,
    create_stall_payload,
)
from .test_users import TEST_USERS, make_carhop_headers

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["shift_manager_headers"]
KITCHEN = TEST_USERS["kitchen_staff_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock + location setup
# ---------------------------------------------------------------------------

def set_clock(current_utc: str):
    resp = api_client.set_clock({"current_utc": current_utc}, ADMIN)
    return get_success_data(resp)


def create_location(code="TST-001", stall_capacity=4, timezone="America/Chicago", **overrides):
    resp = api_client.create_location(
        create_location_payload(code=code, stall_capacity=stall_capacity, timezone=timezone, **overrides),
        ADMIN,
    )
    return get_success_data(resp)


def create_menu_item(**overrides):
    resp = api_client.create_menu_item(create_menu_item_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_service_target(location_id, channel="STALL_INTERCOM", weather_mode="NORMAL",
                          target_seconds=600, headers=None):
    resp = api_client.create_service_target(
        location_id,
        create_service_target_payload(
            channel=channel, weather_mode=weather_mode, target_seconds=target_seconds
        ),
        headers or ADMIN,
    )
    return get_success_data(resp)


def create_stall(location_id, stall_number=1, kind="STALL"):
    resp = api_client.create_stall(
        location_id, create_stall_payload(stall_number=stall_number, kind=kind), ADMIN
    )
    return get_success_data(resp)


def create_carhop(location_id, name="Hop", zone="NORTH", max_trays=3, on_shift=True):
    resp = api_client.create_carhop(
        location_id,
        create_carhop_payload(name=name, zone=zone, max_trays=max_trays, on_shift=on_shift),
        MANAGER,
    )
    return get_success_data(resp)


def get_location(location_id):
    return get_success_data(api_client.get_location(location_id, MANAGER))


# ---------------------------------------------------------------------------
# Tier 1: check-in and draft orders
# ---------------------------------------------------------------------------

def intercom_checkin(location_id, stall_id):
    """Re-read the location for the OCC version, then check in via intercom.

    Returns the newly created DRAFT order.
    """
    location = get_location(location_id)
    resp = api_client.checkin(
        location_id, stall_id, {"expected_location_version": location["version"]}, MANAGER
    )
    return get_success_data(resp)


def add_line(location_id, order_id, menu_item_id, quantity=1, **extra):
    payload = {"menu_item_id": menu_item_id, "quantity": quantity}
    payload.update(extra)
    resp = api_client.add_order_line(location_id, order_id, payload, MANAGER)
    return get_success_data(resp)


def create_drive_thru_order(location_id, customer_id=None):
    payload = create_drive_thru_order_payload()
    if customer_id is not None:
        payload["customer_id"] = customer_id
    resp = api_client.create_order(location_id, payload, MANAGER)
    return get_success_data(resp)


def setup_stall_draft_order(code="TST-DRAFT", item_price=500, stall_capacity=4,
                            target_seconds=600, stall_number=2):
    """Location + STALL_INTERCOM service target + food item + stall + a DRAFT
    intercom order with one line. Returns dict of ids/entities."""
    location = create_location(code=code, stall_capacity=stall_capacity)
    create_service_target(location["id"], target_seconds=target_seconds)
    item = create_menu_item(
        sku=f"FD-{code}", name="Food", category="FOOD", base_price_cents=item_price
    )
    stall = create_stall(location["id"], stall_number=stall_number)
    order = intercom_checkin(location["id"], stall["id"])
    add_line(location["id"], order["id"], item["id"])
    return {"location": location, "item": item, "stall": stall, "order": order}


# ---------------------------------------------------------------------------
# Tier 2: fulfillment progression
# ---------------------------------------------------------------------------

def place_order(location_id, order_id, payload=None):
    resp = api_client.place_order(location_id, order_id, payload or {}, MANAGER)
    return get_success_data(resp)


def advance_order_to_ready(location_id, order_id):
    """PLACED -> PREPARING -> READY. Returns the READY order."""
    get_success_data(api_client.start_preparation(location_id, order_id, KITCHEN))
    return get_success_data(api_client.mark_ready(location_id, order_id, KITCHEN))


def authorize_and_capture(location_id, order_id, tip_cents=None):
    get_success_data(api_client.authorize_payment(location_id, order_id, MANAGER))
    payload = {} if tip_cents is None else {"tip_cents": tip_cents}
    return get_success_data(api_client.capture_payment(location_id, order_id, payload, MANAGER))


def place_and_ready(location_id, order_id):
    """Place, start preparation, mark ready. Returns the READY order."""
    place_order(location_id, order_id)
    return advance_order_to_ready(location_id, order_id)


# ---------------------------------------------------------------------------
# Tier 3: dispatch lifecycle
# ---------------------------------------------------------------------------

def stage_run(location_id, carhop, order_ids=None, route_note=None):
    """Stage a delivery run against the carhop's current version (OCC).

    Returns the LOADED DeliveryRun.
    """
    carhop_now = get_success_data(api_client.get_carhop(location_id, carhop["id"], MANAGER))
    payload = {
        "carhop_id": carhop["id"],
        "expected_carhop_version": carhop_now["version"],
    }
    if order_ids is not None:
        payload["order_ids"] = order_ids
    if route_note is not None:
        payload["route_note"] = route_note
    resp = api_client.create_delivery_run(location_id, payload, MANAGER)
    return get_success_data(resp)


def depart_run(location_id, run_id, carhop_id):
    headers = make_carhop_headers(carhop_id)
    return get_success_data(api_client.depart_run(location_id, run_id, headers))


def deliver_order(location_id, run_id, order_id, carhop_id):
    headers = make_carhop_headers(carhop_id)
    return get_success_data(api_client.deliver_order(location_id, run_id, order_id, headers))


def setup_ready_order_on_stall(code="TST-READY", item_price=500, stall_capacity=4,
                               carhop_name="Hop", carhop_zone="NORTH", max_trays=3,
                               target_seconds=600, tip_cents=None):
    """Full chain: location + target + item + stall + carhop + DRAFT order with
    one line, then placed, prepared, ready. Payment is NOT authorized.

    Returns dict with location, item, stall, carhop, order.
    """
    ctx = setup_stall_draft_order(
        code=code, item_price=item_price, stall_capacity=stall_capacity,
        target_seconds=target_seconds,
    )
    carhop = create_carhop(
        ctx["location"]["id"], name=carhop_name, zone=carhop_zone, max_trays=max_trays
    )
    order = place_and_ready(ctx["location"]["id"], ctx["order"]["id"])
    ctx["carhop"] = carhop
    ctx["order"] = order
    return ctx


def setup_captured_ready_order(code="TST-CAPT", item_price=500, stall_capacity=4,
                               carhop_name="Hop", carhop_zone="NORTH", max_trays=3,
                               target_seconds=600, tip_cents=None):
    """As setup_ready_order_on_stall, plus AUTHORIZED -> CAPTURED payment."""
    ctx = setup_ready_order_on_stall(
        code=code, item_price=item_price, stall_capacity=stall_capacity,
        carhop_name=carhop_name, carhop_zone=carhop_zone, max_trays=max_trays,
        target_seconds=target_seconds,
    )
    order = authorize_and_capture(ctx["location"]["id"], ctx["order"]["id"], tip_cents=tip_cents)
    ctx["order"] = order
    return ctx


def setup_out_for_delivery(code="TST-OUT", item_price=500, stall_capacity=4,
                           carhop_name="Hop", carhop_zone="NORTH", max_trays=3,
                           target_seconds=600, tip_cents=None):
    """Captured READY order staged on a departed run (order OUT_FOR_DELIVERY).

    Returns dict with location, item, stall, carhop, order, run.
    """
    ctx = setup_captured_ready_order(
        code=code, item_price=item_price, stall_capacity=stall_capacity,
        carhop_name=carhop_name, carhop_zone=carhop_zone, max_trays=max_trays,
        target_seconds=target_seconds, tip_cents=tip_cents,
    )
    run = stage_run(ctx["location"]["id"], ctx["carhop"], order_ids=[ctx["order"]["id"]])
    depart_run(ctx["location"]["id"], run["id"], ctx["carhop"]["id"])
    ctx["run"] = run
    return ctx


def setup_delivered_order(code="TST-DLVR", item_price=500, stall_capacity=4,
                          carhop_name="Hop", carhop_zone="NORTH", max_trays=3,
                          target_seconds=600, tip_cents=None):
    """Full lifecycle through DELIVERED. The run auto-completes on delivery.

    Returns dict with location, item, stall, carhop, order (DELIVERED), run.
    """
    ctx = setup_out_for_delivery(
        code=code, item_price=item_price, stall_capacity=stall_capacity,
        carhop_name=carhop_name, carhop_zone=carhop_zone, max_trays=max_trays,
        target_seconds=target_seconds, tip_cents=tip_cents,
    )
    order = deliver_order(
        ctx["location"]["id"], ctx["run"]["id"], ctx["order"]["id"], ctx["carhop"]["id"]
    )
    ctx["order"] = order
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: drive-thru helpers
# ---------------------------------------------------------------------------

def setup_drive_thru_location(code="TST-DT", target_seconds=300, item_price=1000):
    """Location + DRIVE_THRU service target + one food item. Returns dict."""
    location = create_location(code=code)
    create_service_target(location["id"], channel="DRIVE_THRU", target_seconds=target_seconds)
    item = create_menu_item(
        sku=f"FD-{code}", name="Food", category="FOOD", base_price_cents=item_price
    )
    return {"location": location, "item": item}


def create_drive_thru_order_with_line(location_id, menu_item_id, quantity=1, customer_id=None):
    order = create_drive_thru_order(location_id, customer_id=customer_id)
    add_line(location_id, order["id"], menu_item_id, quantity=quantity)
    return order


def place_drive_thru_order(location_id, menu_item_id, customer_id=None, quantity=1):
    """Create a DRIVE_THRU DRAFT with one line and place it. Returns PLACED order."""
    order = create_drive_thru_order_with_line(
        location_id, menu_item_id, quantity=quantity, customer_id=customer_id
    )
    return place_order(location_id, order["id"])

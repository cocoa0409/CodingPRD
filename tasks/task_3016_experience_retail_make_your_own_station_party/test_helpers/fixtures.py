"""Composite setup helpers.

Every helper builds preconditions from scratch through PRD-declared endpoints
(the harness restarts the server before each test, so nothing persists).
Customer-identity-gated calls always use make_customer_headers(customer["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_build_ship_order_payload,
    create_collection_drop_payload,
    create_consumable_payload,
    create_customer_payload,
    create_gift_card_payload,
    create_party_guest_payload,
    create_party_payload,
    create_plush_model_payload,
    create_registry_payload,
    create_staff_payload,
    create_station_payload,
    create_store_payload,
    create_workshop_payload,
)
from .test_users import TEST_USERS, make_customer_headers

MANAGER = TEST_USERS["store_manager_headers"]
ASSOCIATE = TEST_USERS["workshop_associate_headers"]
PARTY_HOST = TEST_USERS["party_host_headers"]
CUSTOMER = TEST_USERS["customer_headers"]

STATION_TYPES = ("STUFF", "SOUND", "BATHE", "DRESS")


# ---------------------------------------------------------------------------
# Tier 0: primitives
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Advance the logical clock (PRD §2.4). Returns the response data."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, MANAGER)
    )


def create_store(name="Test Store", party_room_count=1):
    return get_success_data(
        api_client.create_store(
            create_store_payload(name=name, party_room_count=party_room_count),
            MANAGER,
        )
    )


def create_customer(email=None, full_name=None):
    overrides = {}
    if email is not None:
        overrides["email"] = email
    if full_name is not None:
        overrides["full_name"] = full_name
    return get_success_data(
        api_client.create_customer(create_customer_payload(**overrides), CUSTOMER)
    )


def create_staff(store_id, role_title="PARTY_HOST", display_name="Staff"):
    return get_success_data(
        api_client.create_staff(
            create_staff_payload(store_id, role_title=role_title, display_name=display_name),
            MANAGER,
        )
    )


def create_model(**overrides):
    return get_success_data(
        api_client.create_plush_model(create_plush_model_payload(**overrides), MANAGER)
    )


def provision_consumables(store_id, fiber_qty=100000, chip_qty=None):
    """Create the STUFFING_FIBER row (always) and SOUND_CHIP row (when chip_qty
    is not None). Returns {"fiber": row, "chip": row_or_None}."""
    fiber = get_success_data(
        api_client.create_consumable(
            create_consumable_payload(store_id, "STUFFING_FIBER", initial_qty=fiber_qty),
            MANAGER,
        )
    )
    chip = None
    if chip_qty is not None:
        chip = get_success_data(
            api_client.create_consumable(
                create_consumable_payload(store_id, "SOUND_CHIP", initial_qty=chip_qty),
                MANAGER,
            )
        )
    return {"fiber": fiber, "chip": chip}


def provision_stations(store_id, capacity=4, types=STATION_TYPES):
    """Create one station per requested type. Returns {station_type: station}."""
    return {
        station_type: get_success_data(
            api_client.create_station(
                create_station_payload(store_id, station_type, capacity=capacity),
                MANAGER,
            )
        )
        for station_type in types
    }


def create_gift_card(code=None, initial_balance_cents=10000):
    overrides = {"initial_balance_cents": initial_balance_cents}
    if code is not None:
        overrides["code"] = code
    return get_success_data(
        api_client.create_gift_card(create_gift_card_payload(**overrides), MANAGER)
    )


def create_registry(customer, name="Test Registry"):
    return get_success_data(
        api_client.create_registry(
            create_registry_payload(customer["id"], name=name),
            make_customer_headers(customer["id"]),
        )
    )


# ---------------------------------------------------------------------------
# Tier 1/2: workshop environment + session progression
# ---------------------------------------------------------------------------

def setup_workshop_env(
    store_name="Workshop Store",
    fiber_qty=100000,
    chip_qty=100,
    station_capacity=4,
    station_types=STATION_TYPES,
    model_overrides=None,
    customer_email=None,
):
    """Store + customer + plush model + consumables + stations.

    Returns {"store", "customer", "model", "consumables", "stations"}.
    """
    store = create_store(name=store_name)
    customer = create_customer(email=customer_email)
    model = create_model(**(model_overrides or {}))
    consumables = provision_consumables(store["id"], fiber_qty=fiber_qty, chip_qty=chip_qty)
    stations = provision_stations(store["id"], capacity=station_capacity, types=station_types)
    return {
        "store": store,
        "customer": customer,
        "model": model,
        "consumables": consumables,
        "stations": stations,
    }


def create_walk_in_session(env, customer=None, model=None, **payload_overrides):
    customer = customer or env["customer"]
    model = model or env["model"]
    return get_success_data(
        api_client.create_workshop(
            create_workshop_payload(
                env["store"]["id"], customer["id"], model["id"], **payload_overrides
            ),
            ASSOCIATE,
        )
    )


def advance_session(session_id):
    """One advance-step; returns the updated session (setup-lenient)."""
    return get_success_data(api_client.advance_workshop(session_id, ASSOCIATE))


def advance_to_dressed(session_id):
    """Five advances: SELECT -> ... -> DRESSED. Returns the DRESSED session."""
    session = None
    for _ in range(5):
        session = advance_session(session_id)
    return session


def get_session_total(session_id, customer_id):
    session = get_success_data(
        api_client.get_workshop(session_id, make_customer_headers(customer_id))
    )
    return session["total_price_cents"], session


def pay_session_cash(session_id, customer_id, amount_cents=None):
    """Pay a DRESSED session with CASH. When amount_cents is None, reads the
    session's quoted total_price_cents first (PRD §3.5 exact-match rule)."""
    if amount_cents is None:
        amount_cents, _ = get_session_total(session_id, customer_id)
    return get_success_data(
        api_client.pay_workshop(
            session_id,
            {"payment_amount_cents": amount_cents, "pay_tender": "CASH"},
            make_customer_headers(customer_id),
        )
    )


def create_paid_walk_in(env, customer=None, model=None):
    """Walk-in session driven SELECT -> DRESSED -> PAID (CASH at quoted total).

    Returns (paid_session, stuffed_animal_id).
    """
    customer = customer or env["customer"]
    session = create_walk_in_session(env, customer=customer, model=model)
    advance_to_dressed(session["id"])
    paid = pay_session_cash(session["id"], customer["id"])
    return paid, paid["stuffed_animal_id"]


# ---------------------------------------------------------------------------
# Tier 2/3: party reservation flows
# ---------------------------------------------------------------------------

def create_party(customer, store_id, **overrides):
    return get_success_data(
        api_client.create_party(
            create_party_payload(store_id, customer["id"], **overrides),
            make_customer_headers(customer["id"]),
        )
    )


def pay_party_deposit(party, customer_id):
    """Pay the exact quoted deposit. Returns the DEPOSIT_PAID reservation."""
    return get_success_data(
        api_client.pay_party_deposit(
            party["id"],
            {"payment_amount_cents": party["deposit_amount_cents"]},
            make_customer_headers(customer_id),
        )
    )


def add_party_guests(party_id, customer_id, count, confirm=True, name_prefix="Guest"):
    """Add `count` guests and (optionally) confirm each. Returns guest list."""
    guests = []
    for i in range(count):
        guest = get_success_data(
            api_client.create_party_guest(
                create_party_guest_payload(party_id, guest_name=f"{name_prefix} {i + 1}"),
                make_customer_headers(customer_id),
            )
        )
        if confirm:
            guest = get_success_data(
                api_client.confirm_party_guest(
                    guest["id"], make_customer_headers(customer_id)
                )
            )
        guests.append(guest)
    return guests


def confirm_party_via_clock(party):
    """Move the clock to party_start, crossing the 24h auto-confirm threshold
    (PRD §3.7). Guest workshop sessions are created for CONFIRMED guests."""
    set_clock(party["party_start"])


def list_guest_sessions(party_id, customer_id):
    """Return [{guest, session_id}] for guests that have a session assigned."""
    guests = get_success_data(
        api_client.list_party_guests(
            party_id, make_customer_headers(customer_id), params={"limit": 100}
        )
    )
    if isinstance(guests, dict):
        guests = guests.get("data", guests.get("items", []))
    return [
        {"guest": g, "session_id": g.get("workshop_session_id")}
        for g in guests
    ]


def complete_guest_session(session_id, customer_id):
    """Drive a guest (party-origin) session to PAID at its quoted total."""
    advance_to_dressed(session_id)
    return pay_session_cash(session_id, customer_id)


def setup_confirmed_party(
    guest_count=6,
    confirmed_guests=1,
    package_tier="BASIC",
    staffing_mode="SELF_GUIDED",
    party_start="2026-10-08T18:00:00Z",
    clock_at_booking="2026-10-01T00:00:00Z",
    store_name="Party Store",
    party_room_count=2,
    fiber_qty=1000000,
    chip_qty=100,
    station_capacity=8,
):
    """Full party pipeline through CONFIRMED with guest sessions created.

    Returns {"store", "customer", "model", "party", "guests", "sessions"} where
    sessions is the list from list_guest_sessions (guests with sessions).
    """
    store = create_store(name=store_name, party_room_count=party_room_count)
    customer = create_customer()
    model = create_model()
    provision_consumables(store["id"], fiber_qty=fiber_qty, chip_qty=chip_qty)
    provision_stations(store["id"], capacity=station_capacity)
    set_clock(clock_at_booking)
    party = create_party(
        customer,
        store["id"],
        party_start=party_start,
        guest_count=guest_count,
        package_tier=package_tier,
        staffing_mode=staffing_mode,
    )
    party = pay_party_deposit(party, customer["id"])
    guests = add_party_guests(party["id"], customer["id"], confirmed_guests)
    confirm_party_via_clock(party)
    sessions = list_guest_sessions(party["id"], customer["id"])
    return {
        "store": store,
        "customer": customer,
        "model": model,
        "party": party,
        "guests": guests,
        "sessions": sessions,
    }


# ---------------------------------------------------------------------------
# Tier 3: build-and-ship flows
# ---------------------------------------------------------------------------

def create_build_ship_order(store_id, customer, model_id, **overrides):
    return get_success_data(
        api_client.create_build_ship_order(
            create_build_ship_order_payload(store_id, customer["id"], model_id, **overrides),
            make_customer_headers(customer["id"]),
        )
    )


def assemble_order(order_id):
    """start-assembly; returns (order, workshop_session_id)."""
    order = get_success_data(api_client.start_build_ship_assembly(order_id, ASSOCIATE))
    return order, order["workshop_session_id"]


def hand_over_order(order_id, customer_id, carrier_code="UPS", tracking_number="1Z000"):
    """Drive an IN_ASSEMBLY order's session to PAID, then hand off.

    Returns the HANDED_TO_CARRIER order.
    """
    order = get_success_data(
        api_client.get_build_ship_order(order_id, make_customer_headers(customer_id))
    )
    session_id = order["workshop_session_id"]
    advance_to_dressed(session_id)
    pay_session_cash(session_id, customer_id)
    return get_success_data(
        api_client.handoff_build_ship_order(
            order_id,
            {"carrier_code": carrier_code, "tracking_number": tracking_number},
            ASSOCIATE,
        )
    )


def setup_handed_over_orders(env, count, recipient_prefix="R"):
    """Create `count` build-and-ship orders, assemble, pay, hand off each.

    Returns the list of HANDED_TO_CARRIER orders.
    """
    orders = []
    for i in range(count):
        order = create_build_ship_order(
            env["store"]["id"],
            env["customer"],
            env["model"]["id"],
            recipient_name=f"{recipient_prefix}{i + 1}",
        )
        _, session_id = assemble_order(order["id"])
        orders.append(
            hand_over_order(
                order["id"],
                env["customer"]["id"],
                carrier_code="UPS",
                tracking_number=f"1Z{i + 1:03d}",
            )
        )
    return orders


def run_settlement(store_id, window_start, window_end):
    return get_success_data(
        api_client.run_consignment_settlement(
            store_id,
            {"window_start": window_start, "window_end": window_end},
            MANAGER,
        )
    )

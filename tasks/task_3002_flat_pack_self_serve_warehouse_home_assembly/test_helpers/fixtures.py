"""Composite setup helpers.

The test harness restarts the server before every test, so each helper builds
its preconditions from scratch using only PRD-declared endpoints. All helpers
use the lenient get_success_data() validator so setup failures surface as
clear "Setup failed" assertions rather than confusing downstream errors.

Identity threading: Customer is the only entity-backed role (PRD §2.1), so
every customer-scoped call is made with make_customer_headers(customer["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_article_payload,
    create_assembly_job_payload,
    create_assembly_standard_payload,
    create_bin_stock_payload,
    create_carton_payload,
    create_customer_payload,
    create_delivery_booking_payload,
    create_delivery_slot_payload,
    create_reservation_payload,
    create_spare_part_claim_payload,
    create_store_payload,
)
from .test_users import TEST_USERS, make_customer_headers

ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["store_ops_headers"]
COORD = TEST_USERS["delivery_coordinator_headers"]
PROVIDER = TEST_USERS["assembly_provider_headers"]

CLOCK_START = "2026-09-01T00:00:00Z"


def set_clock(to_iso8601=CLOCK_START):
    """Pin the logical clock (PRD §2.6)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_store(threshold=5, **overrides):
    # The store's threshold defaults to 5 per the PRD; tests that care about a
    # non-default threshold pass it explicitly and it is then sent in the body.
    if threshold != 5:
        overrides.setdefault("low_stock_threshold", threshold)
    payload = create_store_payload(**overrides)
    return get_success_data(api_client.create_store(payload, ADMIN))


def create_customer(member=False, **overrides):
    customer = get_success_data(api_client.create_customer(create_customer_payload(**overrides), OPS))
    if member:
        customer = get_success_data(api_client.enroll_customer(customer["id"], OPS))
    return customer


def cust_headers(customer):
    return make_customer_headers(customer["id"])


def create_article(**overrides):
    return get_success_data(api_client.create_article(create_article_payload(**overrides), ADMIN))


def register_carton(article_id, seq=1, weight_kg=5, volume_m3=0.05, **overrides):
    payload = create_carton_payload(
        carton_seq=seq, weight_kg=weight_kg, volume_m3=volume_m3, **overrides
    )
    return get_success_data(api_client.create_carton(article_id, payload, ADMIN))


def create_stock(store_id, carton_id, on_hand=5):
    payload = create_bin_stock_payload(store_id=store_id, carton_id=carton_id, on_hand=on_hand)
    return get_success_data(api_client.create_bin_stock(payload, OPS))


def create_assembly_standard(article_id, minutes_per_unit=30, **overrides):
    payload = create_assembly_standard_payload(
        article_id=article_id, minutes_per_unit=minutes_per_unit, **overrides
    )
    return get_success_data(api_client.create_assembly_standard(payload, ADMIN))


def create_order(customer, store_id):
    return get_success_data(api_client.create_order({"store_id": store_id}, cust_headers(customer)))


def add_line(customer, order_id, article_id, qty=1):
    return get_success_data(
        api_client.add_order_line(order_id, {"article_id": article_id, "qty": qty}, cust_headers(customer))
    )


def checkout(customer, order_id, **payload):
    return get_success_data(api_client.checkout_order(order_id, payload, cust_headers(customer)))


def pickup_complete(order_id):
    return get_success_data(api_client.pickup_complete(order_id, OPS))


def create_delivery_slot(store_id, zone="ZONE_A", capacity_weight_kg=100,
                         capacity_volume_m3=2.0, service_date="2026-09-10", **overrides):
    payload = create_delivery_slot_payload(
        store_id=store_id, zone=zone, capacity_weight_kg=capacity_weight_kg,
        capacity_volume_m3=capacity_volume_m3, service_date=service_date, **overrides
    )
    return get_success_data(api_client.create_delivery_slot(payload, COORD))


def create_booking(customer, order_id, slot_id, expected_slot_version,
                   access_type="ELEVATOR", floor=1):
    payload = create_delivery_booking_payload(
        slot_id=slot_id, access_type=access_type, floor=floor,
        expected_slot_version=expected_slot_version,
    )
    return get_success_data(
        api_client.create_delivery_booking(order_id, payload, cust_headers(customer))
    )


def current_slot_version(slot_id):
    return get_success_data(api_client.get_delivery_slot(slot_id, COORD))["version"]


def create_assembly_job(customer, order_id, provider_id="CREW-A",
                        window_start="2026-09-10T10:00:00Z",
                        window_end="2026-09-10T12:00:00Z"):
    payload = create_assembly_job_payload(
        provider_id=provider_id, window_start=window_start, window_end=window_end
    )
    return get_success_data(
        api_client.create_assembly_job(order_id, payload, cust_headers(customer))
    )


def create_claim(customer, article_id, value=100, **overrides):
    payload = create_spare_part_claim_payload(
        article_id=article_id, part_value_cents=value, **overrides
    )
    return get_success_data(api_client.create_spare_part_claim(payload, cust_headers(customer)))


def create_standalone_reservation(customer, store_id, article_id, qty=1):
    payload = create_reservation_payload(store_id=store_id, article_id=article_id, qty=qty)
    return get_success_data(api_client.create_reservation(payload, cust_headers(customer)))


def create_return(customer, order_id=None):
    payload = {} if order_id is None else {"order_id": order_id}
    return get_success_data(api_client.create_return(payload, cust_headers(customer)))


def add_return_line(customer, return_id, article_id, qty=1, assembly_state="UNOPENED",
                    order_line_id=None):
    payload = {"article_id": article_id, "qty": qty, "assembly_state": assembly_state}
    if order_line_id is not None:
        payload["order_line_id"] = order_line_id
    return get_success_data(api_client.add_return_line(return_id, payload, cust_headers(customer)))


def submit_return(customer, return_id):
    return get_success_data(api_client.submit_return(return_id, cust_headers(customer)))


def grade_line(return_id, line_id, grade):
    return get_success_data(api_client.grade_return_line(return_id, line_id, {"condition_grade": grade}, OPS))


def settle_return(return_id):
    return get_success_data(api_client.settle_return(return_id, OPS))


# ---------------------------------------------------------------------------
# Higher-level composites
# ---------------------------------------------------------------------------

def setup_store_and_customer(member=False, threshold=5):
    """Clock pinned, one store, one customer. Returns (store, customer)."""
    set_clock()
    store = create_store(threshold=threshold)
    customer = create_customer(member=member)
    return store, customer


def setup_article_with_stock(store, on_hand=5, price_cents=1000, cartons=None,
                             category="ACCESSORY", pick_policy="SELF_SERVE",
                             register_standard_minutes=None, **article_overrides):
    """Article with carton(s) and one bin-stock row per carton in the store.

    cartons: list of (weight_kg, volume_m3, on_hand) tuples; defaults to a
    single 5 kg / 0.05 m3 carton with on_hand units.
    Returns (article, cartons_list, bin_stocks_list).
    """
    article = create_article(category=category, pick_policy=pick_policy,
                             price_cents=price_cents, **article_overrides)
    if cartons is None:
        cartons = [(5, 0.05, on_hand)]
    carton_rows, stock_rows = [], []
    for i, (w, v, oh) in enumerate(cartons, start=1):
        c = register_carton(article["id"], seq=i, weight_kg=w, volume_m3=v)
        carton_rows.append(c)
        stock_rows.append(create_stock(store["id"], c["id"], on_hand=oh))
    if register_standard_minutes is not None:
        create_assembly_standard(article["id"], minutes_per_unit=register_standard_minutes)
    return article, carton_rows, stock_rows


def setup_paid_order(customer, store, lines, fulfillment_channel=None, **checkout_overrides):
    """DRAFT order + lines + checkout -> PAID. lines: list of (article, qty).
    Returns (order, order_lines)."""
    order = create_order(customer, store["id"])
    order_lines = [add_line(customer, order["id"], a["id"], qty) for a, qty in lines]
    payload = dict(checkout_overrides)
    if fulfillment_channel is not None:
        payload["fulfillment_channel"] = fulfillment_channel
    order = checkout(customer, order["id"], **payload)
    return order, order_lines


def setup_fulfilled_order(customer, store, lines, **checkout_overrides):
    """PAID CARRYOUT order walked to FULFILLED. Returns (order, order_lines)."""
    order, order_lines = setup_paid_order(customer, store, lines, **checkout_overrides)
    order = pickup_complete(order["id"])
    return order, order_lines


def setup_in_progress_job(customer, store, article, qty=1,
                          provider_id="CREW-A",
                          window_start="2026-09-10T10:00:00Z",
                          window_end="2026-09-10T12:00:00Z"):
    """FULFILLED order for one requires_assembly article + job DISPATCHED and
    started (IN_PROGRESS). Returns (order, order_lines, job)."""
    order, order_lines = setup_fulfilled_order(customer, store, [(article, qty)])
    job = create_assembly_job(customer, order["id"], provider_id=provider_id,
                              window_start=window_start, window_end=window_end)
    get_success_data(api_client.dispatch_assembly_job(job["id"], PROVIDER))
    job = get_success_data(api_client.start_assembly_job(job["id"], PROVIDER))
    return order, order_lines, job


def seed_member_points(customer, store, target_points):
    """Give a member exactly `target_points` by buying a 100*target_points-cent
    article and closing the order (PRD §3.3: floor(total_cents/100)).

    Creates its own throwaway article with enough stock. Returns the closed
    seed order."""
    seed_article, _, _ = setup_article_with_stock(
        store, on_hand=1, price_cents=100 * target_points,
        category="FURNITURE",
    )
    seed_order, _ = setup_fulfilled_order(customer, store, [(seed_article, 1)])
    seed_order = get_success_data(api_client.close_order(seed_order["id"], cust_headers(customer)))
    assert seed_order["points_earned"] == target_points, (
        f"Setup failed: expected {target_points} points, got {seed_order['points_earned']}"
    )
    return seed_order


def setup_delivery_paid_order(customer, store, article, qty=1):
    """DELIVERY-channel PAID order for one line. Returns (order, order_lines)."""
    return setup_paid_order(customer, store, [(article, qty)], fulfillment_channel="DELIVERY")


def setup_confirmed_booking(customer, store, article, slot, qty=1,
                            access_type="ELEVATOR", floor=1):
    """PAID DELIVERY order + CONFIRMED booking. Returns (order, booking)."""
    order, _ = setup_delivery_paid_order(customer, store, article, qty=qty)
    booking = create_booking(customer, order["id"], slot["id"],
                             expected_slot_version=current_slot_version(slot["id"]),
                             access_type=access_type, floor=floor)
    return order, booking

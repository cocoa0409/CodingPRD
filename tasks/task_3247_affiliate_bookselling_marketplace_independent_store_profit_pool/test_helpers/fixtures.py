"""Composite setup helpers.

The test harness restarts the server before every test, so every helper builds
its preconditions from scratch using only PRD-declared endpoints. All helpers
use get_success_data() so setup failures surface as clear errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START
from .factories import (
    create_book_payload,
    create_list_payload,
    create_order_payload,
    create_partner_payload,
    create_pool_distribution_payload,
    create_publisher_payload,
    create_return_payload,
    create_store_payload,
    create_ticket_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_store_manager_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
FINANCE = TEST_USERS["finance_ops_headers"]
WHOLESALER = TEST_USERS["wholesaler_ops_headers"]
SERVICE = TEST_USERS["customer_service_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock + catalog primitives
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=CLOCK_START):
    """Advance the logical clock (PRD §2.4)."""
    return api_client.set_clock(to_iso8601, ADMIN)


def create_publisher(**overrides):
    payload = create_publisher_payload(**overrides)
    return get_success_data(api_client.create_publisher(payload, ADMIN))


def create_book(publisher_id, **overrides):
    payload = create_book_payload(publisher_id, **overrides)
    return get_success_data(api_client.create_book(payload, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: affiliates
# ---------------------------------------------------------------------------

def create_store(**overrides):
    payload = create_store_payload(**overrides)
    return get_success_data(api_client.create_store(payload, ADMIN))


def create_active_store(**overrides):
    store = create_store(**overrides)
    store = get_success_data(
        api_client.store_action(store["id"], {"action": "activate"}, ADMIN)
    )
    return store


def create_partner(**overrides):
    payload = create_partner_payload(**overrides)
    return get_success_data(api_client.create_partner(payload, ADMIN))


def create_active_partner(**overrides):
    partner = create_partner(**overrides)
    partner = get_success_data(
        api_client.partner_action(partner["id"], {"action": "approve"}, ADMIN)
    )
    partner = get_success_data(
        api_client.partner_action(partner["id"], {"action": "activate"}, ADMIN)
    )
    return partner


# ---------------------------------------------------------------------------
# Tier 2: lists
# ---------------------------------------------------------------------------

def create_list_for_store(store_id, book_id=None, items=None, **overrides):
    if items is None:
        items = [{"book_id": book_id, "position": 1}] if book_id else []
    payload = create_list_payload(store_id, items=items, **overrides)
    return get_success_data(
        api_client.create_list(payload, make_store_manager_headers(store_id))
    )


def publish_list(list_id, store_id):
    return get_success_data(
        api_client.list_action(
            list_id, {"action": "publish"}, make_store_manager_headers(store_id)
        )
    )


# ---------------------------------------------------------------------------
# Tier 3: orders and lifecycle walks
# ---------------------------------------------------------------------------

def create_order(customer_id, book_id=None, lines=None, **overrides):
    if lines is None:
        lines = [{"book_id": book_id, "quantity": 1}]
    payload = create_order_payload(customer_id, lines=lines, **overrides)
    return get_success_data(
        api_client.create_order(payload, make_customer_headers(customer_id))
    )


def place_order(order_id, customer_id):
    return get_success_data(
        api_client.order_action(
            order_id, {"action": "place"}, make_customer_headers(customer_id)
        )
    )


def dispatch_order(order_id):
    return get_success_data(
        api_client.order_action(order_id, {"action": "dispatch"}, WHOLESALER)
    )


def ship_order(order_id):
    return get_success_data(
        api_client.order_action(order_id, {"action": "ship"}, WHOLESALER)
    )


def deliver_order(order_id):
    return get_success_data(
        api_client.order_action(order_id, {"action": "deliver"}, WHOLESALER)
    )


def create_placed_order(customer_id, book_id=None, lines=None, **overrides):
    """DRAFT order created and placed. Returns the placed order."""
    order = create_order(customer_id, book_id, lines=lines, **overrides)
    return place_order(order["id"], customer_id)


def create_delivered_order(customer_id, book_id=None, lines=None, **overrides):
    """Full DRAFT -> PLACED -> SENT_TO_WHOLESALER -> SHIPPED -> DELIVERED walk."""
    order = create_placed_order(customer_id, book_id, lines=lines, **overrides)
    dispatch_order(order["id"])
    ship_order(order["id"])
    return deliver_order(order["id"])


# ---------------------------------------------------------------------------
# Tier 4: returns
# ---------------------------------------------------------------------------

def open_return(order_id, customer_id, **overrides):
    payload = create_return_payload(**overrides)
    return get_success_data(
        api_client.create_return(order_id, payload, make_customer_headers(customer_id))
    )


def settle_return(return_id):
    """REQUESTED -> APPROVED -> RECEIVED -> CREDITED. Returns the credited return."""
    get_success_data(api_client.return_action(return_id, {"action": "approve"}, SERVICE))
    get_success_data(api_client.return_action(return_id, {"action": "receive"}, WHOLESALER))
    return get_success_data(
        api_client.return_action(return_id, {"action": "credit"}, FINANCE)
    )


def open_and_settle_return(order_id, customer_id, **overrides):
    ret = open_return(order_id, customer_id, **overrides)
    return settle_return(ret["id"])


# ---------------------------------------------------------------------------
# Tier 5: payouts
# ---------------------------------------------------------------------------

def list_store_payouts(store_id):
    return get_success_data(api_client.list_payouts(FINANCE, {"affiliate_store_id": store_id}))


def list_partner_payouts(partner_id):
    return get_success_data(
        api_client.list_payouts(FINANCE, {"affiliate_partner_id": partner_id})
    )


def payout_for_store(store_id, index=0):
    """The store's payout opened by the release sweep (fails loudly if absent)."""
    payouts = list_store_payouts(store_id)
    assert len(payouts) > index, f"expected payout[{index}] for store {store_id}"
    return payouts[index]


def payout_for_partner(partner_id, index=0):
    payouts = list_partner_payouts(partner_id)
    assert len(payouts) > index, f"expected payout[{index}] for partner {partner_id}"
    return payouts[index]


# ---------------------------------------------------------------------------
# Tier 6: pool distributions
# ---------------------------------------------------------------------------

def create_pool(**overrides):
    payload = create_pool_distribution_payload(**overrides)
    return get_success_data(api_client.create_pool_distribution(payload, FINANCE))


def calculate_pool(dist_id):
    return get_success_data(api_client.pool_action(dist_id, {"action": "calculate"}, FINANCE))


def approve_pool(dist_id, expected_version):
    return get_success_data(
        api_client.pool_action(
            dist_id,
            {"action": "approve", "expected_distribution_version": expected_version},
            FINANCE,
        )
    )


def distribute_pool(dist_id):
    return get_success_data(
        api_client.pool_action(dist_id, {"action": "distribute"}, FINANCE)
    )


def create_distributed_pool(**overrides):
    """DRAFT -> CALCULATED -> APPROVED -> DISTRIBUTED. Returns the final body."""
    dist = create_pool(**overrides)
    calc = calculate_pool(dist["id"])
    approve_pool(dist["id"], calc["version"])
    return distribute_pool(dist["id"])


# ---------------------------------------------------------------------------
# Ledger queries
# ---------------------------------------------------------------------------

def list_ledger(params=None):
    return get_success_data(api_client.list_ledger_entries(FINANCE, params))


def store_ledger(store_id, **extra):
    params = {"affiliate_store_id": store_id}
    params.update(extra)
    return list_ledger(params)


def partner_ledger(partner_id, **extra):
    params = {"affiliate_partner_id": partner_id}
    params.update(extra)
    return list_ledger(params)


# ---------------------------------------------------------------------------
# Composite scenario used by many corner probes: publisher + book + active
# store + customer, all at the startup clock.
# ---------------------------------------------------------------------------

def setup_catalog_and_store(
    customer_id="cust-c1",
    publisher_overrides=None,
    book_overrides=None,
    store_overrides=None,
    set_clock_to=CLOCK_START,
):
    """Returns (publisher, book, store). Store is ACTIVE."""
    if set_clock_to is not None:
        set_clock(set_clock_to)
    publisher = create_publisher(**(publisher_overrides or {}))
    book = create_book(publisher["id"], **(book_overrides or {}))
    store = create_active_store(**(store_overrides or {}))
    return publisher, book, store


def setup_delivered_order_scenario(
    customer_id="cust-c1",
    quantity=1,
    publisher_overrides=None,
    book_overrides=None,
    store_overrides=None,
    set_clock_to=CLOCK_START,
):
    """Publisher + book + ACTIVE store + one delivered order.

    Returns (publisher, book, store, order)."""
    publisher, book, store = setup_catalog_and_store(
        customer_id=customer_id,
        publisher_overrides=publisher_overrides,
        book_overrides=book_overrides,
        store_overrides=store_overrides,
        set_clock_to=set_clock_to,
    )
    order = create_delivered_order(
        customer_id,
        book["id"],
        lines=[{"book_id": book["id"], "quantity": quantity}],
        attributed_store_id=store["id"],
    )
    return publisher, book, store, order


def create_ticket_for_order(order_id, customer_id, **overrides):
    payload = create_ticket_payload(order_id, customer_id, **overrides)
    return get_success_data(
        api_client.create_ticket(payload, make_customer_headers(customer_id))
    )


def resolve_ticket(ticket_id, note="resolved"):
    get_success_data(api_client.ticket_action(ticket_id, {"action": "assign"}, SERVICE))
    return get_success_data(
        api_client.ticket_action(
            ticket_id, {"action": "resolve", "resolution_note": note}, SERVICE
        )
    )

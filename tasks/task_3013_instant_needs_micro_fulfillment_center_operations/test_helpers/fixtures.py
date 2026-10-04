"""Composite setup helpers.

The test harness restarts the server before every test, so each helper builds
its preconditions from scratch using only PRD-declared endpoints. Setup calls
go through the lenient `get_success_data` validator so a broken precondition
reports as a setup failure, not a confusing assertion failure. Ownership-gated
calls thread the real entity id through the per-instance header builders.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .test_users import (
    SITE_OPS_HEADERS,
    make_customer_headers,
    make_driver_headers,
    make_picker_headers,
)


# ---------------------------------------------------------------------------
# Low-level reads / clock
# ---------------------------------------------------------------------------

def set_clock(current_utc: str):
    return get_success_data(api_client.set_clock({"current_utc": current_utc}, SITE_OPS_HEADERS))


def read_site(site_id) -> dict:
    return get_success_data(api_client.get_site(site_id, SITE_OPS_HEADERS))


def read_customer(customer_id) -> dict:
    return get_success_data(api_client.get_customer(customer_id, SITE_OPS_HEADERS))


def read_order(order_id) -> dict:
    return get_success_data(api_client.get_order(order_id, SITE_OPS_HEADERS))


def read_balance(balance_id) -> dict:
    return get_success_data(api_client.get_inventory_balance(balance_id, SITE_OPS_HEADERS))


def read_pick_batch(batch_id) -> dict:
    return get_success_data(api_client.get_pick_batch(batch_id, SITE_OPS_HEADERS))


def read_delivery_bag(bag_id) -> dict:
    return get_success_data(api_client.get_delivery_bag(bag_id, SITE_OPS_HEADERS))


def read_membership(membership_id) -> dict:
    return get_success_data(api_client.get_membership(membership_id, SITE_OPS_HEADERS))


def read_replenish_order(replenish_order_id) -> dict:
    return get_success_data(api_client.get_replenish_order(replenish_order_id, SITE_OPS_HEADERS))


def list_stock_lots(params=None) -> list:
    resp = api_client.list_stock_lots(SITE_OPS_HEADERS, params=params)
    assert resp.status_code == 200, f"stock-lot list failed: {resp.text}"
    return resp.json()["data"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation
# ---------------------------------------------------------------------------

def create_site(**overrides) -> dict:
    return get_success_data(api_client.create_site(factories.create_site_payload(**overrides), SITE_OPS_HEADERS))


def create_product(**overrides) -> dict:
    return get_success_data(
        api_client.create_product(factories.create_product_payload(**overrides), SITE_OPS_HEADERS)
    )


def create_customer(**overrides) -> dict:
    """Register a customer. The registration call is a Customer-role call; the
    email uniqueness comes from the factory, so the shared placeholder identity
    is fine here — the customer does not exist before this call."""
    return get_success_data(
        api_client.create_customer(
            factories.create_customer_payload(**overrides),
            make_customer_headers("registration"),
        )
    )


def create_balance(site_id, product_id, min_par_level=0) -> dict:
    return get_success_data(
        api_client.create_inventory_balance(
            factories.create_inventory_balance_payload(site_id, product_id, min_par_level=min_par_level),
            SITE_OPS_HEADERS,
        )
    )


def seed_on_hand(balance_id, qty) -> dict:
    return get_success_data(
        api_client.create_stock_adjustment(
            balance_id, factories.create_receipt_adjustment_payload(qty), SITE_OPS_HEADERS
        )
    )


def create_picker(site_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_picker(factories.create_picker_payload(site_id, **overrides), SITE_OPS_HEADERS)
    )


def create_driver(site_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_driver(factories.create_driver_payload(site_id, **overrides), SITE_OPS_HEADERS)
    )


def create_membership(customer_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_membership(
            factories.create_membership_payload(customer_id, **overrides),
            make_customer_headers(customer_id),
        )
    )


def wallet_adjust(customer_id, amount_cents, reason="adjustment") -> dict:
    return get_success_data(
        api_client.create_wallet_adjustment(
            customer_id,
            factories.create_wallet_adjustment_payload(amount_cents, reason=reason),
            SITE_OPS_HEADERS,
        )
    )


def place_order(customer_id, site_id, lines, **overrides) -> dict:
    return get_success_data(
        api_client.create_order(
            factories.create_order_payload(customer_id, site_id, lines, **overrides),
            make_customer_headers(customer_id),
        )
    )


# ---------------------------------------------------------------------------
# Tier 2: replenishment chains
# ---------------------------------------------------------------------------

def create_replenish_order(site_id, lines, **overrides) -> dict:
    return get_success_data(
        api_client.create_replenish_order(
            factories.create_replenish_order_payload(site_id, lines, **overrides), SITE_OPS_HEADERS
        )
    )


def place_replenish_order(replenish_order_id) -> dict:
    return get_success_data(api_client.place_replenish_order(replenish_order_id, SITE_OPS_HEADERS))


def finalize_replenish_order(replenish_order_id, lot_expiries=None) -> dict:
    payload = {}
    if lot_expiries is not None:
        payload["lot_expiries"] = lot_expiries
    return get_success_data(api_client.finalize_replenish_order(replenish_order_id, payload, SITE_OPS_HEADERS))


def receive_perishable_stock(site_id, product_id, qty, expires_at, reference=None) -> dict:
    """Full DRAFT -> PLACED -> FINALIZED chain for one perishable line; returns
    the created StockLot row."""
    ro = create_replenish_order(
        site_id,
        [factories.replenish_line(product_id, qty)],
        reference=reference or factories._unique("PO"),
    )
    place_replenish_order(ro["id"])
    finalize_replenish_order(ro["id"], lot_expiries={product_id: expires_at})
    lots = list_stock_lots({"site_id": site_id, "product_id": product_id})
    assert lots, "expected a stock lot after finalize"
    # created_at comes from the logical clock, which is typically frozen within
    # a test, so list order cannot identify the new lot — match on expires_at.
    matching = [lot for lot in lots if lot["expires_at"].startswith(expires_at.rstrip("Z"))]
    assert matching, f"no lot with expires_at {expires_at}: {lots}"
    return matching[-1]


# ---------------------------------------------------------------------------
# Tier 3: order -> batch -> seal progression
# ---------------------------------------------------------------------------

def open_batch(site_id, picker_id) -> dict:
    return get_success_data(
        api_client.create_pick_batch(
            factories.create_pick_batch_payload(site_id, picker_id), SITE_OPS_HEADERS
        )
    )


def append_order(batch_id, order_id, picker_id) -> dict:
    return get_success_data(
        api_client.append_order_to_batch(batch_id, {"order_id": order_id}, make_picker_headers(picker_id))
    )


def seal_batch(batch_id, sealer_id) -> dict:
    return get_success_data(api_client.seal_pick_batch(batch_id, make_picker_headers(sealer_id)))


def setup_sealed_order(product_class="STANDARD", price_cents=500, qty=1, lot_expires_at=None):
    """Site + product (stocked) + customer + two pickers; one order driven to
    AWAITING_HANDOFF inside a SEALED batch.

    Returns (site, product, balance, customer, picker, sealer, order, batch).
    For PERISHABLE products, stock is received via a replenish finalize with
    `lot_expires_at` so a FRESH lot exists; other classes get a RECEIPT seed.
    """
    site = create_site()
    product = create_product(product_class=product_class, price_cents=price_cents)
    balance = create_balance(site["id"], product["id"])
    if product_class == "PERISHABLE":
        assert lot_expires_at, "perishable stock must arrive via a lot with an expiry"
        receive_perishable_stock(site["id"], product["id"], 50, lot_expires_at)
    else:
        seed_on_hand(balance["id"], 50)
    customer = create_customer()
    picker = create_picker(site["id"], name="Pat Picker")
    sealer = create_picker(site["id"], name="Sam Sealer")
    order = place_order(
        customer["id"], site["id"], [factories.order_line(product["id"], qty)]
    )
    batch = open_batch(site["id"], picker["id"])
    append_order(batch["id"], order["id"], picker["id"])
    batch = seal_batch(batch["id"], sealer["id"])
    order = read_order(order["id"])
    return site, product, balance, customer, picker, sealer, order, batch


# ---------------------------------------------------------------------------
# Tier 4: dispatch progression
# ---------------------------------------------------------------------------

def create_bag_for_order(order_id) -> dict:
    return get_success_data(
        api_client.create_delivery_bag(factories.create_delivery_bag_payload(order_id), SITE_OPS_HEADERS)
    )


def assign_bag(bag_id, driver_id=None) -> dict:
    payload = {} if driver_id is None else {"driver_id": driver_id}
    return get_success_data(api_client.assign_delivery_bag(bag_id, payload, SITE_OPS_HEADERS))


def setup_assigned_bag(product_class="STANDARD", price_cents=500, qty=1, lot_expires_at=None,
                       driver_name="Dee Driver", max_run_orders=4):
    """Sealed order + created delivery bag + selector/explicit assignment.

    Returns (site, product, balance, customer, sealer, order, batch, driver, bag).
    """
    site, product, balance, customer, picker, sealer, order, batch = setup_sealed_order(
        product_class=product_class, price_cents=price_cents, qty=qty, lot_expires_at=lot_expires_at
    )
    driver = create_driver(site["id"], name=driver_name, max_run_orders=max_run_orders)
    bag = create_bag_for_order(order["id"])
    bag = assign_bag(bag["id"])
    return site, product, balance, customer, sealer, order, batch, driver, bag


def deliver_bag(bag_id, driver_id) -> dict:
    """Depart + complete as the assigned driver; returns the completed bag."""
    get_success_data(api_client.depart_delivery_bag(bag_id, make_driver_headers(driver_id)))
    return get_success_data(api_client.complete_delivery_bag(bag_id, make_driver_headers(driver_id)))

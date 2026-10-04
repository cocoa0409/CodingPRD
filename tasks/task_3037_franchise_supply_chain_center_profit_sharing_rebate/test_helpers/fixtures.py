"""Composite setup helpers: multi-step fixture builders for domain scenarios.

All helpers build preconditions from scratch using only PRD-declared endpoints
and return entity dicts (validated with get_success_data) plus captured ids.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_capacity_plan_payload,
    create_compliance_agreement_payload,
    create_order_line_payload,
    create_price_book_payload,
    create_product_payload,
    create_promotion_payload,
    create_purchase_order_payload,
    create_route_payload,
    create_store_payload,
    create_supply_center_payload,
)
from .test_users import TEST_USERS, make_store_manager_headers

ADMIN = TEST_USERS["admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
ANY = TEST_USERS["any_headers"]

CLOCK_START = "2026-09-01T00:00:00Z"
WEEK_START = "2026-09-07T00:00:00Z"


def set_clock(to_iso8601=CLOCK_START):
    resp = api_client.set_clock(to_iso8601, ADMIN)
    get_success_data(resp)


def create_center(**overrides):
    resp = api_client.create_supply_center(create_supply_center_payload(**overrides), ADMIN)
    return get_success_data(resp)


def activate_center(center_id):
    resp = api_client.activate_supply_center(center_id, ADMIN)
    return get_success_data(resp)


def create_active_center(**overrides):
    """Create a center and activate it (with one product if none exists yet)."""
    center = create_center(**overrides)
    return center


def create_product(center_id, **overrides):
    resp = api_client.create_product(center_id, create_product_payload(**overrides), ADMIN)
    return get_success_data(resp)


def get_center_version(center_id):
    return get_success_data(api_client.get_supply_center(center_id, ANY))["version"]


def create_price_book(center_id, product_id, **overrides):
    """Create a price book, fetching the fresh center version for the OCC field."""
    payload = create_price_book_payload(
        product_id, get_center_version(center_id), **overrides
    )
    resp = api_client.create_price_book(center_id, payload, ADMIN)
    return get_success_data(resp)


def create_store(center_id, **overrides):
    resp = api_client.create_store(center_id, create_store_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_and_activate_agreement(center_id, store_id, **overrides):
    agr = get_success_data(
        api_client.create_compliance_agreement(
            center_id, store_id, create_compliance_agreement_payload(**overrides), ADMIN
        )
    )
    get_success_data(api_client.activate_compliance_agreement(center_id, store_id, agr["id"], ADMIN))
    return agr


def activate_store(center_id, store_id):
    """Activate a store, auto-provisioning an ACTIVE compliance agreement when the
    store has none (PRD §3.2 requires one for ONBOARDING -> ACTIVE)."""
    store = get_store(center_id, store_id)
    if store["status"] == "ONBOARDING" and not any(
        a["store_id"] == store_id and a["status"] == "ACTIVE"
        for a in get_success_data(api_client.list_compliance_agreements(center_id, ANY))
    ):
        create_and_activate_agreement(center_id, store_id)
    resp = api_client.activate_store(center_id, store_id, ADMIN)
    return get_success_data(resp)


def create_active_store(center_id, with_agreement=True, **overrides):
    """Create a store, optionally give it an ACTIVE compliance agreement, activate it.

    Returns the store dict. StoreManager headers for this store must be built via
    make_store_manager_headers(store["id"]).
    """
    store = create_store(center_id, **overrides)
    if with_agreement:
        create_and_activate_agreement(center_id, store["id"])
    return activate_store(center_id, store["id"])


def manager_headers(store_id):
    return make_store_manager_headers(store_id)


def get_store(center_id, store_id):
    return get_success_data(api_client.get_store(center_id, store_id, ANY))


def get_store_version(center_id, store_id):
    return get_store(center_id, store_id)["version"]


def create_draft_po(center_id, store_id, **overrides):
    resp = api_client.create_purchase_order(
        center_id, store_id, create_purchase_order_payload(**overrides), manager_headers(store_id)
    )
    return get_success_data(resp)


def add_line(center_id, store_id, order_id, product_id, quantity):
    resp = api_client.add_order_line(
        center_id, store_id, order_id,
        create_order_line_payload(product_id, quantity=quantity),
        manager_headers(store_id),
    )
    return get_success_data(resp)


def submit_po(center_id, store_id, order_id):
    """Submit a PO using the store's fresh version for the OCC field."""
    version = get_store_version(center_id, store_id)
    resp = api_client.submit_purchase_order(
        center_id, store_id, order_id, version, manager_headers(store_id)
    )
    return get_success_data(resp)


def confirm_po(center_id, order_id):
    return get_success_data(api_client.confirm_purchase_order(center_id, order_id, ADMIN))


def create_route(center_id, **overrides):
    resp = api_client.create_route(center_id, create_route_payload(**overrides), COORD)
    return get_success_data(resp)


def create_capacity_plan(center_id, **overrides):
    resp = api_client.create_capacity_plan(center_id, create_capacity_plan_payload(**overrides), ADMIN)
    return get_success_data(resp)


def get_capacity_plan(center_id, plan_id):
    return get_success_data(api_client.get_capacity_plan(center_id, plan_id, ANY))


def create_promotion(center_id, **overrides):
    resp = api_client.create_promotion(center_id, create_promotion_payload(**overrides), ADMIN)
    return get_success_data(resp)


def get_po(center_id, order_id):
    return get_success_data(api_client.get_purchase_order(center_id, order_id, ANY))


def list_lines(center_id, order_id):
    return get_success_data(api_client.list_order_lines(center_id, order_id, ANY))


# ---------------------------------------------------------------------------
# Composite scenarios
# ---------------------------------------------------------------------------

def setup_center_with_product_and_pricing(
    base_cost=1000,
    markup=0.15,
    center_capacity=100000,
    product_category="DOUGH",
    min_quantity=1,
    store_tier="STANDARD",
    **product_overrides,
):
    """Active center + one ACTIVE product + one ACTIVE price book.

    Returns (center, product, price_book).
    """
    set_clock()
    center = create_center(base_weekly_capacity_units=center_capacity)
    center_id = center["id"]
    product = create_product(center_id, category=product_category,
                             base_cost_cents_per_unit=base_cost, **product_overrides)
    activate_center(center_id)
    price_book = create_price_book(
        center_id, product["id"], markup_pct=markup, min_quantity=min_quantity,
        store_tier=store_tier,
    )
    return center, product, price_book


def setup_trading_store(base_cost=1000, markup=0.15, credit_limit=100000000,
                        center_capacity=100000, product_category="DOUGH",
                        **product_overrides):
    """Active center + product + price book + ACTIVE store (with compliance agreement).

    Returns (center, product, store).
    """
    center, product, _pb = setup_center_with_product_and_pricing(
        base_cost=base_cost, markup=markup, center_capacity=center_capacity,
        product_category=product_category, **product_overrides,
    )
    store = create_active_store(center["id"], credit_limit_cents=credit_limit)
    return center, product, store


def setup_draft_po_with_line(base_cost=1000, markup=0.15, quantity=10,
                             credit_limit=100000000, center_capacity=100000,
                             product_category="DOUGH", **product_overrides):
    """Trading store + DRAFT PO with a single line. Returns (center, product, store, po, line)."""
    center, product, store = setup_trading_store(
        base_cost=base_cost, markup=markup, credit_limit=credit_limit,
        center_capacity=center_capacity, product_category=product_category,
        **product_overrides,
    )
    center_id, store_id = center["id"], store["id"]
    po = create_draft_po(center_id, store_id)
    line = add_line(center_id, store_id, po["id"], product["id"], quantity)
    return center, product, store, po, line


def setup_submitted_po(base_cost=1000, markup=0.15, quantity=10,
                       credit_limit=100000000, center_capacity=100000,
                       product_category="DOUGH", with_capacity_plan=False,
                       with_route=False, truck_capacity=10000,
                       **product_overrides):
    """Trading store + SUBMITTED PO. Optionally with capacity plan and route.

    Returns a dict with keys: center, product, store, po, line, plan, route.
    plan/route are None unless requested.
    """
    center, product, store, po, line = setup_draft_po_with_line(
        base_cost=base_cost, markup=markup, quantity=quantity,
        credit_limit=credit_limit, center_capacity=center_capacity,
        product_category=product_category, **product_overrides,
    )
    center_id, store_id = center["id"], store["id"]
    plan = create_capacity_plan(center_id) if with_capacity_plan else None
    route = (create_route(center_id, assigned_store_ids=[store_id],
                          truck_capacity_units=truck_capacity)
             if with_route else None)
    submitted = submit_po(center_id, store_id, po["id"])
    return {
        "center": center, "product": product, "store": store,
        "po": submitted, "line": line, "plan": plan, "route": route,
    }


def setup_confirmed_po(base_cost=100, markup=0.0, quantity=10,
                       credit_limit=100000000, center_capacity=100000,
                       truck_capacity=10000, **product_overrides):
    """Trading store + CONFIRMED PO with capacity plan and route.

    Returns dict with center, product, store, po, line, plan, route.
    """
    ctx = setup_submitted_po(
        base_cost=base_cost, markup=markup, quantity=quantity,
        credit_limit=credit_limit, center_capacity=center_capacity,
        with_capacity_plan=True, with_route=True, truck_capacity=truck_capacity,
        **product_overrides,
    )
    ctx["po"] = confirm_po(ctx["center"]["id"], ctx["po"]["id"])
    return ctx

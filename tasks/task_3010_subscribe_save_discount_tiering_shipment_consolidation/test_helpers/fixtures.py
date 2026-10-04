"""Composite setup helpers.

Every helper builds its preconditions from scratch against an empty database
using only PRD-declared endpoints, and uses the lenient get_success_data()
validator so a setup failure surfaces as "Setup failed", not an assertion deep
inside a test. Ownership-gated calls always use make_customer_headers with the
real Customer id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_CADENCE_MONTHS,
    DEFAULT_CLOCK_ISO,
    DEFAULT_DELIVERY_MONTH,
    DEFAULT_PREFERRED_DAY,
    DEFAULT_START_DATE,
    DEFAULT_STOCK_UNITS,
    REGION,
)
from .factories import (
    create_coupon_payload,
    create_customer_payload,
    create_generate_plans_payload,
    create_inventory_placement_payload,
    create_price_event_payload,
    create_product_payload,
    create_receive_payload,
    create_subscription_payload,
)
from .test_users import (
    make_customer_headers,
    make_platform_admin_headers,
    make_support_agent_headers,
)

ADMIN = make_platform_admin_headers()
SUPPORT = make_support_agent_headers()


def add_price(product, price_cents, effective_from="2026-09-01T00:00:00Z"):
    """Append a price event to a product. Returns the created PriceEvent."""
    resp = api_client.create_price_event(
        product["id"],
        create_price_event_payload(price_cents, effective_from),
        ADMIN,
    )
    return get_success_data(resp)


def create_product(units=DEFAULT_STOCK_UNITS, price_cents=1000,
                   effective_from="2026-09-01T00:00:00Z", region=REGION,
                   **product_overrides):
    """Convenience: create a stocked, priced product. Returns (product, placement)."""
    return create_stocked_product(
        price_cents=price_cents, effective_from=effective_from,
        units=units, region=region, **product_overrides,
    )


def set_clock(to_iso8601=DEFAULT_CLOCK_ISO):
    """Pin the logical clock (PRD §2.4). Returns the response data."""
    resp = api_client.set_clock(to_iso8601, ADMIN)
    return get_success_data(resp)


def create_customer(preferred_delivery_day=DEFAULT_PREFERRED_DAY, region=REGION, **overrides):
    payload = create_customer_payload(
        region=region, preferred_delivery_day=preferred_delivery_day, **overrides,
    )
    resp = api_client.create_customer(payload, ADMIN)
    return get_success_data(resp)


def create_product(region=REGION, **overrides):
    """Create a bare catalog product (no price event, no placement)."""
    resp = api_client.create_product(
        create_product_payload(region=region, **overrides), ADMIN,
    )
    return get_success_data(resp)


def add_price(product_id, price_cents=1000, effective_from="2026-09-01T00:00:00Z"):
    """Append a price event to a product."""
    resp = api_client.create_price_event(
        product_id, create_price_event_payload(price_cents, effective_from), ADMIN,
    )
    return get_success_data(resp)


def create_stocked_product(
    price_cents=1000,
    effective_from="2026-09-01T00:00:00Z",
    units=DEFAULT_STOCK_UNITS,
    region=REGION,
    **product_overrides,
):
    """Create a product, append its first price event, create a placement for
    (product, region), and receive `units` of stock (pass units=0 to skip the
    receive call). Returns (product, placement)."""
    product = get_success_data(api_client.create_product(
        create_product_payload(region=region, **product_overrides), ADMIN,
    ))
    if price_cents is not None:
        get_success_data(api_client.create_price_event(
            product["id"],
            create_price_event_payload(price_cents, effective_from),
            ADMIN,
        ))
        product = get_success_data(api_client.get_product(product["id"], ADMIN))
    placement = get_success_data(api_client.create_inventory_placement(
        create_inventory_placement_payload(product_id=product["id"], region=region),
        ADMIN,
    ))
    if units > 0:
        get_success_data(api_client.receive_inventory(
            placement["id"], create_receive_payload(units), ADMIN,
        ))
        placement = get_success_data(
            api_client.get_inventory_placement(placement["id"], ADMIN),
        )
    return product, placement


def create_subscription(
    customer,
    product,
    cadence_months=DEFAULT_CADENCE_MONTHS,
    quantity=1,
    start_date=DEFAULT_START_DATE,
    **overrides,
):
    """Create a subscription as the owning customer. Returns the Subscription."""
    headers = make_customer_headers(customer["id"])
    payload = create_subscription_payload(
        customer["id"], product["id"],
        cadence_months=cadence_months, quantity=quantity, start_date=start_date,
        **overrides,
    )
    resp = api_client.create_subscription(payload, headers)
    return get_success_data(resp)


def generate_plan_for(customer, delivery_month=DEFAULT_DELIVERY_MONTH):
    """Run monthly plan generation and return this customer's generated plan."""
    headers = make_customer_headers(customer["id"])
    get_success_data(api_client.generate_plans(
        create_generate_plans_payload(delivery_month), ADMIN,
    ))
    resp = api_client.list_customer_plans(customer["id"], headers)
    plans = get_success_data(resp)
    assert plans, "Setup failed: no delivery plan generated for customer"
    return plans[0]


def setup_customer_with_plan(
    num_subscriptions=1,
    price_cents=1000,
    quantity=1,
    units=DEFAULT_STOCK_UNITS,
    delivery_month=DEFAULT_DELIVERY_MONTH,
    start_date=DEFAULT_START_DATE,
    subscription_overrides_list=None,
    **product_overrides,
):
    """Customer + stocked priced product + N ACTIVE subscriptions + the
    generated OPEN plan for `delivery_month`.

    subscription_overrides_list: optional list of per-subscription payload
    overrides (e.g. a price cap on exactly one subscription).

    Returns (customer, product, placement, subscriptions, plan).
    """
    set_clock()
    customer = create_customer()
    product, placement = create_stocked_product(
        price_cents=price_cents, units=units, **product_overrides,
    )
    subscriptions = []
    for i in range(num_subscriptions):
        overrides = (
            subscription_overrides_list[i] if subscription_overrides_list else {}
        )
        subscriptions.append(create_subscription(
            customer, product, quantity=quantity, start_date=start_date, **overrides,
        ))
    plan = generate_plan_for(customer, delivery_month)
    return customer, product, placement, subscriptions, plan


def list_plan_lines(plan, as_customer=None):
    """List a plan's lines (as its owning customer by default)."""
    headers = make_customer_headers(as_customer["id"]) if as_customer else ADMIN
    resp = api_client.list_plan_lines(plan["id"], headers)
    return get_success_data(resp)


def get_plan(plan_id, as_customer=None):
    headers = make_customer_headers(as_customer["id"]) if as_customer else ADMIN
    return get_success_data(api_client.get_plan(plan_id, headers))


def lock_plan(plan, customer):
    resp = api_client.lock_plan(plan["id"], make_customer_headers(customer["id"]))
    return get_success_data(resp)


def ship_plan(plan):
    return get_success_data(api_client.ship_plan(plan["id"], ADMIN))


def deliver_plan(plan):
    return get_success_data(api_client.mark_plan_delivered(plan["id"], ADMIN))


def setup_locked_plan(**kwargs):
    """OPEN plan -> LOCKED. Returns (customer, product, placement, subs, locked_plan)."""
    customer, product, placement, subs, plan = setup_customer_with_plan(**kwargs)
    locked = lock_plan(plan, customer)
    return customer, product, placement, subs, locked


def setup_shipped_plan(**kwargs):
    """Through SHIPPED. Returns (customer, product, placement, subs, shipped_plan)."""
    customer, product, placement, subs, locked = setup_locked_plan(**kwargs)
    shipped = ship_plan(locked)
    return customer, product, placement, subs, shipped


def setup_delivered_plan(**kwargs):
    """Through DELIVERED. Returns (customer, product, placement, subs, delivered_plan)."""
    customer, product, placement, subs, shipped = setup_shipped_plan(**kwargs)
    delivered = deliver_plan(shipped)
    return customer, product, placement, subs, delivered


def report_damage_claim(plan, customer, damaged_line_ids):
    """Report a damage claim on a DELIVERED plan as its owning customer."""
    resp = api_client.create_damage_claim(
        plan["id"], {"damaged_line_ids": list(damaged_line_ids)},
        make_customer_headers(customer["id"]),
    )
    return get_success_data(resp, expected_status=201)


def setup_reported_claim(**kwargs):
    """Full chain: delivered plan + REPORTED damage claim over the first line.
    Returns (customer, product, placement, subs, plan, line, claim)."""
    customer, product, placement, subs, plan = setup_delivered_plan(**kwargs)
    line = list_plan_lines(plan, as_customer=customer)[0]
    claim = report_damage_claim(plan, customer, [line["id"]])
    return customer, product, placement, subs, plan, line, claim


def cancel_subscription_and_get_offer(subscription, customer):
    """Cancel a subscription and fetch its freshly minted retention offer."""
    headers = make_customer_headers(customer["id"])
    get_success_data(api_client.cancel_subscription(subscription["id"], headers))
    offers = get_success_data(
        api_client.list_subscription_offers(subscription["id"], headers),
    )
    assert offers, "Setup failed: no retention offer after cancel"
    return offers[0]


def create_coupon(code, **overrides):
    resp = api_client.create_coupon(create_coupon_payload(code, **overrides), ADMIN)
    return get_success_data(resp, expected_status=201)


def attach_coupon(plan, customer, coupon_code):
    headers = make_customer_headers(customer["id"])
    return api_client.attach_coupon(plan["id"], {"coupon_code": coupon_code}, headers)


def get_placement(placement_id):
    return get_success_data(api_client.get_inventory_placement(placement_id, ADMIN))


def get_product(product_id):
    return get_success_data(api_client.get_product(product_id, ADMIN))


def get_customer_by_id(customer_id):
    return get_success_data(api_client.get_customer(customer_id, ADMIN))


def get_subscription_by_id(subscription_id, customer=None):
    headers = make_customer_headers(customer["id"]) if customer else ADMIN
    return get_success_data(api_client.get_subscription(subscription_id, headers))


def list_notifications(customer, notification_type=None):
    headers = make_customer_headers(customer["id"])
    params = {"notification_type": notification_type} if notification_type else None
    return get_success_data(
        api_client.list_customer_notifications(customer["id"], headers, params=params),
    )

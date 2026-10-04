"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch out of public endpoints, because
each individual test starts against an empty database. Setup steps use
``get_success_data()`` so a broken precondition reports itself as a setup failure
rather than as a confusing assertion failure in the test body.

Identity threading: after a helper creates a ``Vendor`` or a ``Customer``, every
ownership-gated call in that helper uses the per-instance header builder with the
real entity id — never the shared role constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_vendor_headers,
)

MERCH = TEST_USERS["merchandiser_headers"]
PLANNER = TEST_USERS["inventory_planner_headers"]
DOCK = TEST_USERS["cross_dock_headers"]
CS = TEST_USERS["customer_service_headers"]
ANY = TEST_USERS["any_headers"]

CLOCK_START = TEST_DEFAULTS["CLOCK_START"]


# ═══════════════════════════════════════════════════════
# Tier 1: State progression
# ═══════════════════════════════════════════════════════

def set_clock(current_utc=CLOCK_START):
    """Set the logical clock. Returns the value the server reports back."""
    res = api_client.set_clock(current_utc, MERCH)
    return get_success_data(res)["current_utc"]


def create_vendor(vendor_tier="STANDARD", legal_name=TEST_DEFAULTS["LEGAL_NAME"]):
    """Register a vendor; returns the created Vendor (standing EXCELLENT, version 1)."""
    res = api_client.create_vendor(
        {"legal_name": legal_name, "vendor_tier": vendor_tier}, MERCH)
    return get_success_data(res)


def create_shop(vendor_id, shop_name=TEST_DEFAULTS["SHOP_NAME"]):
    """Create a DRAFT shop under a vendor."""
    res = api_client.create_shop(
        {"vendor_id": vendor_id, "shop_name": shop_name}, MERCH)
    return get_success_data(res)


def create_event(shop_id, event_title=TEST_DEFAULTS["EVENT_TITLE"],
                 starts_at="2026-09-01T00:00:00Z", ends_at="2026-09-02T00:00:00Z",
                 ship_time_quote_days=14):
    """Create a DRAFT event under a shop."""
    res = api_client.create_event({
        "shop_id": shop_id,
        "event_title": event_title,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "ship_time_quote_days": ship_time_quote_days,
    }, MERCH)
    return get_success_data(res)


def create_listing(event_id, vendor_sku="NW-SKU-1", unit_price_cents=300,
                   vendor_unit_cost_cents=180, allocation_units=10,
                   reveal_at="2026-09-01T00:00:00Z"):
    """Merchandise a DRAFT listing into an event."""
    res = api_client.create_listing({
        "event_id": event_id,
        "vendor_sku": vendor_sku,
        "unit_price_cents": unit_price_cents,
        "vendor_unit_cost_cents": vendor_unit_cost_cents,
        "allocation_units": allocation_units,
        "reveal_at": reveal_at,
    }, MERCH)
    return get_success_data(res)


def schedule_event(event_id):
    return get_success_data(api_client.schedule_event(event_id, MERCH))


def launch_event(event_id):
    return get_success_data(api_client.launch_event(event_id, MERCH))


def create_customer(email="buyer@example.com", full_name="Casey Buyer"):
    res = api_client.create_customer({"email": email, "full_name": full_name}, ANY)
    return get_success_data(res)


def create_order(customer_id):
    """Open an empty AGGREGATING order for a customer, acting as that customer."""
    res = api_client.create_order({"customer_id": customer_id},
                                  make_customer_headers(customer_id))
    return get_success_data(res)


def add_line(order_id, customer_id, listing_id, quantity):
    res = api_client.add_order_line(
        order_id, {"listing_id": listing_id, "quantity": quantity},
        make_customer_headers(customer_id))
    return get_success_data(res)


def submit_order(order_id, customer_id):
    res = api_client.submit_order(order_id, make_customer_headers(customer_id))
    return get_success_data(res)


# ═══════════════════════════════════════════════════════
# Tier 2: Entity hierarchy
# ═══════════════════════════════════════════════════════

def setup_vendor_shop_event(vendor_tier="STANDARD", ship_time_quote_days=14,
                            event_starts="2026-09-01T00:00:00Z",
                            event_ends="2026-09-02T00:00:00Z",
                            legal_name=TEST_DEFAULTS["LEGAL_NAME"],
                            shop_name=TEST_DEFAULTS["SHOP_NAME"],
                            event_title=TEST_DEFAULTS["EVENT_TITLE"]):
    """Vendor + shop + DRAFT event. Returns (vendor, shop, event)."""
    vendor = create_vendor(vendor_tier=vendor_tier, legal_name=legal_name)
    shop = create_shop(vendor["id"], shop_name=shop_name)
    event = create_event(shop["id"], event_title=event_title,
                         starts_at=event_starts, ends_at=event_ends,
                         ship_time_quote_days=ship_time_quote_days)
    return vendor, shop, event


def setup_live_event_with_listing(vendor_tier="STANDARD", ship_time_quote_days=14,
                                  unit_price_cents=300, vendor_unit_cost_cents=180,
                                  allocation_units=10, vendor_sku="NW-SKU-1",
                                  reveal_at="2026-09-01T00:00:00Z",
                                  event_starts="2026-09-01T00:00:00Z",
                                  event_ends="2026-09-02T00:00:00Z",
                                  legal_name=TEST_DEFAULTS["LEGAL_NAME"]):
    """Vendor + shop + event scheduled and launched + ACTIVE listing.

    Returns (vendor, shop, event, listing).
    """
    vendor, shop, event = setup_vendor_shop_event(
        vendor_tier=vendor_tier, ship_time_quote_days=ship_time_quote_days,
        event_starts=event_starts, event_ends=event_ends, legal_name=legal_name)
    listing = create_listing(
        event["id"], vendor_sku=vendor_sku, unit_price_cents=unit_price_cents,
        vendor_unit_cost_cents=vendor_unit_cost_cents,
        allocation_units=allocation_units, reveal_at=reveal_at)
    schedule_event(event["id"])
    launch_event(event["id"])
    return vendor, shop, event, listing


def fresh_vendor(vendor_id):
    """Re-read a vendor so the caller holds its current ``version``.

    Creating or issuing a buy increments the vendor's ``version`` (PRD §3.4), so a
    cached ``Vendor`` dict is a stale view the moment anything else touches the
    vendor. Every ``expected_vendor_version`` guard must be built from this read.
    """
    return get_success_data(api_client.get_vendor(vendor_id, ANY))


def create_buy(vendor, event, expected_vendor_version=None):
    """Create a DRAFT buy. Defaults the version guard to the vendor's *current*
    version, re-read from the API so a cached view cannot make the guard stale."""
    if expected_vendor_version is None:
        version = fresh_vendor(vendor["id"])["version"]
    else:
        version = expected_vendor_version
    res = api_client.create_purchase_order({
        "vendor_id": vendor["id"],
        "event_id": event["id"],
        "expected_vendor_version": version,
    }, PLANNER)
    return get_success_data(res)


def add_buy_line(po_id, listing_id, quantity_ordered):
    res = api_client.add_po_line(
        po_id, {"listing_id": listing_id, "quantity_ordered": quantity_ordered},
        PLANNER)
    return get_success_data(res)


def issue_buy(po_id, vendor, allow_probation_vendor=None):
    payload = {"expected_vendor_version": fresh_vendor(vendor["id"])["version"]}
    if allow_probation_vendor is not None:
        payload["allow_probation_vendor"] = allow_probation_vendor
    res = api_client.issue_purchase_order(po_id, payload, PLANNER)
    return get_success_data(res)


def confirm_line(confirmation_id, vendor_id, confirm_units):
    res = api_client.confirm_line(
        confirmation_id, {"confirm_units": confirm_units},
        make_vendor_headers(vendor_id))
    return get_success_data(res)


def report_shipment(po_id, vendor_id, quantity_shipped, allocations,
                    carrier_tracking_code="TRK-1",
                    shipped_at="2026-09-01T00:00:00Z"):
    res = api_client.create_shipment({
        "purchase_order_id": po_id,
        "quantity_shipped": quantity_shipped,
        "carrier_tracking_code": carrier_tracking_code,
        "shipped_at": shipped_at,
        "allocations": allocations,
    }, make_vendor_headers(vendor_id))
    return get_success_data(res)


def receive_shipment(shipment_id, arrived_at, bucket_units_reported=None):
    payload = {"arrived_at": arrived_at}
    if bucket_units_reported is not None:
        payload["bucket_units_reported"] = bucket_units_reported
    res = api_client.receive_shipment(shipment_id, payload, DOCK)
    return get_success_data(res)


def capture_order(order_id):
    return get_success_data(api_client.capture_order(order_id, PLANNER))


def close_short_buy(po_id, force_close=True):
    res = api_client.close_short_purchase_order(
        po_id, {"force_close": force_close}, PLANNER)
    return get_success_data(res)


def consolidate_order(order_id):
    order = get_success_data(api_client.get_order(order_id, ANY))
    res = api_client.consolidate_order(
        order_id, {"expected_order_version": order["version"]}, DOCK)
    return get_success_data(res)


def refund_order(order_id, write_off_full_line=False):
    res = api_client.refund_order(
        order_id, {"write_off_full_line": write_off_full_line}, PLANNER)
    return get_success_data(res)


# ═══════════════════════════════════════════════════════
# Tier 3: Full lifecycle shortcuts
# ═══════════════════════════════════════════════════════

def setup_order_with_submitted_line(customer_email="buyer@example.com",
                                    quantity=2, **listing_overrides):
    """Vendor + shop + LIVE event + ACTIVE listing + customer + submitted order.

    Returns (vendor, shop, event, listing, customer, order, line).
    """
    vendor, shop, event, listing = setup_live_event_with_listing(**listing_overrides)
    customer = create_customer(email=customer_email)
    order = create_order(customer["id"])
    line = add_line(order["id"], customer["id"], listing["id"], quantity)
    submit_order(order["id"], customer["id"])
    return vendor, shop, event, listing, customer, order, line


def setup_order_line_bought_confirmed(confirm_units=None, quantity=4,
                                      **listing_overrides):
    """Full path through a confirmed buy: order line submitted, buy issued, vendor
    confirms the line.

    Returns (vendor, shop, event, listing, customer, order, line, po).
    """
    vendor, shop, event, listing, customer, order, line = \
        setup_order_with_submitted_line(quantity=quantity, **listing_overrides)
    po = create_buy(vendor, event)
    add_buy_line(po["id"], listing["id"], quantity)
    issue_buy(po["id"], vendor)
    units = quantity if confirm_units is None else confirm_units
    confirm_line(line["id"], vendor["id"], units)
    return vendor, shop, event, listing, customer, order, line, po


def setup_order_delivered(quantity=2, **listing_overrides):
    """Order through confirm → shipment → receive → capture → consolidate → seal →
    dispatch → deliver.

    Returns a dict of every entity the scenario produced.
    """
    vendor, shop, event, listing, customer, order, line, po = \
        setup_order_line_bought_confirmed(confirm_units=quantity,
                                          quantity=quantity, **listing_overrides)
    shipment = report_shipment(
        po["id"], vendor["id"], quantity,
        [{"listing_id": listing["id"], "quantity": quantity}])
    receive_shipment(shipment["id"], "2026-09-01T09:00:00Z", quantity)
    capture_order(order["id"])
    parcel = consolidate_order(order["id"])
    sealed = get_success_data(api_client.seal_parcel(parcel["id"], DOCK))
    get_success_data(api_client.dispatch_parcel(parcel["id"], DOCK))
    get_success_data(api_client.deliver_parcel(parcel["id"], DOCK))
    return {
        "vendor": vendor, "shop": shop, "event": event, "listing": listing,
        "customer": customer, "order": order, "line": line, "po": po,
        "shipment": shipment, "parcel": sealed,
    }


def setup_dispatched_order(quantity=2, **listing_overrides):
    """Like ``setup_order_delivered`` but stops at DISPATCHED."""
    vendor, shop, event, listing, customer, order, line, po = \
        setup_order_line_bought_confirmed(confirm_units=quantity,
                                          quantity=quantity, **listing_overrides)
    shipment = report_shipment(
        po["id"], vendor["id"], quantity,
        [{"listing_id": listing["id"], "quantity": quantity}])
    receive_shipment(shipment["id"], "2026-09-01T09:00:00Z", quantity)
    capture_order(order["id"])
    parcel = consolidate_order(order["id"])
    sealed = get_success_data(api_client.seal_parcel(parcel["id"], DOCK))
    get_success_data(api_client.dispatch_parcel(parcel["id"], DOCK))
    return {
        "vendor": vendor, "shop": shop, "event": event, "listing": listing,
        "customer": customer, "order": order, "line": line, "po": po,
        "shipment": shipment, "parcel": sealed,
    }


# ═══════════════════════════════════════════════════════
# Tier 4: Accumulation / threshold targeting
# ═══════════════════════════════════════════════════════

def setup_buy_with_fill_rate(vendor, event, listing, ordered, shipped, confirm_units=None,
                             line=None, carrier_suffix=""):
    """A buy issued and (usually) closed short with a controlled rolling fill rate.

    ``shipped`` units are reported against the buy before it is closed short, so the
    buy's realised ratio is exactly ``shipped / ordered``. A buy that is fully shipped
    is filled instead of closed short, which is what admits a buy whose ratio is 1.0000.

    The buy is issued *before* the vendor confirms: issuing stamps the window, so the
    effective fill-rate floor has ramped to zero elapsed and the confirmation is not
    blocked by it, whereas a confirmation on a still-DRAFT buy is compared against the
    vendor's full floor. ``confirm_units`` defaults to the units actually shipped,
    because reported units are bounded by a line's ``quantity_confirmed`` (PRD §3.5).

    Returns a fresh vendor read, because issuing bumps the vendor's version.
    """
    current = fresh_vendor(vendor["id"])
    po = create_buy(current, event)
    add_buy_line(po["id"], listing["id"], ordered)
    issue_buy(po["id"], current)
    vendor_id = vendor["id"]
    units = shipped if confirm_units is None else confirm_units
    targets = [line] if line is not None else get_success_data(
        api_client.list_confirmations(ANY, {"listing_id": listing["id"]}))
    if units > 0 and targets:
        confirm_line(targets[0]["id"], vendor_id, units)
    if shipped == ordered:
        shipment = report_shipment(
            po["id"], vendor_id, shipped,
            [{"listing_id": listing["id"], "quantity": shipped}],
            carrier_tracking_code=f"FILL{carrier_suffix}",
            shipped_at="2026-09-01T00:00:00Z")
        receive_shipment(shipment["id"], "2026-09-01T09:00:00Z", shipped)
    elif shipped > 0:
        report_shipment(
            po["id"], vendor_id, shipped,
            [{"listing_id": listing["id"], "quantity": shipped}],
            carrier_tracking_code=f"PART{carrier_suffix}",
            shipped_at="2026-09-01T00:00:00Z")
        close_short_buy(po["id"])
    else:
        close_short_buy(po["id"])
    return get_success_data(api_client.get_vendor(vendor_id, ANY))


def setup_vendor_standing(vendor, shop, event, listing, target="PROBATION",
                          probe_quantity=10):
    """Drive a vendor's standing to ``target`` and return the vendor re-read.

    The probe is placed against a listing of the vendor's own **dedicated probe
    shop**, because every precondition of the probe is expressed on the buy: the
    buy must cover its own event's listing, a confirmed line must exist, and
    reported units are bounded by the line's confirmed units. Reusing the caller's
    listing would force the probe onto demand the caller's scenario has already
    subscribed. Building a second shop also exercises the vendor's standing
    cascade across every shop it fronts, which is exactly what the callers assert.

    The bands are the ones the rolling ratio feeds: at or above 0.9700 is
    EXCELLENT, 0.9000 up to 0.9700 is GOOD, 0.7500 up to 0.8500 is PROBATION, and
    strictly below 0.7500 is SUSPENDED.
    """
    if target == "EXCELLENT":
        return get_success_data(api_client.get_vendor(vendor["id"], ANY))

    ordered = max(probe_quantity, 10)
    shipped = int(ordered * {"GOOD": 0.92, "PROBATION": 0.80, "SUSPENDED": 0.70}[target]) - 1
    if target in ("GOOD", "PROBATION"):
        # Keep the realised ratio inside the band its tier reads off.
        shipped = int(ordered * 0.92) if target == "GOOD" else int(ordered * 0.80)

    probe_shop = create_shop(vendor["id"], shop_name=f"{shop['shop_name']} Probe")
    probe_event = create_event(
        probe_shop["id"], event_title="Standing Probe Event",
        starts_at="2026-09-01T00:00:00Z", ends_at="2026-09-02T00:00:00Z",
        ship_time_quote_days=14)
    probe_listing = create_listing(
        probe_event["id"], vendor_sku="NW-PROBE-1", unit_price_cents=100,
        vendor_unit_cost_cents=60, allocation_units=ordered,
        reveal_at="2026-09-01T00:00:00Z")
    schedule_event(probe_event["id"])
    launch_event(probe_event["id"])

    customer = create_customer(email=f"probe-{vendor['id'][:8]}@example.com",
                               full_name="Probe Buyer")
    order = create_order(customer["id"])
    line = add_line(order["id"], customer["id"], probe_listing["id"], ordered)
    submit_order(order["id"], customer["id"])

    current = fresh_vendor(vendor["id"])
    po = create_buy(current, probe_event)
    add_buy_line(po["id"], probe_listing["id"], ordered)
    issue_buy(po["id"], current)
    if shipped > 0:
        confirm_line(line["id"], vendor["id"], shipped)
    if shipped == ordered:
        shipment = report_shipment(
            po["id"], vendor["id"], shipped,
            [{"listing_id": probe_listing["id"], "quantity": shipped}],
            carrier_tracking_code=f"FILL-{target[:3]}",
            shipped_at="2026-09-01T00:00:00Z")
        receive_shipment(shipment["id"], "2026-09-01T09:00:00Z", shipped)
    elif shipped > 0:
        report_shipment(
            po["id"], vendor["id"], shipped,
            [{"listing_id": probe_listing["id"], "quantity": shipped}],
            carrier_tracking_code=f"PART-{target[:3]}",
            shipped_at="2026-09-01T00:00:00Z")
        close_short_buy(po["id"])
    else:
        close_short_buy(po["id"])
    get_success_data(api_client.run_event_checkpoint(probe_event["id"], MERCH))
    return get_success_data(api_client.get_vendor(vendor["id"], ANY))


def setup_shop_sku_count_at(shop, event, target_count=40, sku_prefix="CAP"):
    """Fill a shop's curated count to ``target_count`` by scheduling the event and
    merchandising ACTIVE listings into it.

    Returns the list of created listings.
    """
    listings = []
    for i in range(target_count):
        listings.append(create_listing(
            event["id"], vendor_sku=f"{sku_prefix}-{i:03d}",
            unit_price_cents=100, vendor_unit_cost_cents=60,
            allocation_units=4, reveal_at="2026-09-01T00:00:00Z"))
    schedule_event(event["id"])
    return listings


def setup_multi_line_order(lines_spec, customer_email="buyer@example.com",
                           **listing_overrides):
    """Create one customer order carrying several lines.

    ``lines_spec`` is a list of ``(listing_id, quantity)`` pairs, or a list of
    ``(listing_key, quantity)`` where ``listing_key`` indexes ``listings``.

    Returns (customer, order, lines).
    """
    customer = create_customer(email=customer_email)
    order = create_order(customer["id"])
    lines = []
    for listing_id, quantity in lines_spec:
        lines.append(add_line(order["id"], customer["id"], listing_id, quantity))
    return customer, order, lines


def create_cancellation_ledger_entries(customer, listing, count=3):
    """Drive ``count`` CANCELLATION ledger rows for a customer by placing, submitting
    and cancelling that many single-line orders.

    Returns the list of cancelled orders.
    """
    orders = []
    for i in range(count):
        order = create_order(customer["id"])
        add_line(order["id"], customer["id"], listing["id"], 1)
        submit_order(order["id"], customer["id"])
        get_success_data(api_client.cancel_order(
            order["id"], {"reason_code": "CHANGED_MIND"},
            make_customer_headers(customer["id"])))
        orders.append(order)
    return orders


# ═══════════════════════════════════════════════════════
# Tier 5: Finalization / terminal state
# ═══════════════════════════════════════════════════════

def setup_event_closed(cancel_pending_aggregations=True, **listing_overrides):
    """Vendor + shop + LIVE event + listing + customer/order/line, then close the event.

    Returns (vendor, shop, event, listing, customer, order, line).
    """
    vendor, shop, event, listing, customer, order, line = \
        setup_order_with_submitted_line(**listing_overrides)
    get_success_data(api_client.close_event(
        event["id"], MERCH,
        {"cancel_pending_aggregations": cancel_pending_aggregations}))
    return vendor, shop, event, listing, customer, order, line


def setup_event_cancelled_from_live(**listing_overrides):
    """Vendor + shop + LIVE event + listing, cancelled straight from LIVE (no buy, no
    oversell so the LIVE cancellation is admitted)."""
    vendor, shop, event, listing = setup_live_event_with_listing(**listing_overrides)
    get_success_data(api_client.cancel_event(
        event["id"], MERCH, {"reason_code": "MERCHANDISING_PULLED"}))
    return vendor, shop, event, listing


def setup_return_ready_for_review(reason_code="CHANGED_MIND", **listing_overrides):
    """A delivered order whose line carries an escalated return sitting in CS_REVIEW.

    Returns a dict with the scenario entities plus ``return_request``.
    """
    ctx = setup_order_delivered(quantity=1, **listing_overrides)
    line = get_success_data(api_client.get_confirmation(ctx["line"]["id"], ANY))
    rr = get_success_data(api_client.create_return({
        "confirmation_id": line["id"],
        "reason_code": reason_code,
        "expected_confirmation_version": line["version"],
    }, make_customer_headers(ctx["customer"]["id"])))
    get_success_data(api_client.adjudicate_return(rr["id"], CS))
    rr = get_success_data(api_client.get_return(rr["id"], ANY))
    if rr["return_status"] == "AI1_DENIED":
        rr = get_success_data(api_client.escalate_return(
            rr["id"], make_customer_headers(ctx["customer"]["id"])))
    ctx["return_request"] = rr
    return ctx


def setup_customer_at_credit(customer, target_lifetime_cents=50000,
                             reason_code="GOODWILL"):
    """Issue manual goodwill credit until the customer's lifetime credit reaches
    ``target_lifetime_cents``.

    Returns the customer re-read from the API.
    """
    remaining = target_lifetime_cents
    i = 0
    while remaining > 0:
        chunk = min(remaining, 43000)
        get_success_data(api_client.create_credit(
            customer["id"],
            {"amount_cents": chunk, "idempotency_key": f"seed-{i}",
             "reason_code": reason_code},
            CS))
        remaining -= chunk
        i += 1
    return get_success_data(api_client.get_customer(customer["id"], ANY))
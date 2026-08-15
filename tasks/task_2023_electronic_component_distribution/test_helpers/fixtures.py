"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. Setup calls use get_success_data() so a failure
surfaces as a clear "Setup step failed" instead of a confusing assertion.

Identity threading: CustomerBuyer is entity-backed by Customer — any
ownership-gated call builds headers via make_customer_buyer_headers(customer_id)
with the real entity id, never the shared constant.
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import LOGICAL_CLOCK_DEFAULT
from .factories import (
    create_alternate_approval_payload,
    create_allocation_run_payload,
    create_buyback_payload,
    create_customer_payload,
    create_design_registration_payload,
    create_lot_payload,
    create_manufacturer_line_payload,
    create_order_payload,
    create_part_payload,
    order_line_spec,
)
from .test_users import TEST_USERS, make_warehouse_ops_headers

ADMIN = TEST_USERS["distributor_admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
WAREHOUSE = TEST_USERS["warehouse_ops_headers"]
INSPECTOR = TEST_USERS["quality_inspector_headers"]
SUPPLIER = TEST_USERS["supplier_admin_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def create_line(line_code="LIN-1", **overrides):
    """Create a manufacturer line. Returns the created line."""
    payload = create_manufacturer_line_payload(line_code=line_code, **overrides)
    return get_success_data(api_client.create_manufacturer_line(payload, ADMIN))


def create_part(line_id, part_number="PN-1", **overrides):
    """Create a catalog part on a line. Returns the created part."""
    payload = create_part_payload(line_id, part_number=part_number, **overrides)
    return get_success_data(api_client.create_part(payload, ADMIN))


def create_customer(name="Test Customer", **overrides):
    """Create a customer account. Returns the created customer."""
    payload = create_customer_payload(name=name, **overrides)
    return get_success_data(api_client.create_customer(payload, ADMIN))


def receive_lot(part_id, qty_received=100, date_code="202601",
                source_type="FRANCHISED", receiver_id="wh-01"):
    """Receive an inventory lot as WarehouseOps; the receiver's X-User-ID is
    recorded as received_by_user_id (segregation-of-duties anchor)."""
    payload = create_lot_payload(part_id, date_code=date_code,
                                 qty_received=qty_received, source_type=source_type)
    return get_success_data(
        api_client.create_lot(payload, make_warehouse_ops_headers(receiver_id)))


def create_order(customer_id, lines, headers=None, note=None):
    """Create an order with inline lines (born SUBMITTED). Returns the order."""
    payload = create_order_payload(customer_id, lines, note=note)
    return get_success_data(
        api_client.create_order(payload, headers or SALES))


def acknowledge_order(order_id):
    """Acknowledge a SUBMITTED order. Returns the updated order."""
    return get_success_data(api_client.acknowledge_order(order_id, SALES))


def get_order_lines(order_id):
    """All lines of an order via the filtered list endpoint, in list order."""
    data, _meta = validate_paginated(
        api_client.list_order_lines(ADMIN, params={"order_id": order_id}))
    return data


def get_single_line(order_id):
    """The only line of a single-line order."""
    lines = get_order_lines(order_id)
    assert len(lines) == 1, f"Expected exactly one line, got {len(lines)}"
    return lines[0]


def get_order_line(line_id):
    return get_success_data(api_client.get_order_line(line_id, ADMIN))


def get_order(order_id):
    return get_success_data(api_client.get_order(order_id, ADMIN))


def get_part(part_id):
    return get_success_data(api_client.get_part(part_id, ADMIN))


def get_line(line_id):
    return get_success_data(api_client.get_manufacturer_line(line_id, ADMIN))


def get_customer(customer_id):
    return get_success_data(api_client.get_customer(customer_id, ADMIN))


def get_lot(lot_id):
    return get_success_data(api_client.get_lot(lot_id, ADMIN))


def get_registration(registration_id):
    return get_success_data(api_client.get_design_registration(registration_id, ADMIN))


def advance_clock(to_iso8601):
    """Advance the logical clock; runs the registration-expiry and MSL sweeps."""
    data = get_success_data(api_client.set_clock(to_iso8601, ADMIN))
    return data


def clock_plus_hours(hours, base=LOGICAL_CLOCK_DEFAULT):
    """An ISO timestamp `hours` after the given logical-clock instant."""
    start = datetime.strptime(base, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (start + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Tier 2: catalog + order hierarchies
# ---------------------------------------------------------------------------

def setup_catalog(line_code="LIN-1", line_kw=None, part_number="PN-1", part_kw=None):
    """One manufacturer line with one catalog part. Returns (line, part)."""
    line = create_line(line_code=line_code, **(line_kw or {}))
    part = create_part(line["id"], part_number=part_number, **(part_kw or {}))
    return line, part


def setup_acknowledged_order(quantity=10, ship_date="2026-10-01", line_code="LIN-1",
                             line_kw=None, part_kw=None, customer_kw=None):
    """Line + part + customer + single-line order, acknowledged.

    Returns dict(line, part, customer, order, order_line) with the order in
    ACKNOWLEDGED and the line OPEN (snapshot terms applied).
    """
    line, part = setup_catalog(line_code=line_code, line_kw=line_kw, part_kw=part_kw)
    customer = create_customer(**(customer_kw or {}))
    order = create_order(customer["id"],
                         [order_line_spec(part["id"], quantity, ship_date)])
    order = acknowledge_order(order["id"])
    order_line = get_single_line(order["id"])
    return {"line": line, "part": part, "customer": customer,
            "order": order, "order_line": order_line}


# ---------------------------------------------------------------------------
# Tier 3: allocation and shipping lifecycles
# ---------------------------------------------------------------------------

def create_allocation_run_for_part(part_id):
    """Create a PROVISIONAL allocation run, threading the part's current
    version for the OCC guard. Returns the created run."""
    part = get_part(part_id)
    payload = create_allocation_run_payload(part_id, part["version"])
    return get_success_data(api_client.create_allocation_run(payload, ADMIN), 201)


def publish_run(run_id):
    """Publish a PROVISIONAL run. Returns the published run."""
    return get_success_data(api_client.publish_allocation_run(run_id, ADMIN))


def setup_allocated_order(quantity=10, lot_qty=100, ship_date="2026-10-01",
                          line_code="LIN-1", line_kw=None, part_kw=None,
                          customer_kw=None, lot_date_code="202601",
                          lot_source_type="FRANCHISED", receiver_id="wh-01"):
    """Acknowledged single-line order whose line is fully/partially ALLOCATED
    via a published run against one freshly received lot.

    Returns dict(line, part, customer, order, order_line, lot, run).
    """
    sc = setup_acknowledged_order(quantity=quantity, ship_date=ship_date,
                                  line_code=line_code, line_kw=line_kw,
                                  part_kw=part_kw, customer_kw=customer_kw)
    lot = receive_lot(sc["part"]["id"], qty_received=lot_qty,
                      date_code=lot_date_code, source_type=lot_source_type,
                      receiver_id=receiver_id)
    run = publish_run(create_allocation_run_for_part(sc["part"]["id"])["id"])
    order_line = get_order_line(sc["order_line"]["id"])
    return {**sc, "lot": lot, "run": run, "order_line": order_line}


def ship_line(order_id, line_id, qty, substitute_part_id=None):
    """Ship qty units of an ALLOCATED line as WarehouseOps. Returns the line."""
    payload = {"qty": qty}
    if substitute_part_id is not None:
        payload["substitute_part_id"] = substitute_part_id
    return get_success_data(
        api_client.ship_order_line(order_id, line_id, payload, WAREHOUSE))


def setup_shipped_order(quantity=10, ship_qty=None, lot_qty=100,
                        ship_date="2026-10-01", line_code="LIN-1", line_kw=None,
                        part_kw=None, customer_kw=None, lot_date_code="202601"):
    """Allocated single-line order with one successful ship applied.

    Returns dict(line, part, customer, order, order_line, lot, run).
    """
    sc = setup_allocated_order(quantity=quantity, lot_qty=lot_qty,
                               ship_date=ship_date, line_code=line_code,
                               line_kw=line_kw, part_kw=part_kw,
                               customer_kw=customer_kw, lot_date_code=lot_date_code)
    shipped = ship_line(sc["order"]["id"], sc["order_line"]["id"],
                        ship_qty if ship_qty is not None else quantity)
    return {**sc, "order_line": shipped,
            "order": get_order(sc["order"]["id"])}


# ---------------------------------------------------------------------------
# Tier 3b: registrations, alternates, claims
# ---------------------------------------------------------------------------

def submit_registration(customer_id, part_id, registered_cost_cents=700,
                        max_registered_qty=20, valid_from="2026-08-01",
                        valid_to="2026-12-31", headers=None):
    """Submit a design registration (born SUBMITTED). Returns it."""
    payload = create_design_registration_payload(
        customer_id, part_id, registered_cost_cents=registered_cost_cents,
        max_registered_qty=max_registered_qty, valid_from=valid_from,
        valid_to=valid_to)
    return get_success_data(
        api_client.create_design_registration(payload, headers or SALES), 201)


def decide_registration(registration_id, decision, reason=None):
    payload = {"decision": decision}
    if reason is not None:
        payload["reason"] = reason
    return get_success_data(
        api_client.decide_design_registration(registration_id, payload, SUPPLIER))


def approve_registration(registration_id):
    """Supplier APPROVE: registration becomes APPROVED with full remaining qty."""
    return decide_registration(registration_id, "APPROVE")


def propose_alternate(customer_id, primary_part_id, alternate_part_id, headers=None):
    payload = create_alternate_approval_payload(customer_id, primary_part_id,
                                                alternate_part_id)
    return get_success_data(
        api_client.create_alternate_approval(payload, headers or SALES), 201)


def setup_submitted_claim(order_quantity=10, ship_qty=5, registered_cost_cents=700,
                          max_registered_qty=20, standard_cost_cents=1000,
                          book_price_cents=1500, lot_qty=100, approve_first=True):
    """Full chain to a SUBMITTED ship-and-debit claim: stocked franchised part,
    APPROVED registration (unless approve_first=False), allocated order line,
    one ship of ship_qty. Returns dict(..., registration, claim).
    """
    sc = setup_allocated_order(
        quantity=order_quantity, lot_qty=lot_qty,
        part_kw={"standard_cost_cents": standard_cost_cents,
                 "book_price_cents": book_price_cents})
    registration = submit_registration(
        sc["customer"]["id"], sc["part"]["id"],
        registered_cost_cents=registered_cost_cents,
        max_registered_qty=max_registered_qty)
    if approve_first:
        registration = approve_registration(registration["id"])
    shipped = ship_line(sc["order"]["id"], sc["order_line"]["id"], ship_qty)
    claims, _meta = validate_paginated(
        api_client.list_claims(ADMIN, params={"order_line_id": sc["order_line"]["id"]}))
    claim = claims[0] if claims else None
    return {**sc, "order_line": shipped, "registration": registration,
            "claims": claims, "claim": claim}


# ---------------------------------------------------------------------------
# Tier 4: moisture handling and quarantine
# ---------------------------------------------------------------------------

def open_exposure_interval(lot_id, note="opened"):
    """Open a moisture-exposure interval on an AVAILABLE lot. Returns it."""
    return get_success_data(
        api_client.open_exposure(lot_id, {"note": note}, WAREHOUSE), 201)


def seal_exposure_interval(lot_id, exposure_id):
    return get_success_data(api_client.seal_exposure(lot_id, exposure_id, WAREHOUSE))


def bake(lot_id):
    return get_success_data(api_client.bake_lot(lot_id, WAREHOUSE))


def quarantine_lot_by_exposure(lot_id, hours, base=LOGICAL_CLOCK_DEFAULT):
    """Open an exposure interval at `base`, then advance the logical clock by
    `hours` so the sweep quarantines the lot when exposure >= floor life."""
    exposure = open_exposure_interval(lot_id)
    target = clock_plus_hours(hours, base=base)
    advance_clock(target)
    return exposure, target


def setup_quarantined_lot(floor_life_hours=100, lot_qty=100, hours=None,
                          line_code="LIN-Q"):
    """Stocked part whose lot is driven to QUARANTINED by the clock sweep.

    Returns dict(line, part, lot, exposure, now).
    """
    line, part = setup_catalog(line_code=line_code,
                               part_kw={"floor_life_hours": floor_life_hours})
    lot = receive_lot(part["id"], qty_received=lot_qty)
    exposure, target = quarantine_lot_by_exposure(
        lot["id"], hours if hours is not None else floor_life_hours)
    return {"line": line, "part": part, "lot": get_lot(lot["id"]),
            "exposure": exposure, "now": target}


# ---------------------------------------------------------------------------
# Tier 5: buy-back program
# ---------------------------------------------------------------------------

def create_buyback(customer_id, order_line_id, kind="EXCESS_RETURN", qty=1,
                   headers=None):
    payload = create_buyback_payload(customer_id, order_line_id, kind=kind, qty=qty)
    return get_success_data(api_client.create_buyback(payload, headers or SALES), 201)


def setup_buyback_scenario(quantity=10, trailing_purchases_cents=1_000_000,
                           lot_qty=100, ship_qty=None, line_code="LIN-BB"):
    """Shipped single-line order for a customer with trailing purchases; ready
    for buy-back requests. Returns dict(line, part, customer, order,
    order_line, lot, run)."""
    return setup_shipped_order(
        quantity=quantity, lot_qty=lot_qty, ship_qty=ship_qty, line_code=line_code,
        customer_kw={"trailing_12mo_purchases_cents": trailing_purchases_cents})


def approve_buyback(buyback_id):
    return get_success_data(
        api_client.decide_buyback(buyback_id, {"decision": "APPROVE"}, ADMIN))


def list_claims_for_line(order_line_id):
    data, meta = validate_paginated(
        api_client.list_claims(ADMIN, params={"order_line_id": order_line_id}))
    return data, meta

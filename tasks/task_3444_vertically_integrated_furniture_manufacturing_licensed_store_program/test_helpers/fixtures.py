"""Composite setup helpers for the furniture license-program domain.

The runner restarts the API server before every test, so every test begins
against an empty database with the logical clock at 2026-09-01T00:00:00Z
(PRD §2.5). Every helper here builds its preconditions from scratch using only
PRD-declared endpoints, and uses get_success_data so setup failures surface as
clear "Setup failed" errors rather than confusing assertion failures.

Identity threading (PRD §2.1): every ownership-gated call made on behalf of a
licensee uses make_licensee_manager_headers(licensee["id"]); wholesale calls
use make_wholesale_buyer_headers(account["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .factories import (
    create_allocation_cycle_payload,
    create_appointment_payload,
    create_distribution_center_payload,
    create_factory_payload,
    create_licensee_payload,
    create_order_payload,
    create_product_line_payload,
    create_retail_account_payload,
    create_territory_payload,
    create_warranty_claim_payload,
)
from .test_users import (
    TEST_USERS,
    make_licensee_manager_headers,
    make_wholesale_buyer_headers,
)

PA = TEST_USERS["platform_admin_headers"]
PP = TEST_USERS["production_planner_headers"]
LC = TEST_USERS["logistics_coordinator_headers"]
WA = TEST_USERS["warranty_admin_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity creators and transitions
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Advance the logical clock (PRD §2.5). Forward-only within a test."""
    return get_success_data(api.set_clock(to_iso8601, PA))


def create_factory(**overrides):
    return get_success_data(api.create_factory(create_factory_payload(**overrides), PA))


def transition_factory(factory_id, to_state):
    return get_success_data(
        api.transition_factory(factory_id, {"to_state": to_state}, PP)
    )


def create_product_line(**overrides):
    return get_success_data(
        api.create_product_line(create_product_line_payload(**overrides), PA)
    )


def advance_product_line(line_id):
    return get_success_data(api.advance_product_line(line_id, PA))


def get_product_line(line_id):
    return get_success_data(api.get_product_line(line_id, PA))


def create_active_product_line(**overrides):
    line = create_product_line(**overrides)
    return advance_product_line(line["id"])


def create_clearance_product_line(**overrides):
    line = create_active_product_line(**overrides)
    return advance_product_line(line["id"])


def create_licensee(**overrides):
    return get_success_data(api.create_licensee(create_licensee_payload(**overrides), PA))


def transition_licensee(licensee_id, to_state):
    return get_success_data(
        api.transition_licensee(licensee_id, {"to_state": to_state}, PA)
    )


def create_active_licensee(**overrides):
    licensee = create_licensee(**overrides)
    return transition_licensee(licensee["id"], "ACTIVE")


def get_licensee(licensee_id):
    return get_success_data(api.get_licensee(licensee_id, PA))


def set_audit_score(licensee_id, score):
    """OCC-guarded terms update of latest_audit_score (PRD §2.7, §3.2)."""
    current = get_licensee(licensee_id)
    return get_success_data(
        api.update_licensee_terms(
            licensee_id,
            {
                "expected_licensee_version": current["version"],
                "latest_audit_score": score,
            },
            PA,
        )
    )


def create_territory(**overrides):
    return get_success_data(
        api.create_territory(create_territory_payload(**overrides), PA)
    )


def assign_territory(territory_id, licensee_id):
    return get_success_data(
        api.transition_territory(
            territory_id, {"to_state": "ASSIGNED", "licensee_id": licensee_id}, PA
        )
    )


def get_territory(territory_id):
    return get_success_data(api.get_territory(territory_id, PA))


def create_retail_account(**overrides):
    return get_success_data(
        api.create_retail_account(create_retail_account_payload(**overrides), PA)
    )


def get_retail_account(account_id):
    return get_success_data(api.get_retail_account(account_id, PA))


def transition_retail_account(account_id, to_state):
    return get_success_data(
        api.transition_retail_account(account_id, {"to_state": to_state}, PA)
    )


def create_distribution_center(**overrides):
    return get_success_data(
        api.create_distribution_center(create_distribution_center_payload(**overrides), PA)
    )


def create_cycle(factory_id, week_start=None, **overrides):
    payload = create_allocation_cycle_payload(factory_id, **overrides)
    if week_start is not None:
        payload["week_start"] = week_start
    return get_success_data(api.create_allocation_cycle(payload, PP))


def get_cycle(cycle_id):
    return get_success_data(api.get_allocation_cycle(cycle_id, PP))


def run_cycle(cycle_id):
    return get_success_data(api.run_allocation(cycle_id, PP))


def close_cycle(cycle_id):
    return get_success_data(api.close_cycle(cycle_id, PP))


# ---------------------------------------------------------------------------
# Tier 2: order lifecycle shortcuts (dual-axis machine, PRD §3.5)
# ---------------------------------------------------------------------------

def create_licensee_order(licensee, cycle, line, quantity=1,
                          delivery_mode="FREIGHT_TO_STORE", **overrides):
    payload = create_order_payload(
        allocation_cycle_id=cycle["id"],
        product_line_id=line["id"],
        buyer_type="LICENSEE",
        licensee_id=licensee["id"],
        retail_account_id=None,
        quantity=quantity,
        delivery_mode=delivery_mode,
        **overrides,
    )
    return get_success_data(
        api.create_order(payload, make_licensee_manager_headers(licensee["id"]))
    )


def create_retail_order(account, cycle, line, quantity=1, **overrides):
    payload = create_order_payload(
        allocation_cycle_id=cycle["id"],
        product_line_id=line["id"],
        buyer_type="RETAIL_ACCOUNT",
        licensee_id=None,
        retail_account_id=account["id"],
        quantity=quantity,
        delivery_mode="FREIGHT_TO_STORE",
        **overrides,
    )
    return get_success_data(
        api.create_order(payload, make_wholesale_buyer_headers(account["id"]))
    )


def get_order(order_id):
    return get_success_data(api.get_order(order_id, PA))


def submit_order(order):
    """SUBMIT as the order's buyer owner. Returns the updated order."""
    if order["buyer_type"] == "LICENSEE":
        headers = make_licensee_manager_headers(order["licensee_id"])
    else:
        headers = make_wholesale_buyer_headers(order["retail_account_id"])
    return get_success_data(api.transition_order(order["id"], {"action": "SUBMIT"}, headers))


def cancel_order(order, reason="cancelled"):
    if order["buyer_type"] == "LICENSEE":
        headers = make_licensee_manager_headers(order["licensee_id"])
    else:
        headers = make_wholesale_buyer_headers(order["retail_account_id"])
    return get_success_data(
        api.transition_order(order["id"], {"action": "CANCEL", "reason": reason}, headers)
    )


def pick_order(order_id):
    return get_success_data(api.transition_order(order_id, {"action": "PICK"}, LC))


def ship_order(order_id):
    return get_success_data(api.transition_order(order_id, {"action": "SHIP"}, LC))


def deliver_order(order_id):
    return get_success_data(api.transition_order(order_id, {"action": "DELIVER"}, LC))


def deliver_freight_order(order_id):
    """PICK -> SHIP -> DELIVER a freight order (PRD §3.5 freight flow)."""
    pick_order(order_id)
    ship_order(order_id)
    return deliver_order(order_id)


# ---------------------------------------------------------------------------
# Tier 3: composite contexts
# ---------------------------------------------------------------------------

def setup_catalog(factory_over=None, line_over=None, licensee_over=None,
                  line_state="ACTIVE"):
    """Factory + product line (advanced to line_state) + ACTIVE licensee."""
    factory = create_factory(**(factory_over or {}))
    line = create_product_line(**(line_over or {}))
    for _target in ("ACTIVE", "CLEARANCE", "RETIRED"):
        if line_state in ("ACTIVE", "CLEARANCE", "RETIRED") and line["lifecycle"] != line_state:
            line = advance_product_line(line["id"])
    licensee = create_active_licensee(**(licensee_over or {}))
    return {"factory": factory, "line": line, "licensee": licensee}


def setup_open_cycle(ctx=None, week_start=None, **catalog_kwargs):
    """Catalog + one OPEN allocation cycle."""
    ctx = ctx or setup_catalog(**catalog_kwargs)
    ctx["cycle"] = create_cycle(ctx["factory"]["id"], week_start=week_start)
    return ctx


def setup_hd_context(licensee_over=None, dc_over=None, territory_over=None,
                     **catalog_kwargs):
    """Catalog + territory T-SEA assigned to the licensee + home-delivery DC +
    OPEN cycle. The standard home-delivery backdrop (PRD §3.6)."""
    ctx = setup_open_cycle(licensee_over=licensee_over, **catalog_kwargs)
    territory = create_territory(
        **({"region_code": "T-SEA", "population_tier": "METRO"} | (territory_over or {}))
    )
    assign_territory(territory["id"], ctx["licensee"]["id"])
    dc = create_distribution_center(
        **({
            "code": "DC-KENT",
            "supports_home_delivery": True,
            "daily_crew_units": 6,
            "region_codes": ["T-SEA"],
        } | (dc_over or {}))
    )
    ctx.update(territory=territory, dc=dc, region_code="T-SEA")
    return ctx


def create_hd_order(ctx, quantity=1, **overrides):
    return create_licensee_order(
        ctx["licensee"], ctx["cycle"], ctx["line"],
        quantity=quantity, delivery_mode="HOME_DELIVERY", **overrides,
    )


def setup_hd_picked_order(quantity=2, **hd_kwargs):
    """Full home-delivery chain through to a PICKED order (PRD §3.5/§3.6):
    catalog + territory + DC + cycle + HOME_DELIVERY order submitted, the cycle
    run (order ALLOCATED), and the order picked."""
    ctx = setup_hd_context(**hd_kwargs)
    order = create_hd_order(ctx, quantity=quantity)
    submit_order(order)
    run_cycle(ctx["cycle"]["id"])
    pick_order(order["id"])
    ctx["order"] = get_order(order["id"])
    return ctx


def setup_delivered_freight_order(line_over=None, quantity=3, **catalog_kwargs):
    """Catalog + OPEN cycle + licensee freight order submitted, allocated and
    DELIVERED via the freight flow. Returns (ctx, delivered_order)."""
    ctx = setup_open_cycle(line_over=line_over, **catalog_kwargs)
    order = create_licensee_order(
        ctx["licensee"], ctx["cycle"], ctx["line"], quantity=quantity
    )
    submit_order(order)
    run_cycle(ctx["cycle"]["id"])
    deliver_freight_order(order["id"])
    return ctx, get_order(order["id"])


# ---------------------------------------------------------------------------
# Tier 4: home-delivery appointments (PRD §3.6)
# ---------------------------------------------------------------------------

def book_appointment_response(order, ctx, window_start, window_end, zone="LOCAL",
                              crew_units=1, region_code=None, dc_id=None,
                              stairs_flights=None):
    """Raw appointment-create call (returns the response for either assertion
    path). licensee_id is derived server-side from the order."""
    extra = {}
    if stairs_flights is not None:
        extra["stairs_flights"] = stairs_flights
    payload = create_appointment_payload(
        supply_order_id=order["id"],
        dc_id=dc_id or ctx["dc"]["id"],
        region_code=region_code or ctx["region_code"],
        window_start=window_start,
        window_end=window_end,
        zone=zone,
        crew_units=crew_units,
        **extra,
    )
    return api.create_delivery_appointment(
        payload, make_licensee_manager_headers(order["licensee_id"])
    )


def book_appointment(order, ctx, window_start, window_end, **kwargs):
    return get_success_data(
        book_appointment_response(order, ctx, window_start, window_end, **kwargs)
    )


def get_appointment(appointment_id):
    return get_success_data(api.get_delivery_appointment(appointment_id, PA))


def confirm_appointment(appointment_id):
    return get_success_data(
        api.transition_delivery_appointment(
            appointment_id, {"to_state": "CONFIRMED"}, LC
        )
    )


def complete_appointment(appointment_id, actual_duration_minutes):
    return get_success_data(
        api.transition_delivery_appointment(
            appointment_id,
            {
                "to_state": "COMPLETED",
                "actual_duration_minutes": actual_duration_minutes,
            },
            LC,
        )
    )


def cancel_appointment(appointment_id, as_licensee_id=None):
    """Cancel as the owning LicenseeManager when as_licensee_id is given, else
    as LogisticsCoordinator (both actors are allowed, PRD §3.6)."""
    headers = (
        make_licensee_manager_headers(as_licensee_id) if as_licensee_id else LC
    )
    return get_success_data(
        api.transition_delivery_appointment(
            appointment_id, {"to_state": "CANCELLED"}, headers
        )
    )


# ---------------------------------------------------------------------------
# Tier 5: warranty claims and parts orders (PRD §3.7)
# ---------------------------------------------------------------------------

def file_claim(order, claim_type="DEFECT", description="Claim description"):
    """File a warranty claim as the owning LicenseeManager."""
    payload = create_warranty_claim_payload(
        order["id"], claim_type=claim_type, description=description
    )
    return get_success_data(
        api.create_warranty_claim(
            payload, make_licensee_manager_headers(order["licensee_id"])
        )
    )


def get_claim(claim_id):
    return get_success_data(api.get_warranty_claim(claim_id, WA))


def transition_claim(claim_id, payload, as_admin=True, licensee_id=None):
    headers = WA if as_admin else make_licensee_manager_headers(licensee_id)
    return get_success_data(api.transition_warranty_claim(claim_id, payload, headers))


def transition_parts_order(parts_order_id, to_state):
    return get_success_data(
        api.transition_parts_order(parts_order_id, {"to_state": to_state}, LC)
    )


def list_parts_orders_for_claim(claim_id):
    return get_success_data(api.list_parts_orders(WA, params={"claim_id": claim_id}))


# ---------------------------------------------------------------------------
# Tier 6: performance-cycle player (PRD §3.8)
# ---------------------------------------------------------------------------

def play_scored_cycle(ctx, week_start, order_qtys, deliver_count=0,
                      audit_score=None, claim_types=(), move_clock=True):
    """Play one full allocation cycle for ctx's licensee and close it.

    Creates the cycle at week_start, optionally advances the logical clock to
    week_start + 8h (so claims filed in-cycle fall inside the scoring window
    [week_start, closed_at] of PRD §3.8), creates+submits one freight order per
    qty, runs the allocation, delivers the first deliver_count orders, files
    claim_types against the first delivered order, sets the audit score, and
    closes the cycle. Returns the closed cycle.
    """
    cycle = create_cycle(ctx["factory"]["id"], week_start=week_start)
    if move_clock:
        set_clock(week_start.replace("T00:00:00Z", "T08:00:00Z"))
    orders = []
    for qty in order_qtys:
        o = create_licensee_order(ctx["licensee"], cycle, ctx["line"], quantity=qty)
        orders.append(submit_order(o))
    run_cycle(cycle["id"])
    delivered = []
    for o in orders[:deliver_count]:
        deliver_freight_order(o["id"])
        delivered.append(get_order(o["id"]))
    for ct in claim_types:
        file_claim(delivered[0], claim_type=ct)
    if audit_score is not None:
        set_audit_score(ctx["licensee"]["id"], audit_score)
    return close_cycle(cycle["id"])

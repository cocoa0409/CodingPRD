"""Composite setup helpers for the DSD route-sales domain.

The runner restarts the server (empty database) before every test, so each
fixture builds its preconditions from scratch via PRD-declared endpoints.
All setup calls use the lenient get_success_data() so a setup failure
surfaces as a clear "Setup failed" rather than an assertion error.

Identity threading: rep-owned and store-scoped calls always use
make_rep_headers(rep["id"]) / make_store_manager_headers(store["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as _api
from .constants import (
    CLOCK_IN_WINDOW,
    EXPIRY_FRESH,
    SERVICE_DATE_TUE,
    SERVICE_DATE_WED,
)
from .factories import (
    create_assignment_payload,
    create_order_payload,
    create_product_payload,
    create_rep_payload,
    create_route_day_payload,
    create_route_payload,
    create_settlement_payload,
    create_store_payload,
    deliver_line,
    deliver_payload,
    load_payload,
    lot_entry,
    order_line,
)
from .test_users import make_admin_headers, make_rep_headers, make_supervisor_headers


class SetupFailedError(AssertionError):
    pass


def _data(resp, step: str):
    if resp.status_code >= 400:
        raise SetupFailedError(
            f"Setup failed at {step}: HTTP {resp.status_code} {resp.text}"
        )
    return get_success_data(resp)


def set_clock(current_utc: str = CLOCK_IN_WINDOW):
    _data(_api.set_clock({"current_utc": current_utc}, make_admin_headers()), "set_clock")


def create_rep(**overrides) -> dict:
    resp = _api.create_rep(create_rep_payload(**overrides), make_admin_headers())
    return _data(resp, "create_rep")


def create_store(**overrides) -> dict:
    resp = _api.create_store(create_store_payload(**overrides), make_admin_headers())
    return _data(resp, "create_store")


def create_product(**overrides) -> dict:
    resp = _api.create_product(create_product_payload(**overrides), make_admin_headers())
    return _data(resp, "create_product")


def create_route(rsr_id, **overrides) -> dict:
    resp = _api.create_route(create_route_payload(rsr_id, **overrides), make_supervisor_headers())
    return _data(resp, "create_route")


def create_assignment(route_id, store_id, **overrides) -> dict:
    resp = _api.create_assignment(
        create_assignment_payload(route_id, store_id, **overrides),
        make_supervisor_headers(),
    )
    return _data(resp, "create_assignment")


def create_route_day(route_id, **overrides) -> dict:
    resp = _api.create_route_day(
        create_route_day_payload(route_id, **overrides), make_supervisor_headers()
    )
    return _data(resp, "create_route_day")


def load_route_day(day_id, lots, rep) -> dict:
    resp = _api.load_route_day(day_id, load_payload(lots), make_rep_headers(rep["id"]))
    return _data(resp, "load_route_day")


def start_route_day(day_id, rep) -> dict:
    resp = _api.start_route_day(day_id, make_rep_headers(rep["id"]))
    return _data(resp, "start_route_day")


def get_route_day(day_id) -> dict:
    return _data(_api.get_route_day(day_id, make_supervisor_headers()), "get_route_day")


def list_lots(params: dict) -> list:
    return _data(_api.list_truck_lots(make_supervisor_headers(), params=params), "list_lots")


def get_lot_by_code(day_id, lot_code) -> dict:
    lots = list_lots({"route_day_id": day_id, "lot_code": lot_code})
    matches = [l for l in lots if l.get("lot_code") == lot_code]
    assert len(matches) == 1, f"expected exactly one lot {lot_code}, got {len(matches)}"
    return matches[0]


def create_order(day_id, store_id, lines, rep, **overrides) -> dict:
    resp = _api.create_order(
        create_order_payload(day_id, store_id, lines, **overrides),
        make_rep_headers(rep["id"]),
    )
    return _data(resp, "create_order")


def submit_order(order_id, rep) -> dict:
    resp = _api.submit_order(order_id, make_rep_headers(rep["id"]))
    return _data(resp, "submit_order")


def deliver_order(order_id, lines, rep) -> dict:
    resp = _api.deliver_order(order_id, deliver_payload(lines), make_rep_headers(rep["id"]))
    return _data(resp, "deliver_order")


def get_order(order_id) -> dict:
    return _data(_api.get_order(order_id, make_supervisor_headers()), "get_order")


def create_stale_credit(day_id, store_id, product_id, qty_cases, headers) -> dict:
    from .factories import create_stale_credit_payload

    resp = _api.create_stale_credit(
        create_stale_credit_payload(day_id, store_id, product_id, qty_cases), headers
    )
    return _data(resp, "create_stale_credit")


def approve_credit(credit_id, supervisor_headers=None) -> dict:
    resp = _api.approve_stale_credit(credit_id, supervisor_headers or make_supervisor_headers())
    return _data(resp, "approve_credit")


def reject_credit(credit_id, reason, supervisor_headers=None) -> dict:
    from .factories import reject_credit_payload

    resp = _api.reject_stale_credit(
        credit_id, reject_credit_payload(reason), supervisor_headers or make_supervisor_headers()
    )
    return _data(resp, "reject_credit")


def get_credit(credit_id) -> dict:
    return _data(_api.get_stale_credit(credit_id, make_supervisor_headers()), "get_credit")


def create_settlement(day_id) -> dict:
    resp = _api.create_settlement(create_settlement_payload(day_id), make_supervisor_headers())
    return _data(resp, "create_settlement")


def balance_settlement(settlement_id, cash_collected_cents) -> dict:
    from .factories import balance_payload

    resp = _api.balance_settlement(
        settlement_id, balance_payload(cash_collected_cents), make_supervisor_headers()
    )
    return _data(resp, "balance_settlement")


def get_settlement(settlement_id) -> dict:
    return _data(_api.get_settlement(settlement_id, make_supervisor_headers()), "get_settlement")


def list_orders(params: dict) -> tuple:
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(_api.list_orders(make_supervisor_headers(), params=params))


# ---------------------------------------------------------------------------
# Composite fixtures
# ---------------------------------------------------------------------------

def setup_base(clock: str = CLOCK_IN_WINDOW, **route_overrides) -> dict:
    """Clock set; one rep; one ACTIVE store (FULL_RETAIL, cap 100000); one
    product (500 cents); one route; one TUE assignment.

    Returns dict(rep, store, product, route, assignment).
    """
    set_clock(clock)
    rep = create_rep()
    store = create_store()
    product = create_product()
    route = create_route(rep["id"], **route_overrides)
    assignment = create_assignment(route["id"], store["id"])
    return {
        "rep": rep,
        "store": store,
        "product": product,
        "route": route,
        "assignment": assignment,
    }


def setup_route_day(base: dict, service_date: str = SERVICE_DATE_TUE, lots=None,
                    **day_overrides) -> dict:
    """Plan a route day on top of a base context. Returns the RouteDay."""
    return create_route_day(base["route"]["id"], service_date=service_date, **day_overrides)


def setup_started_day(clock: str = CLOCK_IN_WINDOW, lots=None,
                      service_date: str = SERVICE_DATE_TUE, **base_route_overrides) -> dict:
    """Full preamble: base context + route day LOADED with `lots` then started
    (IN_PROGRESS, lots OPEN). Default: one 100-case lot of the base product
    expiring 2026-09-20.

    Returns dict(rep, store, product, route, assignment, day).
    """
    base = setup_base(clock=clock, **base_route_overrides)
    day = setup_route_day(base, service_date=service_date)
    if lots is None:
        lots = [lot_entry(base["product"]["id"], "L-1", EXPIRY_FRESH, 100)]
    day = load_route_day(day["id"], lots, base["rep"])
    day = start_route_day(day["id"], base["rep"])
    base["day"] = day
    return base


def setup_delivered_order(ctx: dict, qty_cases: int, price_lines=None,
                          deliver_qty: int = None, store_id: str = None) -> dict:
    """Create + submit + deliver an order on ctx's started day. Returns the
    delivered order."""
    product_id = ctx["product"]["id"]
    store = store_id or ctx["store"]["id"]
    lines = price_lines or [order_line(product_id, qty_cases)]
    order = create_order(ctx["day"]["id"], store, lines, ctx["rep"])
    submit_order(order["id"], ctx["rep"])
    if deliver_qty is None:
        deliver_qty = qty_cases
    dlines = [deliver_line(product_id, deliver_qty)]
    order = deliver_order(order["id"], dlines, ctx["rep"])
    return order


def setup_day_with_stale_lot(clock: str = CLOCK_IN_WINDOW,
                             stale_qty: int = 20, fresh_qty: int = 0,
                             stale_expiry: str = None, **base_route_overrides) -> dict:
    """Started day whose truck carries a stale-eligible lot (expiry 2026-09-06,
    days_to_expiry 5 on the 2026-09-01 service date) and optionally a fresh lot."""
    from .constants import EXPIRY_STALE_ON_TUE

    base = setup_base(clock=clock, **base_route_overrides)
    day = setup_route_day(base)
    stale_expiry = stale_expiry or EXPIRY_STALE_ON_TUE
    lots = [lot_entry(base["product"]["id"], "L-ST", stale_expiry, stale_qty)]
    if fresh_qty:
        lots.append(lot_entry(base["product"]["id"], "L-F", EXPIRY_FRESH, fresh_qty))
    day = load_route_day(day["id"], lots, base["rep"])
    day = start_route_day(day["id"], base["rep"])
    base["day"] = day
    return base


def setup_approved_credit(clock: str = CLOCK_IN_WINDOW, qty_cases: int = 4,
                          stale_qty: int = 20, **base_route_overrides) -> dict:
    """Started stale-lot day + one credit created by the rep and APPROVED by a
    supervisor. Adds credit to the returned context."""
    ctx = setup_day_with_stale_lot(clock=clock, stale_qty=stale_qty, **base_route_overrides)
    credit = create_stale_credit(
        ctx["day"]["id"], ctx["store"]["id"], ctx["product"]["id"], qty_cases,
        make_rep_headers(ctx["rep"]["id"]),
    )
    credit = approve_credit(credit["id"])
    ctx["credit"] = credit
    return ctx


def setup_balanced_settlement(clock: str = CLOCK_IN_WINDOW, lots=None,
                              deliver_qty: int = None, order_qty: int = None,
                              cash_collected_cents: int = None) -> dict:
    """Started day, one fully delivered order, settlement OPEN then BALANCED
    with cash exactly equal to the chronological expectation (gross of the
    delivered order). Adds order and settlement to the returned context."""
    ctx = setup_started_day(clock=clock, lots=lots)
    qty = order_qty if order_qty is not None else (deliver_qty or 20)
    order = setup_delivered_order(ctx, qty)
    settlement = create_settlement(ctx["day"]["id"])
    cash = cash_collected_cents
    if cash is None:
        cash = settlement["chronological_expected_cents"]
    settlement = balance_settlement(settlement["id"], cash)
    ctx["order"] = order
    ctx["settlement"] = settlement
    return ctx

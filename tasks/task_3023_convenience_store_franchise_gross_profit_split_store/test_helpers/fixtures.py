"""Composite setup helpers.

Every fixture builds its preconditions from scratch through the public API --
no test inherits state from another, because the server is re-launched with an
empty database before each test.

Setup calls use ``get_success_data()`` (lenient) so a broken precondition
surfaces as a clear "Setup step failed" error rather than a confusing
assertion failure inside the test body.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULTS, THRESHOLDS, WEEK_PERIOD_END, WEEK_PERIOD_START
from .factories import (
    create_agreement_payload,
    create_delivery_window_payload,
    create_draw_payload,
    create_franchisee_payload,
    create_fresh_order_payload,
    create_rebate_payload,
    create_revenue_line_payload,
    create_settlement_payload,
    create_shrink_audit_payload,
    create_store_payload,
)
from .test_users import TEST_USERS, make_franchisee_headers

ADMIN = TEST_USERS["admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
COMMISSARY = TEST_USERS["commissary_headers"]

# The clock's default reading before it is ever set.
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"


# ─── Clock ───────────────────────────────────────────────────────────────────

def set_clock(current_utc: str):
    """Drive the server's logical clock. Every temporal rule reads it."""
    return get_success_data(api_client.set_current_utc(current_utc, ADMIN))


# ─── Tier 1: State progression ───────────────────────────────────────────────

def create_franchisee(stated_net_worth_cents: int = DEFAULTS["STATED_NET_WORTH_CENTS"],
                      **overrides) -> dict:
    """Register one operator. Returns the created Franchisee."""
    return get_success_data(api_client.create_franchisee(
        create_franchisee_payload(stated_net_worth_cents=stated_net_worth_cents, **overrides),
        ADMIN))


def create_store(franchisee_id: str, **overrides) -> dict:
    """Open one store under an operator. Returns the created Store."""
    return get_success_data(api_client.create_store(
        create_store_payload(franchisee_id, **overrides), ADMIN))


def create_agreement(franchisee_id: str, store_id: str, activate: bool = True,
                     **overrides) -> dict:
    """Draft an agreement for a store and optionally activate it."""
    agreement = get_success_data(api_client.create_agreement(
        create_agreement_payload(franchisee_id, store_id, **overrides), ADMIN))
    if activate:
        agreement = get_success_data(
            api_client.activate_agreement(agreement["id"], ADMIN))
    return agreement


def setup_store_with_agreement(
        franchisee_net_worth_cents: int = DEFAULTS["STATED_NET_WORTH_CENTS"],
        split_pct: float = DEFAULTS["SPLIT_PCT"],
        waste_share_pct: float = DEFAULTS["WASTE_SHARE_PCT"],
        shrink_responsibility_pct: float = DEFAULTS["SHRINK_RESPONSIBILITY_PCT"],
        rebate_pass_pct: float = DEFAULTS["REBATE_PASS_PCT"],
        minimum_net_worth_cents: int = DEFAULTS["MINIMUM_NET_WORTH_CENTS"],
        activate: bool = True,
        clock: str = DEFAULT_CLOCK,
        franchisee_overrides: dict = None,
        store_overrides: dict = None,
        **agreement_overrides) -> dict:
    """The most common preamble: one operator, one ACTIVE store, one agreement.

    Returns a dict with ``franchisee``, ``store`` and ``agreement`` keys.
    """
    set_clock(clock)
    franchisee = create_franchisee(
        stated_net_worth_cents=franchisee_net_worth_cents,
        **(franchisee_overrides or {}))
    store = create_store(franchisee["id"], **(store_overrides or {}))
    agreement = create_agreement(
        franchisee["id"], store["id"], activate=activate,
        split_pct=split_pct, waste_share_pct=waste_share_pct,
        shrink_responsibility_pct=shrink_responsibility_pct,
        rebate_pass_pct=rebate_pass_pct,
        minimum_net_worth_cents=minimum_net_worth_cents,
        **agreement_overrides)
    return {"franchisee": franchisee, "store": store, "agreement": agreement}


def create_two_franchisees_and_store(incumbent_net_worth_cents: int = 20_000_000,
                                     transferee_net_worth_cents: int = 30_000_000,
                                     **agreement_overrides) -> dict:
    """An incumbent operator with a store plus a separate ACTIVE transferee."""
    set_clock(DEFAULT_CLOCK)
    incumbent = create_franchisee(stated_net_worth_cents=incumbent_net_worth_cents)
    transferee = create_franchisee(stated_net_worth_cents=transferee_net_worth_cents,
                                   legal_name="Transferee Operator LLC")
    store = create_store(incumbent["id"])
    agreement = create_agreement(incumbent["id"], store["id"], **agreement_overrides)
    return {"incumbent": incumbent, "transferee": transferee,
            "store": store, "agreement": agreement}


def refresh_store(store_id: str) -> dict:
    """Re-read a store, since several operations bump its version."""
    return get_success_data(api_client.get_store(store_id, ADMIN))


# ─── Tier 2: Settlement assembly ─────────────────────────────────────────────

def create_open_settlement(store: dict, franchisee: dict, trailing_avg: int = None,
                           period_start: str = WEEK_PERIOD_START,
                           period_end: str = WEEK_PERIOD_END,
                           **overrides) -> dict:
    """Open a weekly settlement against the store's current version."""
    store_version = overrides.pop("expected_store_version", None)
    if store_version is None:
        store_version = refresh_store(store["id"])["version"]
    return get_success_data(api_client.create_settlement(
        create_settlement_payload(
            store["id"], franchisee["id"], store_version,
            trailing_avg_gross_profit_cents=(
                DEFAULTS["TRAILING_AVG_GROSS_PROFIT_CENTS"]
                if trailing_avg is None else trailing_avg),
            period_start=period_start, period_end=period_end, **overrides),
        ADMIN))


def add_revenue_line(settlement: dict, category: str, gross_sales_cents: int,
                     cost_of_goods_cents: int) -> tuple:
    """Append one revenue line, threading the settlement's running version.

    Returns (line, settlement_version_after).
    """
    response = api_client.add_revenue_line(
        settlement["id"],
        create_revenue_line_payload(
            settlement["version"], category=category,
            gross_sales_cents=gross_sales_cents,
            cost_of_goods_cents=cost_of_goods_cents),
        ADMIN)
    line = get_success_data(response)
    return line, line.get("version", settlement["version"] + 1)


def add_revenue_lines(settlement: dict, lines: list) -> dict:
    """Append several ``(category, gross, cogs)`` lines, threading versions."""
    current = settlement
    created = []
    for category, gross, cogs in lines:
        line, _ = add_revenue_line(current, category, gross, cogs)
        created.append(line)
        current = get_success_data(api_client.get_settlement(settlement["id"], ADMIN))
    return {"settlement": current, "lines": created}


def setup_settlement_with_lines(lines: list, trailing_avg: int = None,
                                **store_kwargs) -> dict:
    """Operator + store + ACTIVE agreement + OPEN settlement with revenue lines.

    ``lines`` is a list of ``(category, gross_sales_cents, cost_of_goods_cents)``.
    Returns a dict with ``franchisee``, ``store``, ``agreement``, ``settlement``
    and ``lines``.
    """
    context = setup_store_with_agreement(**store_kwargs)
    settlement = create_open_settlement(
        context["store"], context["franchisee"], trailing_avg=trailing_avg)
    added = add_revenue_lines(settlement, lines)
    context["settlement"] = added["settlement"]
    context["lines"] = added["lines"]
    return context


def reconcile_settlement(settlement_id: str) -> dict:
    """Run one reconciliation step. Returns the updated settlement."""
    return get_success_data(api_client.reconcile_settlement(settlement_id, ADMIN))


def reconcile_to_reconciled(settlement_id: str) -> dict:
    """Drive OPEN -> DRAW_PAID -> RECONCILED. Returns the RECONCILED settlement."""
    reconcile_settlement(settlement_id)
    return reconcile_settlement(settlement_id)


def post_rebate(store_id: str, rebate_cents: int, vendor_code: str = "BRD-01",
                recommended_vendor: bool = True, vendor_name: str = None,
                period_start: str = WEEK_PERIOD_START,
                period_end: str = WEEK_PERIOD_END) -> dict:
    """Post a vendor rebate overlapping the standard week."""
    overrides = {
        "rebate_cents": rebate_cents,
        "vendor_code": vendor_code,
        "recommended_vendor": recommended_vendor,
        "period_start": period_start,
        "period_end": period_end,
    }
    if vendor_name:
        overrides["vendor_name"] = vendor_name
    return get_success_data(api_client.create_rebate(
        create_rebate_payload(store_id, **overrides), ADMIN))


def setup_settlement_with_rebate(rebate_cents: int, lines: list,
                                 rebate_pass_pct: float = DEFAULTS["REBATE_PASS_PCT"],
                                 vendor_code: str = "BRD-01",
                                 trailing_avg: int = None, **store_kwargs) -> dict:
    """Store + agreement + settlement with lines + one overlapping recommended rebate."""
    context = setup_settlement_with_lines(
        lines, trailing_avg=trailing_avg, rebate_pass_pct=rebate_pass_pct, **store_kwargs)
    context["rebate"] = post_rebate(context["store"]["id"], rebate_cents,
                                    vendor_code=vendor_code)
    return context


# ─── Tier 3: Shrink audit lifecycle ──────────────────────────────────────────

def create_shrink_audit(store_id: str, period_start: str, period_end: str,
                        book_inventory_cents: int) -> dict:
    return get_success_data(api_client.create_shrink_audit(
        create_shrink_audit_payload(
            store_id, period_start=period_start, period_end=period_end,
            book_inventory_cents=book_inventory_cents),
        ADMIN))


def count_shrink_audit(audit_id: str, physical_inventory_cents: int,
                       recount: bool = False) -> dict:
    """Record a physical count under the FieldAuditor role."""
    return get_success_data(api_client.count_shrink_audit(
        audit_id, {"physical_inventory_cents": physical_inventory_cents,
                   "recount": recount}, AUDITOR))


def setup_counted_audit(book_inventory_cents: int, physical_inventory_cents: int,
                        shrink_responsibility_pct: float = 0.50,
                        period_start: str = "2026-08-01T00:00:00Z",
                        period_end: str = "2026-09-01T00:00:00Z",
                        clock: str = "2026-09-20T00:00:00Z",
                        **store_kwargs) -> dict:
    """Store + agreement + one shrink audit counted to COUNTED."""
    context = setup_store_with_agreement(
        shrink_responsibility_pct=shrink_responsibility_pct, clock=clock, **store_kwargs)
    audit = create_shrink_audit(context["store"]["id"], period_start, period_end,
                                book_inventory_cents)
    context["audit"] = count_shrink_audit(audit["id"], physical_inventory_cents)
    return context


# ─── Tier 4: Fresh-food window and order lifecycle ───────────────────────────

def create_delivery_window(store_id: str, window_start: str, window_end: str,
                           capacity_units: int, commissary_code: str = None,
                           day_of_week: str = None) -> dict:
    overrides = {"window_start": window_start, "window_end": window_end,
                 "capacity_units": capacity_units}
    if commissary_code:
        overrides["commissary_code"] = commissary_code
    if day_of_week:
        overrides["day_of_week"] = day_of_week
    return get_success_data(api_client.create_delivery_window(
        create_delivery_window_payload(store_id, **overrides), ADMIN))


def place_fresh_order(store_id: str, window_id: str, franchisee_id: str,
                      sku_code: str, ordered_units: int, unit_cost_cents: int) -> dict:
    """Book fresh food as the owning operator."""
    return get_success_data(api_client.create_fresh_order(
        create_fresh_order_payload(
            store_id, window_id, sku_code=sku_code,
            ordered_units=ordered_units, unit_cost_cents=unit_cost_cents),
        make_franchisee_headers(franchisee_id)))


def confirm_fresh_order(order_id: str) -> dict:
    return get_success_data(api_client.confirm_fresh_order(order_id, COMMISSARY))


def lock_delivery_window(window_id: str) -> dict:
    return get_success_data(api_client.lock_delivery_window(window_id, ADMIN))


def deliver_fresh_order(order_id: str, delivered_units: int) -> dict:
    return get_success_data(api_client.deliver_fresh_order(
        order_id, {"delivered_units": delivered_units}, COMMISSARY))


def reconcile_fresh_order(order_id: str, waste_units: int) -> dict:
    return get_success_data(api_client.reconcile_fresh_order(
        order_id, {"waste_units": waste_units}, ADMIN))


def refresh_window(window_id: str) -> dict:
    return get_success_data(api_client.get_delivery_window(window_id, ADMIN))


def setup_window_with_orders(orders: list,
                             capacity_units: int = 2000,
                             window_start: str = "2026-09-08T06:00:00Z",
                             window_end: str = "2026-09-08T10:00:00Z",
                             clock: str = DEFAULT_CLOCK,
                             confirm: bool = False,
                             lock: bool = False,
                             deliver: bool = False,
                             delivery_clock: str = None,
                             **store_kwargs) -> dict:
    """Store + agreement + one window carrying PLACED orders.

    ``orders`` is a list of ``(sku_code, ordered_units, unit_cost_cents)``.
    Optionally confirm, lock the window, and move the clock inside the window
    and deliver. Returns a dict with ``window`` and ``orders``.
    """
    store_kwargs.setdefault("store_overrides", {"cold_chain_certified": True})
    context = setup_store_with_agreement(clock=clock, **store_kwargs)
    window = create_delivery_window(
        context["store"]["id"], window_start, window_end, capacity_units)
    placed = [
        place_fresh_order(context["store"]["id"], window["id"],
                          context["franchisee"]["id"], sku, units, cost)
        for sku, units, cost in orders
    ]
    if confirm:
        placed = [confirm_fresh_order(order["id"]) for order in placed]
    if lock:
        lock_delivery_window(window["id"])
    if deliver:
        set_clock(delivery_clock or _midpoint(window_start, window_end))
        placed = [deliver_fresh_order(order["id"], _delivered_units(order))
                  for order in placed]
    context["window"] = refresh_window(window["id"])
    context["orders"] = placed
    return context


def _midpoint(window_start: str, window_end: str) -> str:
    """An instant strictly inside [window_start, window_end) for deliveries."""
    from datetime import datetime, timezone

    def _parse(value):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    start, end = _parse(window_start), _parse(window_end)
    middle = start + (end - start) / 2
    return middle.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _delivered_units(order: dict) -> int:
    """Delivered units default to the ordered quantity."""
    return order.get("delivered_units") or order["ordered_units"]


def setup_delivered_order(sku_code: str, ordered_units: int, unit_cost_cents: int,
                          waste_units: int,
                          capacity_units: int = 2000,
                          window_start: str = "2026-09-08T06:00:00Z",
                          window_end: str = "2026-09-08T10:00:00Z",
                          **store_kwargs) -> dict:
    """One order driven all the way to RECONCILED with a known waste figure."""
    context = setup_window_with_orders(
        [(sku_code, ordered_units, unit_cost_cents)],
        capacity_units=capacity_units, window_start=window_start,
        window_end=window_end, confirm=True, lock=True, deliver=True, **store_kwargs)
    order = reconcile_fresh_order(context["orders"][0]["id"], waste_units)
    context["orders"] = [order]
    context["window"] = refresh_window(context["window"]["id"])
    return context


# ─── Tier 5: Draws and terminal states ───────────────────────────────────────

def create_draw(franchisee_id: str, store_id: str, amount_cents: int,
                drawn_on: str = "2026-09-02T00:00:00Z") -> dict:
    return get_success_data(api_client.create_draw(
        create_draw_payload(franchisee_id, store_id,
                            amount_cents=amount_cents, drawn_on=drawn_on), ADMIN))


def refresh_franchisee(franchisee_id: str) -> dict:
    return get_success_data(api_client.get_franchisee(franchisee_id, ADMIN))


def suspend_franchisee(franchisee_id: str) -> dict:
    return get_success_data(api_client.suspend_franchisee(franchisee_id, ADMIN))


def reinstate_franchisee(franchisee_id: str) -> dict:
    return get_success_data(api_client.reinstate_franchisee(franchisee_id, ADMIN))


def terminate_franchisee(franchisee_id: str) -> dict:
    return get_success_data(api_client.terminate_franchisee(franchisee_id, ADMIN))


def finalize_settlement(settlement_id: str) -> dict:
    return get_success_data(api_client.finalize_settlement(settlement_id, ADMIN))


def setup_reinstate_scenario() -> dict:
    """The three-hop reinstatement preamble.

    One operator with a settled week whose draw was fully recovered, a
    COUNTED-but-unfinalized audit, and a store that the suspension cascade
    terminated -- so the reinstatement has something to restore.
    """
    set_clock("2026-09-01T12:00:00Z")
    franchisee = create_franchisee(stated_net_worth_cents=20_000_000)
    old_store = create_store(franchisee["id"], store_number="TX-7700")
    old_agreement = create_agreement(franchisee["id"], old_store["id"])

    settlement = create_open_settlement(old_store, franchisee,
                                        trailing_avg=1_000_000)
    add_revenue_lines(settlement, [("MERCHANDISE", 14_000_000, 4_000_000)])
    draw = create_draw(franchisee["id"], old_store["id"], 5_000_000)

    set_clock("2026-09-16T12:00:00Z")
    # Reconciliation is two steps -- OPEN -> DRAW_PAID, then DRAW_PAID ->
    # RECONCILED -- and finalization is only permitted on a RECONCILED week.
    reconcile_to_reconciled(settlement["id"])
    finalize_settlement(settlement["id"])

    set_clock("2026-09-20T12:00:00Z")
    audit = create_shrink_audit(old_store["id"], "2026-08-01T00:00:00Z",
                                "2026-09-01T00:00:00Z", 8_000_000)
    audit = count_shrink_audit(audit["id"], 7_600_000)

    suspend_franchisee(franchisee["id"])

    new_store = create_store(franchisee["id"], store_number="TX-9090",
                             opened_on="2026-09-11T00:00:00Z")
    new_agreement = create_agreement(
        franchisee["id"], new_store["id"],
        term_start="2026-09-11T00:00:00Z", term_end="2031-09-11T00:00:00Z")

    return {
        "franchisee": franchisee,
        "old_store": refresh_store(old_store["id"]),
        "old_agreement": get_success_data(
            api_client.get_agreement(old_agreement["id"], ADMIN)),
        "new_store": new_store,
        "new_agreement": new_agreement,
        "settlement": get_success_data(api_client.get_settlement(settlement["id"], ADMIN)),
        "draw": get_success_data(api_client.get_draw(draw["id"], ADMIN)),
        "audit": audit,
    }


__all__ = [
    "ADMIN", "AUDITOR", "COMMISSARY", "DEFAULT_CLOCK",
    "set_clock", "create_franchisee", "create_store", "create_agreement",
    "setup_store_with_agreement", "create_two_franchisees_and_store", "refresh_store",
    "create_open_settlement", "add_revenue_line", "add_revenue_lines",
    "setup_settlement_with_lines", "reconcile_settlement", "reconcile_to_reconciled",
    "post_rebate", "setup_settlement_with_rebate",
    "create_shrink_audit", "count_shrink_audit", "setup_counted_audit",
    "create_delivery_window", "place_fresh_order", "confirm_fresh_order",
    "lock_delivery_window", "deliver_fresh_order", "reconcile_fresh_order",
    "refresh_window", "setup_window_with_orders", "setup_delivered_order",
    "create_draw", "refresh_franchisee", "suspend_franchisee",
    "reinstate_franchisee", "terminate_franchisee", "finalize_settlement",
    "setup_reinstate_scenario",
]
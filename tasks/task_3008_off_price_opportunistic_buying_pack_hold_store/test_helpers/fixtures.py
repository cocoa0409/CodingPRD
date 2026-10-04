"""Composite setup helpers for multi-step test prerequisites.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the server is restarted and the database reset before each test).
Fixtures use get_success_data() so setup failures surface as clear errors.

Canonical scenario conventions:
- The default logical clock reads 2026-09-01T00:00:00Z (server startup default).
- setup_base() builds: clock pinned + buying season (DRAFT, version 1) +
  zone MT (compare_at_multiplier 2.0, cadence 4, clearance 12) + vendor STANDARD.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_allocation_plan_payload,
    create_lot_line_payload,
    create_lot_payload,
    create_packaway_hold_payload,
    create_price_zone_payload,
    create_receipt_payload,
    create_season_payload,
    create_store_payload,
    create_store_sku_payload,
    create_target_season_payload,
    create_ticket_payload,
    create_vendor_payload,
    create_warehouse_payload,
)
from .test_users import TEST_USERS

BUYER = TEST_USERS["buyer_headers"]
PLANNER = TEST_USERS["planning_lead_headers"]
ALLOCATOR = TEST_USERS["allocation_manager_headers"]
INVENTORY = TEST_USERS["inventory_planner_headers"]
PRICING = TEST_USERS["pricing_analyst_headers"]
CLERK = TEST_USERS["warehouse_clerk_headers"]
STORE_OPS = TEST_USERS["store_ops_lead_headers"]
AUDITOR = TEST_USERS["shrink_auditor_headers"]


def set_clock(to_iso8601: str = "2026-09-01T00:00:00Z") -> dict:
    """Advance the logical clock (PlanningLead only)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, PLANNER))


def make_zone(zone_code: str = "MT", **overrides) -> dict:
    """Create a price zone (PricingAnalyst)."""
    return get_success_data(
        api_client.create_price_zone(create_price_zone_payload(zone_code=zone_code, **overrides), PRICING)
    )


def make_vendor(**overrides) -> dict:
    """Register a vendor (PlanningLead)."""
    return get_success_data(api_client.create_vendor(create_vendor_payload(**overrides), PLANNER))


def make_warehouse(zone_code: str = "MT", **overrides) -> dict:
    """Create a warehouse (InventoryPlanner)."""
    return get_success_data(
        api_client.create_warehouse(create_warehouse_payload(zone_code=zone_code, **overrides), INVENTORY)
    )


def make_store(**overrides) -> dict:
    """Create a store (AllocationManager)."""
    return get_success_data(api_client.create_store(create_store_payload(**overrides), ALLOCATOR))


def setup_base(season_budget: int = TEST_DEFAULTS["SEASON_BUDGET"],
               season_reserve_ratio: float = TEST_DEFAULTS["SEASON_RESERVE_RATIO"],
               zone_code: str = "MT", zone_overrides: dict = None,
               vendor_overrides: dict = None) -> dict:
    """Clock pinned at the startup default + DRAFT buying season + zone + STANDARD vendor.

    Returns a dict with keys: season, zone, vendor.
    """
    set_clock(TEST_DEFAULTS.get("CLOCK_PIN", "2026-09-01T00:00:00Z"))
    season = get_success_data(
        api_client.create_season(
            create_season_payload(
                department_otb_budget_cents=season_budget,
                packaway_reserve_ratio=season_reserve_ratio,
            ),
            PLANNER,
        )
    )
    zone = make_zone(zone_code=zone_code, **(zone_overrides or {}))
    vendor = make_vendor(**(vendor_overrides or {}))
    return {"season": season, "zone": zone, "vendor": vendor}


def open_season(season: dict) -> dict:
    """Open a DRAFT season (PlanningLead). Returns the season read after opening.
    No-ops (returns the current read) when the season is already OPEN so that
    scenario builders can defensively ensure an open season."""
    current = get_success_data(api_client.get_season(season["id"], PLANNER))
    if current["status"] != "DRAFT":
        return current
    opened = get_success_data(api_client.open_season(season["id"], PLANNER))
    return opened


def make_lot(vendor_id: str, season_id: str, **overrides) -> dict:
    """Register an OFFERED lot (Buyer)."""
    return get_success_data(api_client.create_lot(create_lot_payload(vendor_id, season_id, **overrides), BUYER))


def make_lot_line(lot_id: str, **overrides) -> dict:
    """Add a lot line to an OFFERED or EVALUATED lot (Buyer)."""
    return get_success_data(api_client.create_lot_line(lot_id, create_lot_line_payload(**overrides), BUYER))


def evaluate_lot(lot_id: str, negotiated_price_cents=None) -> dict:
    """Evaluate (or re-evaluate) a lot (Buyer). Returns the evaluated lot."""
    payload = {}
    if negotiated_price_cents is not None:
        payload["negotiated_price_cents"] = negotiated_price_cents
    return get_success_data(api_client.evaluate_lot(lot_id, payload, BUYER))


def get_season(season_id: str) -> dict:
    return get_success_data(api_client.get_season(season_id, PLANNER))


def get_lot(lot_id: str) -> dict:
    return get_success_data(api_client.get_lot(lot_id, BUYER))


def get_hold(hold_id: str) -> dict:
    return get_success_data(api_client.get_packaway_hold(hold_id, INVENTORY))


def accept_lot(lot_id: str, season_id: str) -> dict:
    """Accept an EVALUATED lot with the season's current version (OCC). Returns the lot."""
    season = get_season(season_id)
    return get_success_data(
        api_client.accept_lot(lot_id, {"expected_season_version": season["version"]}, BUYER)
    )


def make_accepted_lot(vendor_id: str, season_id: str, with_line: bool = True,
                      negotiated_price_cents=None, line_overrides: dict = None, **overrides) -> dict:
    """Create a lot, optionally one lot line, evaluate it, accept it against the
    season's current version. Returns {"lot", "line", "season"}."""
    lot = make_lot(vendor_id, season_id, **overrides)
    line = None
    if with_line:
        line = make_lot_line(lot["id"], **(line_overrides or {}))
    lot = evaluate_lot(lot["id"], negotiated_price_cents)
    lot = accept_lot(lot["id"], season_id)
    return {"lot": lot, "line": line, "season": get_season(season_id)}


def make_approved_packaway_lot(vendor_id: str, season_id: str, target_season_id: str,
                               **overrides) -> dict:
    """Accepted PACKAWAY lot pointing at a DRAFT target season."""
    overrides.setdefault("lot_type", "PACKAWAY")
    overrides.setdefault("disposition", "PACKAWAY")
    overrides["target_season_id"] = target_season_id
    return make_accepted_lot(vendor_id, season_id, with_line=False, **overrides)


def make_hold(lot_id: str, warehouse_id: str, **overrides) -> dict:
    """Enter an ACCEPTED packaway lot into storage (InventoryPlanner)."""
    return get_success_data(
        api_client.create_packaway_hold(create_packaway_hold_payload(lot_id, warehouse_id, **overrides), INVENTORY)
    )


def make_ticket(lot_line_id: str, zone_code: str = "MT", **overrides) -> dict:
    """Issue a ticket for an ACCEPTED lot's line (PricingAnalyst)."""
    return get_success_data(
        api_client.create_ticket(create_ticket_payload(lot_line_id, zone_code=zone_code, **overrides), PRICING)
    )


def make_store_sku(store_id: str, lot_line_id: str, ticket_id: str, season_id: str, **overrides) -> dict:
    """Manually place units of a lot line at a store (StoreOpsLead)."""
    return get_success_data(
        api_client.create_store_sku(
            create_store_sku_payload(store_id, lot_line_id, ticket_id, season_id, **overrides), STORE_OPS
        )
    )


def make_allocation_plan(lot_id: str, season_id: str, total_units: int, cluster_weights: dict) -> dict:
    """Create a DRAFT allocation plan with the lot's current version (OCC)."""
    lot = get_lot(lot_id)
    return get_success_data(
        api_client.create_allocation_plan(
            create_allocation_plan_payload(lot_id, season_id, lot["version"],
                                           total_units=total_units,
                                           cluster_weights=cluster_weights),
            ALLOCATOR,
        )
    )


def setup_floor_sku(units_on_hand: int = 10, target_retail_cents: int = 10_000,
                    compare_at_claim_cents: int = 25_000, clearance_outlet: bool = False,
                    lot_overrides: dict = None, line_overrides: dict = None,
                    season_budget: int = TEST_DEFAULTS["SEASON_BUDGET"]) -> dict:
    """Full chain to one live StoreSku in zone MT:
    base (season OPEN) + accepted lot + line + ticket + store + manual placement.
    Returns {"base", "lot", "line", "ticket", "store", "sku"}."""
    base = setup_base(season_budget=season_budget)
    base["season"] = open_season(base["season"])
    line_opts = {"target_retail_cents": target_retail_cents,
                 "compare_at_claim_cents": compare_at_claim_cents}
    line_opts.update(line_overrides or {})
    accepted = make_accepted_lot(
        base["vendor"]["id"], base["season"]["id"],
        line_overrides=line_opts,
        **(lot_overrides or {}),
    )
    ticket = make_ticket(accepted["line"]["id"], zone_code=base["zone"]["zone_code"])
    store = make_store(clearance_outlet=clearance_outlet)
    sku = make_store_sku(store["id"], accepted["line"]["id"], ticket["id"], base["season"]["id"],
                         units_on_hand=units_on_hand)
    return {"base": base, "lot": accepted["lot"], "line": accepted["line"],
            "ticket": ticket, "store": store, "sku": sku}


def setup_receipt_scenario(received_qty: int = None, lot_overrides: dict = None,
                           line_specs: list = None, season_budget: int = TEST_DEFAULTS["SEASON_BUDGET"]) -> dict:
    """Season OPEN + accepted lot + warehouse + OPEN receipt whose lines are created
    automatically. If received_qty is not None (int or list per line), records it.
    Returns {"base", "lot", "lines", "warehouse", "receipt", "receipt_lines"}."""
    base = setup_base(season_budget=season_budget)
    base["season"] = open_season(base["season"])
    lot_opts = dict(lot_overrides or {})
    negotiated = lot_opts.pop("negotiated_price_cents", None)
    overrides = {"disposition": "IMMEDIATE"}
    overrides.update(lot_opts)
    lot = make_lot(base["vendor"]["id"], base["season"]["id"], **overrides)
    lines = []
    for spec in (line_specs or [{}]):
        lines.append(make_lot_line(lot["id"], **spec))
    # Lines can only be added while the lot is OFFERED or EVALUATED, so evaluate
    # and accept only after all lines exist.
    lot = evaluate_lot(lot["id"], negotiated)
    lot = accept_lot(lot["id"], base["season"]["id"])
    warehouse = make_warehouse()
    receipt = get_success_data(
        api_client.create_receipt(create_receipt_payload(lot["id"], warehouse["id"]), CLERK)
    )
    receipt_lines = get_success_data(api_client.list_receipt_lines(receipt["id"], CLERK))
    receipt_lines = receipt_lines if isinstance(receipt_lines, list) else receipt_lines.get("data", [])
    if received_qty is not None:
        qtys = received_qty if isinstance(received_qty, list) else [received_qty] * len(receipt_lines)
        for rl, qty in zip(receipt_lines, qtys):
            get_success_data(api_client.update_receipt_line(receipt["id"], rl["id"], {"received_qty": qty}, CLERK))
    return {"base": base, "lot": lot, "lines": lines, "warehouse": warehouse,
            "receipt": receipt, "receipt_lines": receipt_lines}

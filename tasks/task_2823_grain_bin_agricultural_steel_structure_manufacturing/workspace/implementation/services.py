"""Aggregate recomputation and the cascade chains."""
import calc
import store
from common import D, rhu
from store import touch

# Production states whose credit_hold_cents participate in the dealer ledger.
LEDGER_STATES = ("QUEUED", "KITTED", "SHIPPED", "HOLD_CREDIT", "HOLD_ENGINEERING")


# ---------------------------------------------------------------------------
# Dealer credit ledger, plus the second hop of the credit chain
# ---------------------------------------------------------------------------
def recompute_dealer_ledger(dealer):
    """Recompute the ledger from scratch and run the ACTIVE/CREDIT_HOLD sweep."""
    committed = 0
    for order in store.orders_of_dealer(dealer["id"]):
        if order["production_status"] in LEDGER_STATES:
            committed += order["credit_hold_cents"]
    available = dealer["credit_limit_cents"] - committed
    dealer["credit_committed_cents"] = committed
    dealer["credit_available_cents"] = available
    previous = dealer["status"]
    dealer["status"] = "CREDIT_HOLD" if available < 0 else "ACTIVE"
    touch(dealer)

    if dealer["status"] == previous:
        return dealer

    if dealer["status"] == "CREDIT_HOLD":
        for order in store.orders_of_dealer(dealer["id"]):
            if order["production_status"] == "QUEUED":
                order["production_status"] = "HOLD_CREDIT"
                touch(order)
    else:
        for order in store.orders_of_dealer(dealer["id"]):
            if order["production_status"] == "HOLD_CREDIT":
                order["production_status"] = "QUEUED"
                touch(order)
    # Both swept states participate in the ledger sum, so the committed total is
    # unchanged by the sweep and no second recomputation is needed.
    return dealer


def recompute_staged_kit_count(dealer, bump=True):
    """The count of that dealership's PLANNED loads. `bump` is false on the
    cascade hops whose PRD version enumeration omits the dealership row."""
    count = 0
    for load in store.loads_of_dealer(dealer["id"]):
        if load["status"] == "PLANNED":
            count += 1
    dealer["staged_kit_count"] = count
    if bump:
        touch(dealer)
    return dealer


# ---------------------------------------------------------------------------
# Freight load aggregates and the linehaul split
# ---------------------------------------------------------------------------
def recompute_load(load):
    """Re-derive the whole load from the attached set, renumbering sequences."""
    attached = store.orders_on_load(load["id"])

    if not attached:
        load["assigned_cube_m3"] = D("0")
        load["assigned_weight_kg"] = D("0")
        load["cube_utilization_pct"] = D("0")
        load["linehaul_cost_cents"] = 0
        load["order_count"] = 0
        return load

    assigned_cube = rhu(sum((D(o["kit_cube_m3"]) for o in attached), D(0)), 3)
    assigned_weight = rhu(sum((D(o["kit_weight_kg"]) for o in attached), D(0)), 2)
    total = calc.linehaul_cost_cents(load["trailer_type"], assigned_weight)

    load["assigned_cube_m3"] = assigned_cube
    load["assigned_weight_kg"] = assigned_weight
    load["cube_utilization_pct"] = calc.cube_utilization_pct(assigned_cube, load["max_cube_m3"])
    load["linehaul_cost_cents"] = total
    load["order_count"] = len(attached)

    shares = calc.freight_shares(
        attached, load["allocation_basis"], total, assigned_weight, assigned_cube
    )
    for index, order in enumerate(attached):
        sequence = index + 1
        share = shares[index]
        if order["freight_sequence"] != sequence or order["allocated_freight_cents"] != share:
            order["freight_sequence"] = sequence
            order["allocated_freight_cents"] = share
            touch(order)
    return load


def detach_order(order, bump_dealer=True):
    """Detach an order from a load still in PLANNED, re-deriving the split and
    cancelling a load the detach leaves empty. Returns the affected load."""
    load_id = order["freight_load_id"]
    if load_id is None:
        return None
    load = store.freight_loads.get(load_id)
    if load is None or load["status"] != "PLANNED":
        return None
    order["freight_load_id"] = None
    order["allocated_freight_cents"] = 0
    order["freight_sequence"] = None
    touch(order)
    recompute_load(load)
    touch(load)
    if load["order_count"] == 0:
        load["status"] = "CANCELLED"
        dealer = store.dealers.get(load["dealer_id"])
        if dealer is not None:
            recompute_staged_kit_count(dealer, bump=bump_dealer)
    return load


# ---------------------------------------------------------------------------
# Coil lot mass ledger
# ---------------------------------------------------------------------------
def recompute_coil_lot(lot):
    reserved = D(0)
    consumed = D(0)
    scrap = D(0)
    for run in store.runs_of_lot(lot["id"]):
        if run["status"] == "SCHEDULED":
            reserved += D(run["planned_kg"])
        elif run["status"] == "COMPLETED":
            consumed += D(run["consumed_kg"])
            scrap += D(run["scrap_kg"])
    lot["reserved_kg"] = rhu(reserved, 2)
    lot["consumed_kg"] = rhu(consumed, 2)
    lot["scrap_kg"] = rhu(scrap, 2)
    lot["remaining_kg"] = rhu(
        D(lot["received_kg"]) - lot["reserved_kg"] - lot["consumed_kg"] - lot["scrap_kg"], 2
    )
    if lot["status"] != "QUARANTINED":
        lot["status"] = "DEPLETED" if lot["remaining_kg"] == 0 else "AVAILABLE"
    touch(lot)
    return lot


# ---------------------------------------------------------------------------
# The four determination branches
# ---------------------------------------------------------------------------
def cascade_structural_underdesign(design):
    """Hop 1 recalls the design, hop 2 holds its shippable orders, hop 3 detaches
    them from PLANNED loads and re-derives the split, hop 4 cancels an emptied
    load. The dealership row is not part of this chain's version enumeration."""
    if design is None:
        return
    if design["status"] in ("SEALED", "UNDER_REVIEW"):
        design["status"] = "RECALLED"
        touch(design)
    else:
        return
    for order in store.orders_of_design(design["id"]):
        if order["production_status"] in ("QUEUED", "KITTED"):
            order["production_status"] = "HOLD_ENGINEERING"
            touch(order)
            detach_order(order, bump_dealer=False)


def cascade_coating_inadequate(coating_spec_id):
    """Hop 1 quarantines every AVAILABLE or DEPLETED lot on that coating, hop 2
    voids each lot's SCHEDULED runs, hop 3 drops their reservations."""
    if coating_spec_id is None:
        return
    for lot in store.ordered(store.coil_lots):
        if lot["coating_spec_id"] != coating_spec_id:
            continue
        if lot["status"] not in ("AVAILABLE", "DEPLETED"):
            continue
        lot["status"] = "QUARANTINED"
        touch(lot)
        for run in store.runs_of_lot(lot["id"]):
            if run["status"] == "SCHEDULED":
                run["status"] = "VOIDED"
                touch(run)
        recompute_coil_lot(lot)


def cascade_installation_defect(crew):
    """Hop 1 downgrades the crew one tier, hop 2 blocks its live orders."""
    if crew is None:
        return
    if crew["status"] != "CERTIFIED":
        return
    tier, status = calc.crew_downgrade(crew["certification_tier"])
    crew["certification_tier"] = tier
    crew["max_diameter_m"] = calc.CREW_TIER_MAX_DIAMETER_M[tier]
    crew["status"] = status
    touch(crew)
    for order in store.orders_of_crew(crew["id"]):
        if order["production_status"] in ("CANCELLED", "SHIPPED"):
            continue
        if order["installation_readiness"] == "ASSIGNED":
            order["installation_readiness"] = "BLOCKED"
            touch(order)


def apply_determination(failure):
    """OVERLOAD_MISUSE is the quiet branch: no cross-entity effect fires."""
    cause = failure["determined_cause"]
    if cause == "STRUCTURAL_UNDERDESIGN":
        cascade_structural_underdesign(store.bin_designs.get(failure["bin_design_id"]))
    elif cause == "COATING_INADEQUATE":
        design = store.bin_designs.get(failure["bin_design_id"])
        cascade_coating_inadequate(design["coating_spec_id"] if design else None)
    elif cause == "INSTALLATION_DEFECT":
        order = store.dealer_orders.get(failure["dealer_order_id"])
        crew_id = order["installation_crew_id"] if order else None
        cascade_installation_defect(store.installation_crews.get(crew_id) if crew_id else None)

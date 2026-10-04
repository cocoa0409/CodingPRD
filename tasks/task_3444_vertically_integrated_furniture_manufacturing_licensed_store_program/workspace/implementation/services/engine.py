"""Multi-entity business events: waterfall, promotion sweep, cascades, scoring."""
from datetime import timedelta
from decimal import Decimal

from constants import (
    PERF_PROBATION_THRESHOLD, PERF_RECOVERY_THRESHOLD, PERF_SUSPENSION_THRESHOLD,
    SEASONED_WEIGHTS,
)
from db import store
from services import calc
from util import now_dt, touch


# ---------------------------------------------------------------------------
# Shared leaf events
# ---------------------------------------------------------------------------

def deliver_order(order, bumped):
    """SHIPPED -> DELIVERED side effects (PRD §3.5): delivered_at, royalty, credit."""
    order["fulfillment_state"] = "DELIVERED"
    order["delivered_at"] = now_dt()
    touch(order, bumped)
    if order["buyer_type"] == "LICENSEE":
        lic = store.licensees.get(order["licensee_id"])
        if lic is not None:
            order["_royalty_cents"] = calc.royalty_for(order["final_total_cents"], lic["royalty_rate"])
            if calc.recompute_ledger(lic):
                touch(lic, bumped)
    else:
        acct = store.retail_accounts.get(order["retail_account_id"])
        if acct is not None and calc.recompute_credit(acct):
            touch(acct, bumped)


def drop_order(order, cancel_fulfillment, bumped):
    """allocation -> DROPPED. Fulfillment -> CANCELLED only on the cancel/terminate/close path."""
    order["allocation_state"] = "DROPPED"
    if cancel_fulfillment:
        order["fulfillment_state"] = "CANCELLED"
    touch(order, bumped)


def _accounts_of(orders):
    return {o["retail_account_id"] for o in orders if o["buyer_type"] == "RETAIL_ACCOUNT"}


def _recompute_accounts(account_ids, bumped):
    for aid in account_ids:
        acct = store.retail_accounts.get(aid)
        if acct is not None and calc.recompute_credit(acct):
            touch(acct, bumped)


# ---------------------------------------------------------------------------
# capacity_waterfall promotion sweep (PRD §3.4): single rank-ordered scan.
# ---------------------------------------------------------------------------

def promotion_sweep(cycle, bumped):
    if cycle["status"] not in ("OPEN", "ALLOCATED"):
        return
    calc.recompute_cycle(cycle)
    remaining = cycle["available_units"]
    waitlisted = sorted(
        (o for o in store.orders.values()
         if o["allocation_cycle_id"] == cycle["id"] and o["allocation_state"] == "WAITLISTED"),
        key=calc.rank_key,
    )
    promoted_accounts = set()
    for o in waitlisted:
        if o["quantity"] <= remaining:
            if cycle["status"] == "OPEN":
                o["allocation_state"] = "RESERVED"
            else:  # ALLOCATED: lock final price off the line's current lifecycle
                line = store.product_lines.get(o["product_line_id"])
                o["allocation_state"] = "ALLOCATED"
                o["final_total_cents"] = calc.final_total_cents(o, line)
                o["_reached_allocated"] = True
            touch(o, bumped)
            remaining -= o["quantity"]
            if o["buyer_type"] == "RETAIL_ACCOUNT":
                promoted_accounts.add(o["retail_account_id"])
    if calc.recompute_cycle(cycle):
        touch(cycle, bumped)
    _recompute_accounts(promoted_accounts, bumped)


# ---------------------------------------------------------------------------
# capacity_waterfall run (PRD §3.4): licensee pass then wholesale best-fit pass.
# ---------------------------------------------------------------------------

def run_waterfall(cycle, bumped):
    K = cycle["capacity_units"]
    wholesale_floor = K // 4  # floor(K * 0.25)
    licensee_cap = K - wholesale_floor

    candidates = [
        o for o in store.orders.values()
        if o["allocation_cycle_id"] == cycle["id"]
        and o["allocation_state"] in ("RESERVED", "WAITLISTED")
    ]
    licensee_orders = sorted(
        (o for o in candidates if o["buyer_type"] == "LICENSEE"), key=calc.rank_key)
    wholesale_orders = sorted(
        (o for o in candidates if o["buyer_type"] == "RETAIL_ACCOUNT"), key=calc.rank_key)

    selected = set()
    dropped = set()

    remaining = licensee_cap
    licensee_selected_qty = 0
    for o in licensee_orders:
        line = store.product_lines.get(o["product_line_id"])
        if line is not None and line["lifecycle"] == "RETIRED":
            dropped.add(o["id"])  # RETIRED at run time: dropped, consumes nothing
            continue
        if o["quantity"] <= remaining:
            selected.add(o["id"])
            remaining -= o["quantity"]
            licensee_selected_qty += o["quantity"]

    wholesale_cap = K - licensee_selected_qty
    remaining = wholesale_cap
    for o in wholesale_orders:
        line = store.product_lines.get(o["product_line_id"])
        if line is not None and line["lifecycle"] == "RETIRED":
            dropped.add(o["id"])
            continue
        if o["quantity"] <= remaining:
            selected.add(o["id"])
            remaining -= o["quantity"]

    for o in candidates:
        if o["id"] in dropped:
            drop_order(o, cancel_fulfillment=False, bumped=bumped)
        elif o["id"] in selected:
            line = store.product_lines[o["product_line_id"]]
            o["allocation_state"] = "ALLOCATED"
            o["final_total_cents"] = calc.final_total_cents(o, line)
            o["_reached_allocated"] = True
            touch(o, bumped)
        else:
            # Not selected -> WAITLISTED (demotion of RESERVED orders is possible).
            if o["allocation_state"] != "WAITLISTED":
                o["allocation_state"] = "WAITLISTED"
                touch(o, bumped)

    if calc.recompute_cycle(cycle):
        touch(cycle, bumped)
    _recompute_accounts(_accounts_of(candidates), bumped)


# ---------------------------------------------------------------------------
# AllocationCycle close (PRD §3.4 + §3.8)
# ---------------------------------------------------------------------------

def close_cycle(cycle, bumped):
    cycle["status"] = "CLOSED"
    cycle["closed_at"] = now_dt()
    touch(cycle, bumped)

    cycle_orders = [o for o in store.orders.values() if o["allocation_cycle_id"] == cycle["id"]]
    for o in cycle_orders:
        if o["allocation_state"] == "WAITLISTED":
            drop_order(o, cancel_fulfillment=True, bumped=bumped)
    if calc.recompute_cycle(cycle):
        touch(cycle, bumped)

    licensee_ids = {
        o["licensee_id"] for o in cycle_orders
        if o["buyer_type"] == "LICENSEE" and o["allocation_state"] != "UNALLOCATED"
    }
    scored = [store.licensees[lid] for lid in licensee_ids if lid in store.licensees]
    scored.sort(key=lambda l: (l["created_at"], l["_seq"]))
    for lic in scored:
        _score_licensee(lic, cycle, cycle_orders, bumped)


def _score_licensee(lic, cycle, cycle_orders, bumped):
    mine = [
        o for o in cycle_orders
        if o["buyer_type"] == "LICENSEE" and o["licensee_id"] == lic["id"]
        and o["allocation_state"] != "UNALLOCATED"
    ]
    counted = [o for o in mine if o["_reached_allocated"] and o["allocation_state"] != "DROPPED"]
    allocated_units = sum(o["quantity"] for o in counted)
    delivered = [o for o in counted if o["fulfillment_state"] == "DELIVERED"]
    delivered_units = sum(o["quantity"] for o in delivered)
    sell_through = Decimal(100 * delivered_units) / Decimal(max(1, allocated_units))
    delivered_order_count = len(delivered)
    claims_in_cycle = sum(
        1 for c in store.claims.values()
        if c.get("licensee_id") == lic["id"]
        and cycle["week_start"] <= c["created_at"] <= cycle["closed_at"]
    )
    claims_pct = Decimal(100 * claims_in_cycle) / Decimal(max(1, delivered_order_count))
    claims_component = max(Decimal("0"), Decimal("100") - Decimal("10") * claims_pct)
    instantaneous = calc.round2(
        Decimal("0.5") * sell_through
        + Decimal("0.3") * Decimal(lic["latest_audit_score"])
        + Decimal("0.2") * claims_component
    )
    history = store.score_history.setdefault(lic["id"], [])
    history.append(instantaneous)
    recent = history[-4:][::-1]  # most recent first
    weights = SEASONED_WEIGHTS[:len(recent)]
    weight_sum = sum(weights)
    seasoned = calc.round2(
        sum(w * s for w, s in zip(weights, recent)) / weight_sum
    )
    lic["last_cycle_score"] = instantaneous
    lic["seasoned_score"] = seasoned
    touch(lic, bumped)
    # Seasoned score drives standing; boundary equalities do NOT trigger.
    if lic["status"] == "ACTIVE" and seasoned < PERF_PROBATION_THRESHOLD:
        lic["status"] = "PROBATION"
    elif lic["status"] == "PROBATION" and seasoned >= PERF_RECOVERY_THRESHOLD:
        lic["status"] = "ACTIVE"
    elif lic["status"] == "PROBATION" and seasoned < PERF_SUSPENSION_THRESHOLD:
        lic["status"] = "SUSPENDED"


# ---------------------------------------------------------------------------
# ProductLine RETIRED cascade (PRD §3.1): fulfillment deliberately unchanged.
# ---------------------------------------------------------------------------

def retire_line(line, bumped):
    affected_cycles = set()
    affected_accounts = set()
    for o in store.orders.values():
        if o["product_line_id"] == line["id"] and o["allocation_state"] in ("RESERVED", "WAITLISTED"):
            drop_order(o, cancel_fulfillment=False, bumped=bumped)
            affected_cycles.add(o["allocation_cycle_id"])
            if o["buyer_type"] == "RETAIL_ACCOUNT":
                affected_accounts.add(o["retail_account_id"])
    for cid in affected_cycles:
        c = store.cycles.get(cid)
        if c is not None and calc.recompute_cycle(c):
            touch(c, bumped)
    _recompute_accounts(affected_accounts, bumped)
    for cid in affected_cycles:
        c = store.cycles.get(cid)
        if c is not None and c["status"] in ("OPEN", "ALLOCATED"):
            promotion_sweep(c, bumped)


# ---------------------------------------------------------------------------
# Territory revocation (PRD §3.2) — shared by manual revoke and termination.
# ---------------------------------------------------------------------------

def revoke_territory(terr, bumped):
    former = terr["assigned_licensee_id"]
    terr["status"] = "OPEN"
    terr["assigned_licensee_id"] = None
    terr["assigned_at"] = None
    terr["revoked_at"] = now_dt()
    touch(terr, bumped)
    if former is None:
        return
    for a in store.appointments.values():
        if (a["licensee_id"] == former and a["region_code"] == terr["region_code"]
                and a["status"] in ("REQUESTED", "CONFIRMED")):
            was_confirmed = a["status"] == "CONFIRMED"
            a["status"] = "CANCELLED"
            touch(a, bumped)
            if was_confirmed:
                o = store.orders.get(a["supply_order_id"])
                if o is not None and o["fulfillment_state"] == "SHIPPED":
                    o["fulfillment_state"] = "PICKED"  # compensation
                    touch(o, bumped)


# ---------------------------------------------------------------------------
# Licensee TERMINATED cascade (PRD §3.2) — SNAPSHOT drop-set semantics.
# ---------------------------------------------------------------------------

def terminate_licensee(lic, bumped):
    # Snapshot the drop set from fulfillment state AS OF NOW, before any
    # appointment cancellation can revert SHIPPED -> PICKED.
    drop_set = [
        o for o in store.orders.values()
        if o.get("licensee_id") == lic["id"]
        and o["allocation_state"] in ("RESERVED", "ALLOCATED", "WAITLISTED")
        and o["fulfillment_state"] in ("PENDING", "PICKED")
    ]
    # HOP 1a: revoke every assigned territory (HOP 2a appointment cancels ride along,
    # with their HOP 3a SHIPPED -> PICKED compensations — the snapshot above is
    # already fixed, so a reverted order is NOT added to the drop set).
    for t in store.territories.values():
        if t["assigned_licensee_id"] == lic["id"]:
            revoke_territory(t, bumped)
    # HOP 1b: drop the snapshotted orders (fulfillment -> CANCELLED same mutation).
    for o in drop_set:
        drop_order(o, cancel_fulfillment=True, bumped=bumped)
    # HOP 2b: release capacity on each affected cycle.
    affected_cycles = {o["allocation_cycle_id"] for o in drop_set}
    for cid in affected_cycles:
        c = store.cycles.get(cid)
        if c is not None and calc.recompute_cycle(c):
            touch(c, bumped)
    # HOP 3b: waitlist promotion sweep per affected cycle.
    for cid in affected_cycles:
        c = store.cycles.get(cid)
        if c is not None and c["status"] in ("OPEN", "ALLOCATED"):
            promotion_sweep(c, bumped)


# ---------------------------------------------------------------------------
# Missed-appointment sweep (PRD §2.5): atomic with the clock set.
# ---------------------------------------------------------------------------

def missed_sweep(new_clock, bumped):
    grace = timedelta(minutes=120)
    for a in store.appointments.values():
        if a["status"] == "CONFIRMED" and a["window_end"] + grace < new_clock:
            a["status"] = "MISSED"
            touch(a, bumped)
            o = store.orders.get(a["supply_order_id"])
            if o is not None and o["fulfillment_state"] == "SHIPPED":
                o["fulfillment_state"] = "PICKED"
                touch(o, bumped)

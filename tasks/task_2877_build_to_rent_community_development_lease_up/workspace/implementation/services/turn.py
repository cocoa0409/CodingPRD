"""Turn work order windows, capacity and the cost waterfall (PRD section 3.10)."""
from __future__ import annotations

import repo
from datetime import timedelta

SCOPE_RATE_CENTS_PER_TECH_HOUR = {
    "MAKE_READY": 6500,
    "DETACHED_YARD_RESTORE": 8000,
    "MAJOR_REHAB": 11000,
}
TURN_SCOPES = ("MAKE_READY", "DETACHED_YARD_RESTORE", "MAJOR_REHAB")
MAX_WINDOW_HOURS = 240
REWORK_BUFFER = timedelta(hours=48)
TURN_OPEX_CAP_CENTS = 80000
DEPARTING_LEASE_STATUSES = ("ENDING", "ENDED")


def window_hours(start, end):
    """The length of the window in whole hours, or None when it is not whole."""
    seconds = (end - start).total_seconds()
    if seconds <= 0:
        return None
    if seconds % 3600 != 0:
        return None
    return int(seconds // 3600)


def overlaps(a_start, a_end, b_start, b_end):
    """Half-open intersection: an order ending exactly when the next begins is fine."""
    return a_start < b_end and b_start < a_end


def recoverable_cap_cents(homesite):
    """The gross monthly charge of the most recent departing lease on this home,
    ranked executed_at descending then created_at descending; 0 when none exists."""
    departing = [l for l in repo.leases_of_homesite(homesite)
                 if l["lease_status"] in DEPARTING_LEASE_STATUSES]
    if not departing:
        return 0
    chosen = max(departing, key=lambda l: (
        l["_executed_at"] is not None,
        l.get("_executed_at") or l["_created"],
        l["_created"],
        l["_seq"],
    ))
    return chosen["gross_monthly_charge_cents"]


def allocate(total_turn_cost_cents, cap_cents):
    """A strict waterfall: each bucket fills completely before the next receives
    anything, and the three buckets always sum to the total."""
    tenant = total_turn_cost_cents if total_turn_cost_cents < cap_cents else cap_cents
    remainder = total_turn_cost_cents - tenant
    opex = remainder if remainder < TURN_OPEX_CAP_CENTS else TURN_OPEX_CAP_CENTS
    capital = remainder - opex
    return tenant, opex, capital


def compute_costs(homesite, scope, tech_count, hours, material_cost_cents):
    labor = tech_count * hours * SCOPE_RATE_CENTS_PER_TECH_HOUR[scope]
    total = labor + material_cost_cents
    tenant, opex, capital = allocate(total, recoverable_cap_cents(homesite))
    return {
        "window_hours": hours,
        "labor_cost_cents": labor,
        "total_turn_cost_cents": total,
        "tenant_recoverable_cents": tenant,
        "community_opex_cents": opex,
        "capital_reserve_cents": capital,
    }


def peak_tech_demand(community, start, end, exclude_id=None):
    """The technicians already committed at the busiest hour covered by [start, end)."""
    scheduled = [t for t in repo.turn_orders_of_community(community)
                 if t["status"] == "SCHEDULED" and t["id"] != exclude_id
                 and overlaps(start, end, t["_window_start"], t["_window_end"])]
    if not scheduled:
        return 0
    points = {start}
    for order in scheduled:
        if order["_window_start"] > start:
            points.add(order["_window_start"])
    peak = 0
    for point in sorted(points):
        demand = sum(o["tech_count"] for o in scheduled
                     if o["_window_start"] <= point < o["_window_end"])
        if demand > peak:
            peak = demand
    return peak

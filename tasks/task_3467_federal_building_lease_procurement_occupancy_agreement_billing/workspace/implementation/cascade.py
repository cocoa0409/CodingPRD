"""Space-inventory reconciliation, terminal cascades, and the clock sweep.

available_sf is a stored, computed field maintained by
space_inventory_reconciliation at every event that changes the committed
pool (PRD section 2.9); a change in its value bumps the building's version.
"""
from decimal import Decimal

from calc import rhu
from dates import add_months, parse_date
from store import DB, bump


def sync_building(b):
    """Recompute available_sf from the pinned formula; bump version on change."""
    if not b:
        return
    if b["ownership_type"] == "FEDERALLY_OWNED":
        committed = sum(
            o["assigned_sf"] for o in DB["oas"].values()
            if o.get("building_id") == b["id"] and o["status"] in ("DRAFT", "ACTIVE")
        )
    else:  # LEASED_STOCK
        committed = sum(
            l["leased_sf"] for l in DB["leases"].values()
            if l.get("building_id") == b["id"] and l["status"] in ("AWARDED", "COMMENCED", "EXPIRING")
        )
    avail = b["total_sf"] - committed
    if avail != b["available_sf"]:
        b["available_sf"] = avail
        bump(b)


def oa_terminal_cascade(oa, new_status):
    """The OA terminal cascade (PRD section 3.5): cancel non-terminal
    alterations reversing pending lump charges; accelerate COMPLETED
    AMORTIZED balances into terminal_writeoff_cents; release owned space."""
    oa["status"] = new_status
    bump(oa)
    for alt in DB["alterations"].values():
        if alt["oa_id"] != oa["id"]:
            continue
        if alt["status"] in ("REQUESTED", "ESTIMATED", "APPROVED"):
            alt["status"] = "CANCELLED"
            if alt["lump_charge_status"] == "PENDING":
                alt["lump_charge_status"] = "REVERSED"
            bump(alt)
        elif (alt["status"] == "COMPLETED" and alt["funding_method"] == "AMORTIZED"
              and alt.get("amortization_balance_cents") is not None):
            bal = alt["amortization_balance_cents"]
            oa["terminal_writeoff_cents"] += rhu(bal)
            if bal != 0:
                alt["amortization_balance_cents"] = Decimal(0)
                bump(alt)
    if oa.get("building_id"):
        sync_building(DB["buildings"].get(oa["building_id"]))


def sweep_clock(cur_date):
    """Time-based transitions for a clock advance (PRD sections 2.4, 3.9).

    Returns (transitioned_lease_ids, transitioned_oa_ids, transitioned_plan_ids).
    A lease may move COMMENCED -> EXPIRING -> EXPIRED/SUCCEEDED in one sweep.
    """
    t_leases, t_oas, t_plans = [], [], []
    # COMMENCED -> EXPIRING once current date reaches end_date - 18 months
    for lease in list(DB["leases"].values()):
        if lease["status"] == "COMMENCED" and lease.get("end_date"):
            threshold = add_months(parse_date(lease["end_date"]), -18)
            if cur_date >= threshold:
                lease["status"] = "EXPIRING"
                bump(lease)
                t_leases.append(lease["id"])
    # EXPIRING -> EXPIRED / SUCCEEDED once current date passes end_date
    for lease in list(DB["leases"].values()):
        if lease["status"] == "EXPIRING" and lease.get("end_date") and cur_date > parse_date(lease["end_date"]):
            lease["status"] = "SUCCEEDED" if lease.get("executed_option") == "SUCCEEDING_LEASE" else "EXPIRED"
            bump(lease)
            if lease["id"] not in t_leases:
                t_leases.append(lease["id"])
            # cascade: the lease's DRAFT/ACTIVE OAs expire with their own cascades
            for oa in list(DB["oas"].values()):
                if oa.get("lease_id") == lease["id"] and oa["status"] in ("DRAFT", "ACTIVE"):
                    oa_terminal_cascade(oa, "EXPIRED")
                    t_oas.append(oa["id"])
            # unexecuted plans lapse
            for plan in list(DB["plans"].values()):
                if plan["lease_id"] == lease["id"] and plan["status"] in ("OPEN", "OPTION_SELECTED"):
                    plan["status"] = "CANCELLED"
                    bump(plan)
                    t_plans.append(plan["id"])
            # the lease leaves the committed pool
            sync_building(DB["buildings"].get(lease["building_id"]))
    # natural OA expiry: ACTIVE -> EXPIRED once current date passes end_date
    for oa in list(DB["oas"].values()):
        if oa["status"] == "ACTIVE" and cur_date > parse_date(oa["end_date"]):
            oa_terminal_cascade(oa, "EXPIRED")
            t_oas.append(oa["id"])
    return t_leases, t_oas, t_plans

"""Fund posture recomputation, the parked-project walk, the dividend waterfall
and the period-close checkpoint (PRD 2.9, 3.6, 3.9)."""

import calculations as calc
import derive
from db import clock_now, db, touch


def projects_of_store(store_id, state=None):
    rows = [p for p in db.projects.values() if p["store_id"] == store_id]
    if state is not None:
        rows = [p for p in rows if p["state"] == state]
    rows.sort(key=lambda p: (p["created_at"], p["_seq"]))
    return rows


def programs_of_store(store_id):
    """Waterfall order: priority_rank ASC then created_at ASC."""
    rows = [p for p in db.programs.values() if p["store_id"] == store_id]
    rows.sort(key=lambda p: (p["priority_rank"], p["created_at"], p["_seq"]))
    return rows


def special_orders_of_store(store_id):
    rows = [o for o in db.special_orders.values() if o["store_id"] == store_id]
    rows.sort(key=lambda o: (o["created_at"], o["_seq"]))
    return rows


def walk_awaiting_funds(store):
    """Auto-approve parked projects while the available surcharge covers each
    obligation.  The posture gate is evaluated once, before the walk; the
    available surcharge is re-measured at the moment each project is walked."""
    if derive.fund_posture(store["id"]) != "UNRESTRICTED":
        return []
    approved = []
    for project in projects_of_store(store["id"], "AWAITING_FUNDS"):
        if project["obligation_cents"] <= derive.available_surcharge_cents(store["id"]):
            project["state"] = "APPROVED"
            touch(project)
            approved.append(project)
    return approved


def run_dividend_waterfall(store):
    """Distribute the dividend balance measured BEFORE any transfer in this run."""
    remaining = derive.dividend_fund_balance_cents(store["id"])
    candidates = [p for p in programs_of_store(store["id"]) if p["status"] == "ACTIVE"]
    plan = calc.dividend_waterfall_plan(
        remaining, candidates, lambda program: derive.ytd_funded_cents(program["id"])
    )
    for program, grant in plan:
        derive.append_ledger_entry(
            store,
            "DIVIDEND",
            "DIVIDEND_TRANSFER",
            -grant,
            "MWR_PROGRAM",
            program["id"],
        )
    return plan


def close_period(store):
    """Six steps, strictly in order (PRD 3.9)."""
    now = clock_now()

    # 1. lapsed delegations expire.
    delegations = list(db.delegations.values())
    delegations.sort(key=lambda g: (g["created_at"], g["_seq"]))
    for delegation in delegations:
        if delegation["status"] == "ACTIVE" and delegation["valid_to"] <= now:
            delegation["status"] = "EXPIRED"
            touch(delegation)

    # 2. pending special orders of this store join at FULFILLED.
    for order in special_orders_of_store(store["id"]):
        if order["state"] in ("LOCAL_FILL_PENDING", "OVERSEAS_SHIP_PENDING"):
            order["state"] = "FULFILLED"
            touch(order)

    # 3. the dividend waterfall.
    run_dividend_waterfall(store)

    # 4. dividend balance and fund posture are derived figures — recomputed by
    #    construction from the ledger the waterfall just appended to.

    # 5. parked capital projects.
    walk_awaiting_funds(store)

    # 6. period index and store version.
    store["period_close_index"] += 1
    touch(store)
    return store

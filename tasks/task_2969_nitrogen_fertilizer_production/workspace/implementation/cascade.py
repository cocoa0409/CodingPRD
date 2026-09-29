"""The cascades of PRD 2.12, 3.2, 3.9 and 3.10.

Consistency is immediate: by the time a route returns, every downstream row has
already moved, been version-bumped and had its updated_at refreshed. Sweep
orders are the ones the PRD fixes, never dict order.
"""
import calc
from mutate import touch
from store import db
from util import D


# --------------------------------------------------------------------------
# Sweep orderings (PRD 2.12)
# --------------------------------------------------------------------------
def runs_in_sweep_order(runs):
    return sorted(runs, key=lambda r: (r["window_start"], r["_seq"]))


def orders_in_release_order(orders):
    def key(order):
        line = db.lines.get(order["product_line_id"])
        rank = line["priority_rank"] if line else 0
        return (-rank, order["_seq"])
    return sorted(orders, key=key)


def quotes_in_created_order(quotes):
    return sorted(quotes, key=lambda q: q["_seq"])


# --------------------------------------------------------------------------
# Order release and downstream movement cancellation
# --------------------------------------------------------------------------
def cancel_shipments_of_order(order_id, reason="UPSTREAM_ALLOCATION_RELEASED"):
    ships = sorted([s for s in db.shipments.values()
                    if s["production_order_id"] == order_id
                    and s["status"] in ("DRAFT", "BOOKED")],
                   key=lambda s: s["_seq"])
    for ship in ships:
        was_booked = ship["status"] == "BOOKED"
        ship["status"] = "CANCELLED"
        ship["cancel_reason"] = reason
        touch(ship)
        if was_booked:
            origin = db.assets.get(ship["origin_asset_id"])
            if origin is not None:
                touch(origin)


def release_order(order, reason):
    """RESERVED -> RELEASED, handing the ammonia back to the campaign."""
    order["allocation_status"] = "RELEASED"
    order["release_reason"] = reason
    order["reserved_tons"] = D("0.000")
    order["allocated_ammonia_tons"] = D("0.000")
    touch(order)
    run = db.runs.get(order["run_id"])
    if run is not None:
        touch(run)
    cancel_shipments_of_order(order["id"])


def release_reserved_orders_of_run(run, reason):
    orders = [o for o in db.orders.values()
              if o["run_id"] == run["id"] and o["allocation_status"] == "RESERVED"]
    for order in orders_in_release_order(orders):
        release_order(order, reason)


# --------------------------------------------------------------------------
# Approved-campaign revocation (derate hop 4, freeze hop 2, outage hop 2)
# --------------------------------------------------------------------------
def revert_approved_runs_of_train(train_id):
    runs = [r for r in db.runs.values()
            if r["train_id"] == train_id and r["status"] == "APPROVED"]
    reverted = []
    for run in runs_in_sweep_order(runs):
        run["status"] = "PLANNED"
        run["provisional_unit_cost_usd_per_ton"] = None
        touch(run)
        reverted.append(run)
    return reverted


def revert_approved_runs_of_plant(plant_id):
    train_ids = [t["id"] for t in db.trains.values() if t["plant_id"] == plant_id]
    runs = [r for r in db.runs.values()
            if r["train_id"] in train_ids and r["status"] == "APPROVED"]
    reverted = []
    for run in runs_in_sweep_order(runs):
        run["status"] = "PLANNED"
        run["provisional_unit_cost_usd_per_ton"] = None
        touch(run)
        reverted.append(run)
    return reverted


# --------------------------------------------------------------------------
# The derate cascade (PRD 3.2)
# --------------------------------------------------------------------------
def derate_if_spent(charge):
    """Hops 2-4: a charge that has fallen under the minimum takes its train with it."""
    if charge["status"] != "ACTIVE":
        return False
    if calc.charge_activity_pct(charge) >= calc.CATALYST_MIN_ACTIVITY_PCT:
        return False
    charge["status"] = "SPENT"
    touch(charge)
    train = db.trains.get(charge["train_id"])
    if train is not None and train["status"] != "DOWN_FOR_TURNAROUND":
        train["status"] = "DERATED"
        touch(train)
        revert_approved_runs_of_train(train["id"])
    return True


def recover_if_activity_restored(charge, resume_running=False):
    """The SPENT -> ACTIVE recovery arm shared by regeneration and reopening."""
    if charge["status"] != "SPENT":
        return False
    if calc.charge_activity_pct(charge) < calc.CATALYST_MIN_ACTIVITY_PCT:
        return False
    other = calc.active_charge(charge["train_id"])
    if other is not None:
        return False
    charge["status"] = "ACTIVE"
    touch(charge)
    train = db.trains.get(charge["train_id"])
    if train is not None and train["status"] == "DERATED":
        train["status"] = "RUNNING" if resume_running else "IDLE"
        touch(train)
    return True


# --------------------------------------------------------------------------
# Posture re-derivation and the degrade cascade (PRD 2.8 / 3.10)
# --------------------------------------------------------------------------
def withdraw_issued_quotes(plant_id):
    quotes = [q for q in db.quotes.values()
              if q["plant_id"] == plant_id and q["status"] == "ISSUED"]
    for quote in quotes_in_created_order(quotes):
        quote["status"] = "WITHDRAWN"
        quote["withdraw_reason"] = "PLANT_POSTURE_DEGRADED"
        touch(quote)


def freeze_production(plant_id):
    reverted_ids = [r["id"] for r in revert_approved_runs_of_plant(plant_id)]
    orders = [o for o in db.orders.values()
              if o["run_id"] in reverted_ids and o["allocation_status"] == "RESERVED"]
    for order in orders_in_release_order(orders):
        release_order(order, "PLANT_FROZEN")


def rederive_posture(plant):
    """Rewrite posture and the pollutant list; cascade when the arc degrades."""
    exceeded = calc.exceeded_pollutants(plant)
    posture = calc.operating_posture(plant, exceeded)
    previous = plant["operating_posture"]
    plant["exceeded_pollutants"] = exceeded
    plant["operating_posture"] = posture
    if posture == previous:
        return False
    touch(plant)
    if posture in ("RESTRICTED", "FROZEN"):
        withdraw_issued_quotes(plant["id"])
    if posture == "FROZEN":
        freeze_production(plant["id"])
    return True


# --------------------------------------------------------------------------
# The outage cascade (PRD 3.9)
# --------------------------------------------------------------------------
def outage_start_cascade(turnaround):
    train = db.trains.get(turnaround["train_id"])
    if train is not None:
        train["status"] = "DOWN_FOR_TURNAROUND"
        touch(train)
    aborted = []
    running = [r for r in db.runs.values()
               if r["train_id"] == turnaround["train_id"] and r["status"] == "RUNNING"]
    for run in runs_in_sweep_order(running):
        run["status"] = "ABORTED"
        run["abort_reason"] = "TRAIN_DOWN_FOR_TURNAROUND"
        touch(run)
        aborted.append(run)
    revert_approved_runs_of_train(turnaround["train_id"])
    aborted_ids = [r["id"] for r in aborted]
    orders = [o for o in db.orders.values()
              if o["run_id"] in aborted_ids and o["allocation_status"] == "RESERVED"]
    for order in orders_in_release_order(orders):
        release_order(order, "RUN_ABORTED")
    tasks = sorted([t for t in db.tasks.values()
                    if t["turnaround_id"] == turnaround["id"]
                    and t["predecessor_task_id"] is None
                    and t["status"] == "PENDING"],
                   key=lambda t: t["_seq"])
    for task in tasks:
        task["status"] = "READY"
        touch(task)

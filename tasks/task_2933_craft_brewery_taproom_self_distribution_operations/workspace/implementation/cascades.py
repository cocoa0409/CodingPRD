"""Cross-entity cascades, loss allocation and lazy licence expiry (PRD 2.9)."""

from decimal import Decimal

import calc
import derive
import store
from store import DB


def touch_once(row, seen):
    """Bump a row's version at most once per request."""
    if row is None:
        return
    key = row["id"]
    if key in seen:
        return
    seen.add(key)
    store.touch(row)


# ---------------------------------------------------------------------------
# allocation release
# ---------------------------------------------------------------------------

def release_allocation(order, seen):
    """Return every allocation line of the order to its packaging run."""
    lines = order.get("allocation_lines") or []
    for line in lines:
        run = DB["runs"].get(line.get("packaging_run_id"))
        if run is not None:
            touch_once(run, seen)
    order["allocation_lines"] = []
    order["allocated_bbl"] = calc.bbl(0)


def reject_order(order, reason, seen):
    was_allocated = order.get("state") == "ALLOCATED"
    order["state"] = "REJECTED"
    order["rejection_reason"] = reason
    if was_allocated:
        release_allocation(order, seen)
    touch_once(order, seen)


def reject_live_orders(predicate, reason, seen):
    for order in store.ordered(derive.rows("orders")):
        if order.get("state") not in ("SUBMITTED", "ALLOCATED"):
            continue
        if not predicate(order):
            continue
        reject_order(order, reason, seen)


# ---------------------------------------------------------------------------
# brewer's notice cascades
# ---------------------------------------------------------------------------

def notice_suspended_cascade(seen):
    """Hop 1: ACTIVE licences suspend. Hop 2: their live orders reject. Hop 3: release."""
    suspended_ids = []
    for licence in store.ordered(derive.rows("licenses")):
        if licence.get("status") == "ACTIVE":
            licence["status"] = "SUSPENDED"
            touch_once(licence, seen)
            suspended_ids.append(licence["id"])
    if suspended_ids:
        reject_live_orders(
            lambda order: order.get("state_license_id") in suspended_ids,
            "NOTICE_SUSPENDED", seen)


def notice_revoked_cascade(seen):
    """Every licence, whatever its status, moves to SUSPENDED."""
    affected_ids = []
    for licence in store.ordered(derive.rows("licenses")):
        was_active = licence.get("status") == "ACTIVE"
        if licence.get("status") != "SUSPENDED":
            licence["status"] = "SUSPENDED"
            touch_once(licence, seen)
        if was_active:
            affected_ids.append(licence["id"])
    if affected_ids:
        reject_live_orders(
            lambda order: order.get("state_license_id") in affected_ids,
            "NOTICE_SUSPENDED", seen)


def notice_reinstated_cascade(seen):
    """Only unexpired suspended licences return to ACTIVE."""
    now = store.clock_now()
    for licence in store.ordered(derive.rows("licenses")):
        if licence.get("status") != "SUSPENDED":
            continue
        if licence["expires_at_utc"] > now:
            licence["status"] = "ACTIVE"
            touch_once(licence, seen)


# ---------------------------------------------------------------------------
# COLA revocation cascade (depth 2)
# ---------------------------------------------------------------------------

def cola_revoked_cascade(beer, seen):
    reject_live_orders(lambda order: order.get("beer_id") == beer["id"],
                       "LABEL_REVOKED", seen)


# ---------------------------------------------------------------------------
# appointment activation cascade
# ---------------------------------------------------------------------------

def appointment_activated_cascade(appointment, seen):
    def covered(order):
        if order.get("channel") != "SELF_DISTRIBUTED":
            return False
        if order.get("state_license_id") != appointment["state_license_id"]:
            return False
        return derive.appointment_covers_beer(appointment, order.get("beer_id"))

    reject_live_orders(covered, "APPOINTMENT_ACTIVATED", seen)


# ---------------------------------------------------------------------------
# lazy licence expiry
# ---------------------------------------------------------------------------

def refresh_license_expiry(licence, seen=None):
    if seen is None:
        seen = set()
    if licence.get("status") != "ACTIVE":
        return
    if store.clock_now() < licence["expires_at_utc"]:
        return
    licence["status"] = "EXPIRED"
    touch_once(licence, seen)
    reject_live_orders(lambda order: order.get("state_license_id") == licence["id"],
                       "LICENSE_NOT_ACTIVE", seen)


def refresh_all_license_expiry():
    seen = set()
    for licence in store.ordered(derive.rows("licenses")):
        refresh_license_expiry(licence, seen)


# ---------------------------------------------------------------------------
# packaging loss allocation
# ---------------------------------------------------------------------------

def allocate_packaging_loss(batch, seen):
    runs = derive.completed_runs_of_batch(batch["id"])
    packaged = derive.packaged_bbl(batch)
    yield_bbl = batch.get("actual_yield_bbl")
    if yield_bbl is None:
        total_loss = calc.bbl(0)
    else:
        total_loss = calc.bbl(Decimal(yield_bbl) - packaged)

    zero = calc.bbl(0)
    if not runs or total_loss <= 0:
        for run in runs:
            if run.get("loss_share_bbl") != zero:
                run["loss_share_bbl"] = zero
                touch_once(run, seen)
            else:
                run["loss_share_bbl"] = zero
        return

    if batch.get("loss_basis") == "LAST_RUN_ABSORBS":
        for run in runs:
            run["loss_share_bbl"] = zero
            touch_once(run, seen)
        runs[-1]["loss_share_bbl"] = total_loss
        touch_once(runs[-1], seen)
        return

    # PRO_RATA: independent rounding per run, then the remainder to a single run.
    for run in runs:
        share = calc.bbl(total_loss * Decimal(run.get("bbl_removed") or 0) / packaged)
        run["loss_share_bbl"] = share
        touch_once(run, seen)
    summed = sum((Decimal(run["loss_share_bbl"]) for run in runs), Decimal("0"))
    remainder = calc.bbl(total_loss - summed)
    if remainder != 0:
        winner = None
        for run in runs:
            if winner is None:
                winner = run
                continue
            removed = Decimal(run.get("bbl_removed") or 0)
            best = Decimal(winner.get("bbl_removed") or 0)
            if removed > best:
                winner = run
        winner["loss_share_bbl"] = calc.bbl(Decimal(winner["loss_share_bbl"]) + remainder)
        touch_once(winner, seen)


def close_batch(batch, seen):
    """CONDITIONING -> PACKAGED: free the vessel and allocate the packaging loss."""
    batch["state"] = "PACKAGED"
    packaged = derive.packaged_bbl(batch)
    if batch.get("actual_yield_bbl") is not None:
        batch["total_loss_bbl"] = calc.bbl(Decimal(batch["actual_yield_bbl"]) - packaged)
    tank = DB["tanks"].get(batch.get("tank_id"))
    if tank is not None and tank.get("status") == "OCCUPIED":
        tank["status"] = "DIRTY"
        tank["occupying_batch_id"] = None
        touch_once(tank, seen)
    allocate_packaging_loss(batch, seen)


# ---------------------------------------------------------------------------
# keg return reconciliation (hops 2 and 3)
# ---------------------------------------------------------------------------

def reconcile_run_after_return(run, seen):
    if run is None:
        return
    touch_once(run, seen)
    if run.get("reconciliation_state") != "OPEN":
        return
    if derive.kegs_outstanding_count(run) != 0:
        return
    if (run.get("kegs_filled_count") or 0) < 1:
        return
    run["reconciliation_state"] = "RECONCILED"
    total = Decimal("0")
    for keg in derive.rows("kegs"):
        if keg.get("packaging_run_id") != run["id"]:
            continue
        if keg.get("depletion_variance_oz") is None:
            continue
        total += Decimal(keg["depletion_variance_oz"])
    run["keg_shrinkage_oz"] = calc.oz(total)

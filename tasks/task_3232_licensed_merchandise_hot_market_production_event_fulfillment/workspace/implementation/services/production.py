"""Production workflow: design clearance, parallel-hold runs, layering,
press operations, the reopen rail and retirement cascades."""
from decimal import Decimal

import db
from services import ledger, pricing


# --- Printed-unit totals --------------------------------------------------

def refresh_printed_totals(run):
    """base_units_printed sums committed_qty over BASE layers;
    accessory_units_printed sums it over EMBROIDER, HEAT_PRESS and PENNANT.
    A layer still awaiting its first print is credited at the units it was
    authorised for, because the committed layer set is what the run holds."""
    base = 0
    accessory = 0
    for layer_id in run.get("layer_ids") or []:
        layer = db.store.print_layers.get(layer_id)
        if layer is None:
            continue
        if layer.get("layer_state") == "PENDING_PRINT":
            qty = int(layer.get("quantity", 0) or 0)
        else:
            qty = max(0, min(int(layer.get("quantity", 0) or 0),
                             int(layer.get("committed_qty", 0) or 0)))
        if layer.get("print_type") == "BASE":
            base += qty
        elif layer.get("print_type") in ("EMBROIDER", "HEAT_PRESS", "PENNANT"):
            accessory += qty
    run["base_units_printed"] = base
    run["accessory_units_printed"] = accessory
    return base, accessory


def printable_pool(run):
    """The run's printable pool: committed_inventory_cents / unit_cost_cents."""
    unit_cost = int(run.get("unit_cost_cents", 0) or 0)
    if unit_cost <= 0:
        return 0
    return int(Decimal(int(run.get("committed_inventory_cents", 0) or 0)) / Decimal(unit_cost))


def sellable_units(run):
    """Sellable units: base units plus accessory units, with pennant
    contributions counted only when pennants_included is true."""
    base = int(run.get("base_units_printed", 0) or 0)
    accessory = int(run.get("accessory_units_printed", 0) or 0)
    if run.get("pennants_included", True):
        return base + accessory
    pennant = 0
    for layer_id in run.get("layer_ids") or []:
        layer = db.store.print_layers.get(layer_id)
        if layer is not None and layer.get("print_type") == "PENNANT":
            pennant += int(layer.get("committed_qty", 0) or 0)
    return base + max(0, accessory - pennant)


def _actions_supported_total(run):
    total = 0
    for layer_id in run.get("layer_ids") or []:
        layer = db.store.print_layers.get(layer_id)
        if layer is not None:
            total += int(layer.get("quantity", 0) or 0)
    return total


def credited_units(run):
    """The units a sealed layer set credits to its run: a committed layer is
    credited at the units it was authorised for and a failed layer only at the
    units that survived, so an all-failed layer contributes nothing.  A pennant
    layer rides the BASE press capability (PRD 2.9), so it counts while the run
    holds a BASE layer and is barred only when the run excludes pennants."""
    pennant_barred = not run.get("pennants_included", True)
    total = 0
    for layer_id in run.get("layer_ids") or []:
        layer = db.store.print_layers.get(layer_id)
        if layer is None:
            continue
        if layer.get("print_type") == "PENNANT" and pennant_barred:
            continue
        planned = int(layer.get("quantity", 0) or 0)
        committed = int(layer.get("committed_qty", 0) or 0)
        if layer.get("layer_state") == "PENDING_PRINT":
            total += planned
        else:
            total += max(0, min(planned, committed))
    return total


def capitalized_inventory(run):
    """committed_inventory_cents for a run: the inventory value this run
    contributes, taken as the run's share of the parallel-hold allocation for
    the local case and widened by the supported print actions."""
    unit_cost = int(run.get("unit_cost_cents", 0) or 0)
    actions = _actions_supported_total(run)
    credited = credited_units(run)
    if run.get("trigger_type") == "STANDARD":
        return unit_cost * max(1, actions)
    return unit_cost * max(1, int(run.get("capacity_commitment_units", 0) or 0) + credited)


def hold_allocation(run):
    """parallel_hold_inventory_cents for this run, shared by the two outcomes of
    the same event."""
    unit_cost = int(run.get("unit_cost_cents", 0) or 0)
    if run.get("trigger_type") == "STANDARD":
        return unit_cost * max(1, int(run.get("expected_demand_qty", 0) or 0))
    return unit_cost * max(1, int(run.get("capacity_commitment_units", 0) or 0))


# --- Demand rescaling cascades -------------------------------------------

def open_orders(run):
    """The run's open demand: orders that have not reached a post-event rail."""
    return [o for o in db.created_order(list(db.store.fulfillment_orders.values()))
            if o.get("production_order_id") == run["id"]
            and o.get("status") not in ("DELIVERED", "RETURNED", "DISTRESSED")]


def _distress_by_cascade(order, run):
    """Cascade-set DISTRESSED: the already-picked units are counted as the
    destroyed quantity and the order is recorded against the collapse."""
    order["status"] = "DISTRESSED"
    order["distress_reason"] = "DEMAND_COLLAPSE"
    order["destroyed_qty"] = max(int(order.get("picked_qty", 0) or 0),
                                 int(order.get("destroyed_qty", 0) or 0))
    order["realized_wholesale_cents"] = 0
    db.touch(order)
    db.touch(run)


def close_order_at_event_window(order, run):
    """The event window has closed on an order that never left PLANNED: it is
    written down by Target B of demand_collapse_write_down, which is skipped
    whenever an equal-or-greater charge already stands."""
    charge = pricing.order_write_down(
        int(order.get("quantity", 0) or 0),
        int(run.get("unit_cost_cents", 0) or 0))
    if charge >= int(run.get("write_down_inventory_cents", 0) or 0):
        if charge > int(order.get("write_down_inventory_cents", 0) or 0):
            order["write_down_inventory_cents"] = charge
            db.touch(order)


def scale_open_orders(run, numerator, denominator):
    """Scale every open order's requested_wholesale_cents by numerator over
    denominator; any order whose recomputed total falls to zero or below is
    moved to DISTRESSED with reason DEMAND_COLLAPSE."""
    if not denominator:
        return
    factor = Decimal(int(numerator or 0)) / Decimal(int(denominator))
    for order in open_orders(run):
        current = Decimal(int(order.get("requested_wholesale_cents", 0) or 0))
        rescaled = pricing.to_cents(pricing.round_half_up(current * factor))
        if rescaled <= 0:
            order["requested_wholesale_cents"] = 0
            _distress_by_cascade(order, run)
        else:
            order["requested_wholesale_cents"] = rescaled
            db.touch(order)
            db.touch(run)


def cascade_layer_failure(run, layer, design, licensor):
    """PrintLayer PRINTED -> PRINT_FAILED (cascade hops 2 and 3): the run's
    printed totals are recomputed downward and the run's open demand is scaled by
    the layer's committed quantity over its authorized quantity."""
    refresh_printed_totals(run)
    scale_open_orders(run, int(layer.get("committed_qty", 0) or 0),
                      int(layer.get("quantity", 0) or 0))
    if design is not None:
        db.touch(design)
    db.touch(run)


def fail_printed_layers(run, design, licensor, forced_version=None,
                        scale_demand=True, force_printed=False):
    """Every printed layer of the run moves to PRINT_FAILED with committed_qty
    forced to 0, preserving the version the goods were printed at.  Returns the
    units the layers had printed, which the retirement books as lost goods.
    With `force_printed` even a layer that has only been authorised is moved, so
    a retirement takes the whole layer set out of the sellable pool."""
    failed_units = 0
    touched = False
    for layer_id in run.get("layer_ids") or []:
        layer = db.store.print_layers.get(layer_id)
        if layer is None:
            continue
        if layer.get("layer_state") == "PRINT_FAILED":
            continue
        if not force_printed and layer.get("layer_state") != "PRINTED":
            continue
        failed_units += int(layer.get("printed_qty", 0) or 0)
        layer["committed_qty"] = 0
        layer["layer_state"] = "PRINT_FAILED"
        layer["design_version_checked"] = (
            forced_version if forced_version is not None
            else (design.get("version") if design else layer.get("design_version_checked")))
        db.touch(layer)
        touched = True
    if touched:
        refresh_printed_totals(run)
        if scale_demand:
            scale_open_orders(run, 0, 1)
    return failed_units


# --- Design clearance cascade --------------------------------------------

def cascade_design_rejection(design, licensor):
    """REJECT cascade hop 1: every ProductionOrder using this design moves to
    RETIRED_DESTROYED with retire_reason ASSORTMENT_CHANGED, its printed layers
    move to PRINT_FAILED with committed_qty 0, and each run's open demand is
    rescaled or distressed."""
    for run in db.created_order(list(db.store.production_orders.values())):
        if run.get("design_id") != design["id"]:
            continue
        run["status"] = "RETIRED_DESTROYED"
        run["retire_reason"] = "ASSORTMENT_CHANGED"
        run["retired_at"] = db.stamp()
        run["hold_allocation_cents"] = 0
        db.touch(run)
        fail_printed_layers(run, design, licensor,
                            forced_version=run.get("retired_design_version"))
        run["write_down_inventory_cents"] = pricing.run_write_down(
            run.get("trigger_type"), int(run.get("destroyed_units", 0) or 0),
            int(run.get("unit_cost_cents", 0) or 0))


# --- Run commit / reopen / retire ----------------------------------------

def mark_committed(run, design, licensor):
    """PARALLEL_HOLD -> COMMITTED side effects."""
    run["status"] = "COMMITTED"
    run["committed_at"] = db.stamp()
    run["committed_inventory_cents"] = int(capitalized_inventory(run))
    run["hold_allocation_cents"] = 0
    run["write_down_inventory_cents"] = int(run.get("unit_cost_cents", 0) or 0)
    refresh_printed_totals(run)
    pricing.refresh_rush_delivery_points(run)
    db.touch(run)
    if design is not None:
        db.touch(design)
    if licensor is not None:
        db.touch(licensor)
        ledger.recompute_unsettled(licensor)


def reopen_run(run, design, licensor):
    """PRINTING -> COMMITTED (reopen inside the event window): the event window
    restarts from the new stamp, the run's write-down is zeroed, and the run
    becomes committable again because of the intervening revert."""
    run["status"] = "COMMITTED"
    run["committed_at"] = db.stamp()
    refresh_printed_totals(run)
    run["write_down_inventory_cents"] = 0
    db.touch(run)
    db.store.reopened_runs.add(run["id"])
    if design is not None:
        db.touch(design)


def can_accept_commit(run):
    """Only a run in PARALLEL_HOLD, or one that has been *reopened* from
    PRINTING back to COMMITTED (an intervening revert), may accept a commit."""
    if run.get("status") == "PARALLEL_HOLD":
        return True
    return run.get("status") == "COMMITTED" and run["id"] in db.store.reopened_runs


def _settle_orders_for_disposal(run, destroy_mode):
    """Every fulfillment order of the run is disposed of.  An order that has
    already reached a terminal post-event rail is left as it stands."""
    total = 0
    for order in db.created_order(list(db.store.fulfillment_orders.values())):
        if order.get("production_order_id") != run["id"]:
            continue
        if order.get("status") in ("DISTRESSED", "RETURNED", "DELIVERED"):
            continue
        qty = int(order.get("quantity", 0) or 0)
        if destroy_mode == "DONATE":
            order["donated_qty"] = qty
            order["destroyed_qty"] = 0
            order["requested_wholesale_cents"] = pricing.donate_weighted_total(qty)
        else:
            order["destroyed_qty"] = qty
            order["donated_qty"] = 0
            order["requested_wholesale_cents"] = pricing.destroy_weighted_total(qty)
        order["realized_wholesale_cents"] = 0
        order["status"] = "DISTRESSED"
        order["distress_reason"] = "DEMAND_COLLAPSE"
        total += qty
        db.touch(order)
    return total


def retire_run(run, retire_reason, destroy_mode, design, licensor, status):
    """Retire a run.  From COMMITTED or PRINTING the destroy_mode selects
    RETIRED_DONATED or RETIRED_DESTROYED; a retirement from PARALLEL_HOLD always
    lands in RETIRED_DESTROYED."""
    run["retire_reason"] = retire_reason
    run["retired_at"] = db.stamp()
    run["hold_allocation_cents"] = 0

    if status == "PARALLEL_HOLD":
        run["status"] = "RETIRED_DESTROYED"
        db.touch(run)
        # The lightest branch of the retirement cascade moves every print layer
        # to PRINT_FAILED with committed_qty forced to 0 (PRD 3.7) and then
        # scales the run's open demand down.
        fail_printed_layers(run, design, licensor, force_printed=True)
        refresh_printed_totals(run)
        return run

    donating = destroy_mode == "DONATE"
    run["status"] = "RETIRED_DONATED" if donating else "RETIRED_DESTROYED"
    lost_units = _settle_orders_for_disposal(run, destroy_mode if destroy_mode else "DESTROY")
    if donating:
        run["donated_units"] = int(run.get("donated_units", 0) or 0) + lost_units
    else:
        run["destroyed_units"] = int(run.get("destroyed_units", 0) or 0) + lost_units

    below = run["status"] == "RETIRED_DESTROYED" and status == "PRINTING"
    fail_printed_layers(
        run, design, licensor,
        forced_version=(run.get("retired_design_version") if below else None),
        scale_demand=False, force_printed=True)
    refresh_printed_totals(run)

    # An order that never left PLANNED is written down at the event window's
    # close, on Target B of demand_collapse_write_down.
    for pending in open_orders(run):
        if pending.get("status") == "PLANNED":
            close_order_at_event_window(pending, run)

    # Write-down: Target A is recomputed over the run's destroyed and donated
    # units, replacing whatever the run carried before (PRD 3.7).  The
    # skip-if-lesser rule of that section governs the order-level Target B, not
    # this recomputation.
    lost_total = int(run.get("destroyed_units", 0) or 0) + \
        int(run.get("donated_units", 0) or 0)
    run["write_down_inventory_cents"] = pricing.run_write_down(
        run.get("trigger_type"), lost_total,
        int(run.get("unit_cost_cents", 0) or 0))

    db.touch(run)
    if design is not None:
        db.touch(design)
    if licensor is not None:
        if donating:
            licensor["accrued_royalty_cents"] = ledger.q2(max(
                Decimal("0"),
                ledger.dec(licensor.get("accrued_royalty_cents", 0))
                - Decimal(pricing.order_write_down(lost_units,
                                                   int(run.get("unit_cost_cents", 0) or 0)))))
        db.touch(licensor)
        ledger.recompute_unsettled(licensor)
    return run
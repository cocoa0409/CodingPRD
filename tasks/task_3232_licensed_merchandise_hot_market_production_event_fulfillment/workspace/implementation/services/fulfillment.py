"""Fulfillment workflow: the shared inventory pool, pick, ship, deliver,
return, distress and the royalty recognition those rails drive."""
import db
from errors import (ERR_CAPACITY_EXCEEDED, ERR_INVALID_STATE,
                    ERR_INVENTORY_INSUFFICIENT, ERR_LOT_EXHAUSTED,
                    ERR_PICK_REMARK_REUSED, ERR_STALE_VERSION, fail)
from services import ledger, pricing, production


def is_venue_or_popup(order):
    """Rush commitments bind to venue and event-pop-up destinations."""
    destination = str(order.get("destination_code") or "")
    if destination.endswith("-VENUE") or "-VENUE" in destination:
        return True
    if destination.endswith("-POPUP") or "-POPUP" in destination:
        return True
    return order.get("channel") in ("VENUE_RETAIL", "EVENT_POPUP")


def pick_remarks_for(order_id):
    return db.store.pick_remarks.setdefault(order_id, [])


def recognize_run_orders(run):
    """Recompute the licensor's accrued royalty from the run's orders that have
    reached DELIVERED or RETURNED (distressed goods never accrue)."""
    licensor = db.store.licensors.get(run.get("licensor_id"))
    if licensor is None:
        return
    ledger.recompute_licensor_accrued(
        run.get("licensor_id"), run["id"],
        db.store.designs.get(run.get("design_id")),
        incurred_at=db.stamp())


# --- Pick -----------------------------------------------------------------

def pick(order, run, quantity, pick_remark, expected_version, design=None):
    """PLANNED -> PICKED.  The checks below are evaluated in the pinned
    precedence order of PRD 2.10; the request layer has already resolved the
    optimistic-concurrency guard on the referenced run."""
    # State eligibility.
    if order.get("status") not in ("PLANNED", "PICKED"):
        fail(ERR_INVALID_STATE, "fulfillment order is not in a state that permits a pick")

    # Aggregate capacity: picked units across all channels plus this pick must
    # not pass the run's printable pool.
    pool = production.printable_pool(run)
    after_pick = int(order.get("picked_qty", 0) or 0) + int(quantity)
    if aggregate_units(run, override=(order["id"], after_pick)) > pool:
        fail(ERR_CAPACITY_EXCEEDED,
             "picking %s units would take the run past its printable pool" % quantity)

    # The reference pool: the requested quantity of the run's earliest shipment
    # by committed_at, which is this order's own requested quantity.
    available_reference = _reference_pool(order)
    if int(quantity) > available_reference:
        fail(ERR_INVENTORY_INSUFFICIENT,
             "the pick exceeds the available units of the reference pool")

    # Lot exhaustion: every picked unit already shipped or distressed.
    if _lot_exhausted(run):
        fail(ERR_LOT_EXHAUSTED,
             "every picked unit of the run has already been shipped or distressed")

    # Remark uniqueness across every pick recorded on this order.
    if pick_remark is not None and pick_remark != "":
        if pick_remark in pick_remarks_for(order["id"]):
            fail(ERR_PICK_REMARK_REUSED,
                 "pick_remark %r has already been recorded on this order" % pick_remark)

    order["picked_qty"] = int(order.get("picked_qty", 0) or 0) + int(quantity)
    if order.get("pick_remark") in (None, ""):
        order["pick_remark"] = pick_remark
    order["status"] = "PICKED"
    db.touch(order)
    if pick_remark:
        pick_remarks_for(order["id"]).append(pick_remark)
    db.touch(run)
    if design is not None:
        db.touch(design)
    return order


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


def _reference_pool(order):
    """The reference pool: the units the channel's demand still holds, measured
    by the requested quantity of the run's earliest shipment ordered by its
    `committed_at` stamp (PRD 3.5).  Before any shipment exists for the order,
    that pool is the order's own requested quantity."""
    shipments = [s for s in db.store.shipments.values()
                 if s.get("fulfillment_order_id") == order["id"]]
    if shipments:
        shipments.sort(key=lambda s: (str(s.get("committed_at") or ""),
                                      db.creation_key(s)))
        return int(order.get("quantity", 0) or 0)
    return int(order.get("quantity", 0) or 0)


def _shipment_run(shipment):
    order = db.store.fulfillment_orders.get(shipment.get("fulfillment_order_id"))
    return order.get("production_order_id") if order else None


def _lot_exhausted(run):
    """Exhaustion is read off the run's own orders: when every unit the run has
    picked belongs to an order that has since been shipped or distressed, there
    is nothing left behind it to pick from (PRD 3.5).  Delivered and returned
    orders have left that pool through a different rail and do not exhaust it."""
    picked = 0
    moved = 0
    for order in db.store.fulfillment_orders.values():
        if order.get("production_order_id") != run["id"]:
            continue
        picked += int(order.get("picked_qty", 0) or 0)
        if order.get("status") in ("SHIPPED", "DISTRESSED"):
            moved += max(int(order.get("picked_qty", 0) or 0),
                         int(order.get("shipped_qty", 0) or 0))
    return picked > 0 and moved >= picked


# --- Ship -----------------------------------------------------------------

def ship(order, run, quantity, carrier, sla_hours):
    """PICKED -> SHIPPED; opens a Shipment in IN_TRANSIT."""
    if order.get("status") not in ("PICKED", "SHIPPED"):
        fail(ERR_INVALID_STATE, "fulfillment order is not in a state that permits a shipment")
    if run is None or run.get("status") not in ("COMMITTED", "PRINTING"):
        fail(ERR_INVALID_STATE, "the referenced production run is no longer a sellable pool")
    if int(quantity) > int(order.get("picked_qty", 0) or 0) - int(order.get("shipped_qty", 0) or 0):
        fail(ERR_CAPACITY_EXCEEDED, "cannot ship more units than were picked")
    if carrier == "RUSH_AIR" and not order.get("rush_flag"):
        fail("ERR_RUSH_COMMITMENT_BREACH",
             "RUSH_AIR was requested on an order without a rush commitment")
    if order.get("rush_flag") and is_venue_or_popup(order) and int(sla_hours) > 24:
        fail("ERR_RUSH_COMMITMENT_BREACH",
             "a rush venue delivery may not exceed 24 hours")

    order["shipped_qty"] = int(order.get("shipped_qty", 0) or 0) + int(quantity)
    shipment = {
        "fulfillment_order_id": order["id"],
        "carrier": carrier,
        "sla_hours": int(sla_hours),
        "shipment_state": "IN_TRANSIT",
        "committed_at": db.stamp(),
        "delivered_at": None,
    }
    db.init_common(shipment)
    db.store.shipments[shipment["id"]] = shipment

    if int(order["shipped_qty"]) >= int(order.get("picked_qty", 0) or 0):
        order["status"] = "SHIPPED"
    db.touch(order)
    db.touch(run)
    db.store.ledger_lines.setdefault(run["id"], []).append(
        {"line": "partial_shipment_ledger", "order_id": order["id"],
         "quantity": int(quantity), "at": db.stamp()})
    return shipment


# --- Deliver --------------------------------------------------------------

def deliver(order, run):
    """SHIPPED -> DELIVERED; every shipment moves to DELIVERED."""
    if order.get("status") != "SHIPPED":
        fail(ERR_INVALID_STATE, "only a shipped order may be delivered")
    order["status"] = "DELIVERED"
    order["realized_wholesale_cents"] = int(order.get("requested_wholesale_cents", 0) or 0)
    db.touch(order)
    for shipment in db.store.shipments.values():
        if shipment.get("fulfillment_order_id") == order["id"]:
            shipment["shipment_state"] = "DELIVERED"
            shipment["delivered_at"] = db.stamp()
            db.touch(shipment)
    if run is not None:
        licensor = db.store.licensors.get(run.get("licensor_id"))
        if licensor is not None:
            ledger.recompute_licensor_accrued(
                licensor["id"], run["id"], db.store.designs.get(run.get("design_id")),
                incurred_at=db.stamp())
            db.touch(licensor)
    return order


# --- Return ---------------------------------------------------------------

def return_order(order, run, return_quantity, destroy_mode):
    """PLANNED or SHIPPED -> RETURNED (terminal)."""
    status = order.get("status")
    if status not in ("PLANNED", "SHIPPED"):
        fail(ERR_INVALID_STATE, "fulfillment order is not in a state that permits a return")
    if int(return_quantity) > int(order.get("shipped_qty", 0) or 0):
        fail(ERR_CAPACITY_EXCEEDED, "return_quantity exceeds the shipped quantity")

    unit_cost = int(run.get("unit_cost_cents", 0) or 0) if run else 0
    order["returned_qty"] = int(order.get("returned_qty", 0) or 0) + int(return_quantity)
    order["realized_wholesale_cents"] = pricing.returned_recognition(
        order.get("requested_wholesale_cents", 0), return_quantity, unit_cost)
    order["status"] = "RETURNED"
    db.touch(order)

    if run is not None:
        lines = db.store.ledger_lines.setdefault(run["id"], [])
        if status == "SHIPPED":
            lines.append({"line": "units_damaged_destroyed", "order_id": order["id"],
                          "quantity": int(return_quantity), "at": db.stamp()})
        else:
            lines.append({"line": "units_destroyed_damaged", "order_id": order["id"],
                          "quantity": int(return_quantity), "at": db.stamp()})
        run["destroyed_units"] = int(run.get("destroyed_units", 0) or 0) + int(return_quantity)
        db.touch(run)
        licensor = db.store.licensors.get(run.get("licensor_id"))
        if licensor is not None:
            ledger.recompute_licensor_accrued(
                licensor["id"], run["id"], db.store.designs.get(run.get("design_id")),
                incurred_at=db.stamp())
            db.touch(licensor)
    return order


# --- Distress -------------------------------------------------------------

def distress(order, run, distress_reason, destroy_mode, donation_recipient_code):
    """PLANNED -> DISTRESSED (terminal); destroyed or donated goods never
    accrue a royalty."""
    if order.get("status") != "PLANNED":
        fail(ERR_INVALID_STATE, "fulfillment order is not in a state that permits distress")

    quantity = int(order.get("quantity", 0) or 0)
    if destroy_mode == "DONATE" or donation_recipient_code:
        order["donated_qty"] = quantity
        order["destroyed_qty"] = 0
        order["requested_wholesale_cents"] = pricing.donate_weighted_total(quantity)
        if donation_recipient_code:
            order["donation_recipient_code"] = donation_recipient_code
    else:
        order["destroyed_qty"] = quantity
        order["donated_qty"] = 0
        order["requested_wholesale_cents"] = pricing.destroy_weighted_total(quantity)
    order["realized_wholesale_cents"] = 0
    order["distress_reason"] = distress_reason
    order["status"] = "DISTRESSED"
    db.touch(order)
    if run is not None:
        db.touch(run)
        licensor = db.store.licensors.get(run.get("licensor_id"))
        if licensor is not None:
            ledger.recompute_licensor_accrued(
                licensor["id"], run["id"], db.store.designs.get(run.get("design_id")),
                incurred_at=db.stamp())
            db.touch(licensor)
    return order


def aggregate_units(run, override=None):
    """Picked, destroyed, donated and returned units of a run, counted across all
    channels.  `override` replaces one order's picked_qty for a prospective
    write."""
    total = 0
    for order in db.store.fulfillment_orders.values():
        if order.get("production_order_id") != run["id"]:
            continue
        picked = int(order.get("picked_qty", 0) or 0)
        if override is not None and override[0] == order["id"]:
            picked = int(override[1])
        total += (picked
                  + int(order.get("destroyed_qty", 0) or 0)
                  + int(order.get("donated_qty", 0) or 0)
                  + int(order.get("returned_qty", 0) or 0))
    return total


def aggregate_ceiling_breached(run, extra_units):
    return aggregate_units(run) + int(extra_units) > production.printable_pool(run)
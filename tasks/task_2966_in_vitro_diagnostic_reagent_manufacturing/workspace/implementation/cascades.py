"""Multi-hop system cascades (PRD 2.10).

Every hop is mandatory and immediate: by the time a response is returned every
downstream row has already been updated and had its version increased by 1.
"""

import calc
import recompute
from store import db, rows, touch

RECALL_QUARANTINE_REASON = "Recalled by complaint field action."
BRIDGING_QUARANTINE_REASON = "Bridging study failed for this critical material."


def _abort_stability_studies(lot):
    for study in rows(db.stability_studies):
        if study["reagent_lot_id"] != lot["id"]:
            continue
        if study["status"] in ("APPROVED", "IN_PROGRESS"):
            study["status"] = "ABORTED"
            touch(study)


def _quarantine_material_lot(material_lot, reason):
    material_lot["qualification_status"] = "QUARANTINED"
    material_lot["quarantine_reason"] = reason
    recompute.material_lot_quantities(material_lot)
    touch(material_lot)


def recall_lot(lot, field_action):
    """The recall cascade of PRD 3.8, fired by a CORRECTION or a REMOVAL."""
    # Hop 2 - the finished lot is recalled on both axes.
    lot["disposition_status"] = "RECALLED"
    lot["distribution_status"] = "BLOCKED"

    # Hop 3 - live reservations are quarantined.
    touched_orders = []
    for allocation in calc.allocation_rows(reagent_lot_id=lot["id"]):
        if allocation["status"] not in ("RESERVED", "SHIPPED"):
            continue
        allocation["status"] = "QUARANTINED"
        allocation["quarantine_reason"] = RECALL_QUARANTINE_REASON
        touch(allocation)
        order = db.distribution_orders.get(allocation["distribution_order_id"])
        if order is not None and order not in touched_orders:
            touched_orders.append(order)
    recompute.reagent_lot_units(lot)
    touch(lot)

    # Hop 3b - only a REMOVAL reaches back into raw material.
    if field_action == "REMOVAL":
        for component in calc.lot_components(lot["id"], "CONSUMED"):
            material_lot = db.material_lots.get(component["material_lot_id"])
            if material_lot is None or \
                    material_lot["qualification_status"] != "QUALIFIED":
                continue
            spec = db.material_specifications.get(
                material_lot["material_specification_id"])
            if spec is None or not spec["is_critical"]:
                continue
            _quarantine_material_lot(material_lot, RECALL_QUARANTINE_REASON)

    # Hop 4 - the parent orders re-roll their coverage.
    for order in touched_orders:
        was_allocated = order["status"] == "ALLOCATED"
        recompute.order_rollup(order)
        if was_allocated and order["allocated_units"] < order["requested_units"]:
            order["status"] = "PARTIALLY_ALLOCATED"
        touch(order)

    # Rider 1 - live stability studies on the recalled lot are aborted.
    _abort_stability_studies(lot)

    # Rider 2 - a REMOVAL of the only RELEASED lot withdraws the product.
    if field_action == "REMOVAL":
        product = db.product_specifications.get(lot["product_specification_id"])
        if product is not None and product["clearance_status"] == "CLEARED":
            others = [l for l in rows(db.reagent_lots)
                      if l["product_specification_id"] == product["id"]
                      and l["id"] != lot["id"]
                      and l["disposition_status"] == "RELEASED"]
            if not others:
                product["clearance_status"] = "WITHDRAWN"
                touch(product)


def bridging_failure(study):
    """The three-hop cascade of PRD 3.7 behind a rejected bridge."""
    # Hop 2 - the changed critical raw material lot is quarantined.
    material_lot = db.material_lots.get(study["changed_material_lot_id"])
    if material_lot is not None and \
            material_lot["qualification_status"] == "QUALIFIED":
        _quarantine_material_lot(material_lot, BRIDGING_QUARANTINE_REASON)

    # Hop 2b - a candidate that is on the market is blocked.
    candidate = db.reagent_lots.get(study["candidate_lot_id"])
    if candidate is not None and candidate["distribution_status"] == "AVAILABLE":
        candidate["distribution_status"] = "BLOCKED"
        touch(candidate)

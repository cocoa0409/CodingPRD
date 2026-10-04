"""Cup settlement and void, including the exit-tunnel checklist gate."""

from db import SHRINKAGE_ALERT_BPS, db
from errors import fail
from services.core import recompute_store, touch
from services.pricing import cup_capacity_breach, price_order
from services.wall import mutate_bin, recompute_shrinkage


def linked_inspection(order):
    """The inspection that gated, or would gate, this checkout."""
    for inspection in db().exit_inspections.values():
        if inspection["fusion_order_id"] == order["id"]:
            return inspection
    return None


def checkout(order, member, store, payload):
    """The nine-rung ladder as PRD §2.4 orders it for this endpoint."""
    variant = payload.get("pricing_variant") or "POST_DISCOUNT"
    launch_id = payload.get("exclusive_launch_id")

    # rung 5 -- sibling readiness: the exit tunnel and the per-piece element.
    inspection = linked_inspection(order)
    if store["checklist_required"] and inspection is not None:
        if inspection["stage"] != "COMPLETED":
            fail("ERR_INSPECTION_REQUIRED",
                 "The exit inspection linked to this cup has not been completed.")

    if order["pricing_model"] == "PER_PIECE":
        element = db().elements.get(order.get("pieced_element_id") or "")
        if element is None or element["status"] not in ("ACTIVE", "CATALOG"):
            fail("ERR_ELEMENT_NOT_SOURCED",
                 "The per-piece element is not currently sourced on the wall.")

    if launch_id is not None:
        from services.core import get_launch
        get_launch(launch_id)

    # rung 7 -- personal ceilings (none apply to a plain settlement).
    # rung 8 -- fiscal position: the priced amount and the shrink position must admit it.
    breach = cup_capacity_breach(order, store)
    if breach == "RESTRICTED":
        fail("ERR_STORE_RESTRICTED",
             "A restricted store refuses a cup whose weighed mass exceeds the "
             "mass capacity of its cup size.")
    if breach == "CAPACITY":
        fail("ERR_CUP_CAPACITY_EXCEEDED",
             "The weighed mass exceeds the capacity of the declared cup size.")
    if store["shrinkage_basis_points"] >= SHRINKAGE_ALERT_BPS:
        fail("ERR_SHRINKAGE_ALERT",
             "The store's lifetime shrink position blocks further settlement.")

    # rung 9 -- store posture.
    if store["stage"] == "FROZEN":
        fail("ERR_STORE_FROZEN", "A frozen store admits no cup settlement.")

    priced = price_order(order, store, member, variant, launch_id is not None)
    order.update(priced)
    order["exclusive_launch_id"] = launch_id
    order["status"] = "SETTLED"
    order["exit_inspection_id"] = inspection["id"] if inspection is not None else None
    touch(order)
    recompute_shrinkage(store)
    touch(store)
    return order


def void(order, store, payload):
    """Voiding returns the cup's mass to the wall and waives a scheduled inspection."""
    if order["status"] == "PENDING":
        if any(i["stage"] == "COMPLETED" for i in db().exit_inspections.values()
               if i["fusion_order_id"] == order["id"]):
            fail("ERR_INVALID_STATE",
                 "A pending cup with a completed inspection cannot be voided.")
    elif order["status"] != "SETTLED":
        fail("ERR_INVALID_STATE",
             "Only a pending or settled cup may be voided.")

    for allocation in [a for a in db().fusion_allocations.values()
                       if a["fusion_order_id"] == order["id"]]:
        bin_record = db().wall_bins.get(allocation["wall_bin_id"])
        if bin_record is not None:
            mutate_bin(bin_record, allocation["allocation_grams"])

    order["status"] = "VOID"
    order["_voided"] = True
    touch(order)

    for inspection in db().exit_inspections.values():
        if inspection["fusion_order_id"] == order["id"] and inspection["stage"] == "SCHEDULED":
            inspection["stage"] = "WAIVED"
            touch(inspection)

    recompute_store(store)
    recompute_shrinkage(store)
    touch(store)
    return order
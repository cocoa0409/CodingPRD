"""Multi-hop cascades: the short-pick cascade (PRD 3.6) and order
cancellation with its waitlist cascade (PRD 3.9)."""

import db as store
from db import db
from services import derive, money, selectors


# --------------------------------------------------------------------------
# Substitution proposals
# --------------------------------------------------------------------------
def create_proposal(line, substitute_sku, supersedes_proposal_id=None):
    highest = 0
    for proposal in derive.line_proposals(line):
        if proposal["round_no"] > highest:
            highest = proposal["round_no"]
    entity = store.new_entity()
    entity.update({
        "order_line_id": line["id"],
        "substitute_sku_id": substitute_sku["id"],
        "supersedes_proposal_id": supersedes_proposal_id,
        "round_no": highest + 1,
        "proposed_price_delta_cents": (
            substitute_sku["unit_price_cents"] * line["ordered_qty"]
            - line["provisional_line_price_cents"]
        ),
        "status": "DRAFT",
        "expires_at": None,
    })
    db.proposals[entity["id"]] = entity
    store.bump(line)  # PRD 2.4: creating a proposal bumps the parent line
    return entity


# --------------------------------------------------------------------------
# The four-hop short-pick cascade (PRD 3.6)
# --------------------------------------------------------------------------
def short_pick_cascade(task, line, sku):
    # Hop one -- the line goes short and the picked units leave the grid.
    line["line_status"] = "SHORT"
    line["substitution_resolution"] = "PENDING"
    line["picked_units"] = task["picked_units"]
    line["picked_weight_grams"] = task["actual_weight_grams"]
    sku["physical_units"] = sku["physical_units"] - task["picked_units"]
    derive.recompute_all_sku_ledgers()

    # Hop two -- the substitute selector runs from the originally ordered SKU.
    ordered_sku = db.skus[line["sku_id"]]
    candidate = selectors.select_substitute(line, ordered_sku)
    if candidate is not None:
        create_proposal(line, candidate)

    # Hop three -- order flags and the charge waterfall.
    order = db.orders[line["order_id"]]
    derive.recompute_order_flags(order)
    money.run_waterfall(order)
    store.bump(order)
    # Hop four -- the wave posture is recomputed by reconcile().


# --------------------------------------------------------------------------
# Order cancellation (PRD 3.9)
# --------------------------------------------------------------------------
def cancel_order(order):
    previous_fulfillment = order["fulfillment_status"]
    previous_billing = order["billing_status"]

    # Lines.
    for line in derive.order_lines(order):
        if line["line_status"] in ("PENDING", "SHORT"):
            line["line_status"] = "CANCELLED"

    # Retrieval work in flight.
    for task in derive.order_tasks(order):
        if task["status"] in ("QUEUED", "RETRIEVING"):
            task["status"] = "CANCELLED"

    # Substitution decisions in flight.
    for proposal in derive.order_proposals(order):
        if proposal["status"] in ("DRAFT", "PROPOSED"):
            proposal["status"] = "EXPIRED"

    # Hop 1 -- bookings released.
    freed_slots = []
    touched_slots = []
    for booking in derive.order_bookings(order):
        if booking["status"] in ("HELD", "CONFIRMED", "WAITLISTED"):
            occupied = booking["status"] in ("HELD", "CONFIRMED")
            booking["status"] = "RELEASED"
            slot = db.slots[booking["delivery_slot_id"]]
            if slot not in touched_slots:
                touched_slots.append(slot)
            if occupied and slot not in freed_slots:
                freed_slots.append(slot)

    # Wave detachment.
    if previous_fulfillment == "WAVED":
        order["wave_id"] = None

    order["fulfillment_status"] = "CANCELLED"
    money.run_waterfall(order, apply_billing=False)
    if previous_billing in ("AUTHORIZED", "ADJUSTED"):
        order["billing_status"] = "REVERSED"
    store.bump(order)

    # Hop 2 -- ledger and surge; hop 3 and 4 -- one promotion at most.
    for slot in touched_slots:
        derive.recompute_slot_ledger(slot)
    for slot in freed_slots:
        selectors.promote_one_waitlisted(slot)
    for slot in touched_slots:
        derive.recompute_slot_ledger(slot)
        money.recompute_surge(slot)
    derive.recompute_all_sku_ledgers()

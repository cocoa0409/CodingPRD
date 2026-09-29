"""Ledger posting and every bubble-up / compensating cascade (PRD 2.10, 2.11)."""

import calc
from store import base_row, store, touch

REQUIRED_TASK_TYPES = ("REGISTRATION", "LICENSING", "PREPARATION")
RESOLVED_TASK_STATUSES = ("COMPLETED", "WAIVED")

MILESTONE_FIELD = {
    "REGISTRATION": "registered_at",
    "LICENSING": "licensed_at",
    "PREPARATION": "prep_completed_at",
}


def post_ledger(vehicle_id, entry_type, amount_cents, source_entity_type,
                source_entity_id, memo):
    row = base_row(versioned=False)
    row.update({
        "vehicle_id": vehicle_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "source_entity_type": source_entity_type,
        "source_entity_id": source_entity_id,
        "posted_at": store.now_iso(),
        "memo": memo,
    })
    store.ledger[row["id"]] = row
    return row


# -- in-fleeting chain (four hops) -------------------------------------


def stamp_milestone(vehicle, task_type):
    field = MILESTONE_FIELD[task_type]
    vehicle[field] = store.now_iso()
    # The milestone stamp itself is not one of the version-incrementing
    # transitions enumerated in PRD 3.4; only the promotion increments.
    touch(vehicle, bump=False)


def evaluate_promotion(vehicle):
    """Hop 1 -> 2: promote IN_FLEETING -> IN_SERVICE when all three types are resolved."""
    if vehicle["fleet_status"] != "IN_FLEETING":
        return
    tasks = calc.tasks_of_vehicle(vehicle["id"])
    for task_type in REQUIRED_TASK_TYPES:
        if not any(
            t["task_type"] == task_type and t["status"] in RESOLVED_TASK_STATUSES
            for t in tasks
        ):
            return
    now = store.now_iso()
    vehicle["fleet_status"] = "IN_SERVICE"
    vehicle["first_rent_ready_at"] = now
    if not vehicle.get("in_service_at"):
        vehicle["in_service_at"] = now
    touch(vehicle)
    allocation = store.allocations.get(vehicle["allocation_id"])
    if allocation is not None:
        recompute_allocation(allocation)


def recompute_allocation(allocation):
    """Hop 2 -> 3: recompute in_fleeted_count and advance the compound status."""
    if allocation["status"] == "CANCELLED":
        return
    in_fleeted = calc.allocation_in_fleeted_count(allocation)
    unit_count = allocation["unit_count"]
    reached_infleeted = False
    if allocation["status"] in ("ORDERED", "PARTIALLY_INFLEETED"):
        if in_fleeted >= unit_count:
            allocation["status"] = "INFLEETED"
            reached_infleeted = True
        elif in_fleeted > 0 and allocation["status"] == "ORDERED":
            allocation["status"] = "PARTIALLY_INFLEETED"
    touch(allocation)
    if reached_infleeted:
        plan = store.plans.get(allocation["plan_id"])
        if plan is not None:
            evaluate_plan_closure(plan)


def evaluate_plan_closure(plan):
    """Hop 3 -> 4: close a LOCKED plan whose in-fleeted count met the plan size."""
    if plan["status"] != "LOCKED":
        return
    if calc.plan_in_fleeted_unit_count(plan) >= plan["planned_unit_count"]:
        plan["status"] = "CLOSED"
        touch(plan)


# -- damage condition cascade -------------------------------------------


def damage_condition_cascade(vehicle):
    """DAMAGE_REPORTED -> SOUND once no damage event for the unit is still open."""
    still_open = any(
        d["status"] in calc.OPEN_DAMAGE_STATUSES
        for d in calc.damage_events_of_vehicle(vehicle["id"])
    )
    if still_open:
        return
    if vehicle["condition_status"] != "DAMAGE_REPORTED":
        return
    vehicle["condition_status"] = "SOUND"
    touch(vehicle)


# -- total-loss chain (three hops) -------------------------------------


def total_loss_cascade(vehicle):
    """Hop 1 -> 2 -> 3: retire the unit and clean up its downstream paperwork."""
    origin = vehicle["fleet_status"]
    vehicle["fleet_status"] = "TOTAL_LOSS"
    vehicle["condition_status"] = "TOTALED"
    touch(vehicle)

    if origin == "IN_FLEETING":
        for task in calc.tasks_of_vehicle(vehicle["id"]):
            if task["status"] == "PENDING":
                task["status"] = "WAIVED"
                task["completed_at"] = store.now_iso()
                touch(task)
        return

    if origin not in ("IN_SERVICE", "IN_TRANSIT", "HELD_FOR_SALE"):
        return

    for order in calc.orders_of_vehicle(vehicle["id"]):
        if order["status"] in calc.NON_TERMINAL_ORDER_STATUSES:
            order["status"] = "CANCELLED"
            touch(order)
    for consignment in calc.consignments_of_vehicle(vehicle["id"]):
        if consignment["status"] in calc.NON_TERMINAL_CONSIGNMENT_STATUSES:
            # Deliberately posts no RECONDITION_REVERSAL: money sunk into a
            # destroyed car stays in the basis the total loss is measured against.
            consignment["status"] = "WITHDRAWN"
            touch(consignment)

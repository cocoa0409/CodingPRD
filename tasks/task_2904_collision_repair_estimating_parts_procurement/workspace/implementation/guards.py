"""Shared ladder rungs 10-13 helpers and the stall cascade (PRD 2.5, 3.8)."""
import calc
import db
from db import store
from errors import raise_error

STAGES = ("INTAKE", "TEARDOWN", "BLUEPRINTED", "ESTIMATE_LOCKED", "PARTS_STAGED",
          "REPAIR", "REFINISH_CALIBRATION", "READY_FOR_QC", "QC_FAILED", "DELIVERED",
          "TOTAL_LOSS")
TERMINAL_STAGES = ("DELIVERED", "TOTAL_LOSS")


def find_order(order_id):
    """Rung 10, leftmost path identifier."""
    order = store.repair_orders.get(order_id)
    if order is None:
        raise_error("ERR_REPAIR_ORDER_NOT_FOUND")
    return order


def not_terminal(order):
    """Rung 12."""
    if order["stage"] in TERMINAL_STAGES:
        raise_error("ERR_ORDER_TERMINAL")


def stage_in(order, states):
    """Rung 13, first clause."""
    if order["stage"] not in states:
        raise_error("ERR_STAGE_PRECONDITION")


def parts_state_in(parts_line, states):
    """Rung 13, third clause."""
    if parts_line["procurement_status"] not in states:
        raise_error("ERR_PARTS_LINE_STATE")


def posture_open(order):
    """Rung 13, fourth clause."""
    if order["authorization_posture"] != "OPEN":
        raise_error("ERR_AUTHORIZATION_POSTURE_BLOCKED")


def release_assignments(order, statuses, new_status, bumper, stage=None):
    """Retire stall bookings, releasing exactly their occupied minutes."""
    touched_stalls = []
    for assignment in calc.order_assignments(order["id"]):
        if assignment["status"] not in statuses:
            continue
        if stage is not None and assignment["stage"] != stage:
            continue
        assignment["status"] = new_status
        bumper.add(assignment)
        stall = store.stalls.get(assignment["stall_id"])
        if stall is not None and stall not in touched_stalls:
            touched_stalls.append(stall)
    for stall in touched_stalls:
        calc.stall_rollup(stall, bumper)


def activate_assignments(order, stage, bumper):
    """Promote every SCHEDULED booking for the entered stage; booked minutes unchanged."""
    for assignment in calc.order_assignments(order["id"]):
        if assignment["status"] == "SCHEDULED" and assignment["stage"] == stage:
            assignment["status"] = "ACTIVE"
            bumper.add(assignment)


def latest_inspection(order):
    rows = calc.order_qc_inspections(order["id"])
    if not rows:
        return None
    return sorted(rows, key=lambda r: (r["sequence_number"], r["_seq"]))[-1]


def close_delay_events(parts_line, order, bumper):
    """Receipt of a correct part closes every open delay on the line (PRD 3.6)."""
    closed = 0
    for event in store.parts_delay_events.values():
        if event.get("parts_line_id") != parts_line["id"]:
            continue
        if event.get("closed_at") is not None:
            continue
        event["closed_at"] = db.now_iso()
        event["delay_minutes"] = db.floor_minutes(db.parse_iso(event["opened_at"]),
                                                  db.parse_iso(event["closed_at"]))
        closed += 1
    calc.recount_open_delays(order)
    return closed


def open_delay_event(parts_line, order, reason):
    event = db.base_row(mutable=False)
    event.update({
        "repair_order_id": order["id"],
        "parts_line_id": parts_line["id"],
        "reason": reason,
        "opened_at": db.now_iso(),
        "closed_at": None,
        "delay_minutes": None,
    })
    store.parts_delay_events[event["id"]] = event
    calc.recount_open_delays(order)
    return event


def has_open_delay(parts_line):
    for event in store.parts_delay_events.values():
        if event.get("parts_line_id") == parts_line["id"] and event.get("closed_at") is None:
            return True
    return False

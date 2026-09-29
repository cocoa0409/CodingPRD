"""Multi-record cascades (PRD 2.9): fan-out sets are processed in created_at
ascending order so the observable end state is deterministic."""
import db
import derive


def release_pending_stops(dispatch):
    """Release every PENDING stop and revert its order back to READY."""
    pending = [
        s
        for s in db.stops.values()
        if s["dispatch_id"] == dispatch["id"] and s["status"] == "PENDING"
    ]
    for stop in db.ordered(pending):
        stop["status"] = "RELEASED"
        db.touch(stop)
        order = db.orders.get(stop["order_id"])
        if order is not None and order["fulfillment_status"] in ("ASSIGNED", "EN_ROUTE"):
            order["fulfillment_status"] = "READY"
            db.touch(order)


def void_provisional_lines(dispatch):
    lines = [
        line
        for line in db.lines.values()
        if line["dispatch_id"] == dispatch["id"] and line["line_type"] == "PROVISIONAL_STOP"
    ]
    for line in db.ordered(lines):
        line["status"] = "VOIDED"
        db.touch(line)


def recall_dispatch(dispatch, reason):
    """Abort one route: it pays nothing and reverses every commitment."""
    dispatch["status"] = "RECALLED"
    dispatch["recalled_reason"] = reason
    db.touch(dispatch)
    release_pending_stops(dispatch)
    void_provisional_lines(dispatch)


def disqualify_driver(driver, reason):
    """Drive the driver to DISQUALIFIED and unwind everything in flight.

    The caller is responsible for the driver's single version increment.
    """
    driver["qualification_status"] = "DISQUALIFIED"
    driver["disqualified_reason"] = reason
    affected = [
        d
        for d in db.dispatches.values()
        if d["driver_id"] == driver["id"] and d["status"] in ("STACKED", "LOCKED", "EN_ROUTE")
    ]
    for dispatch in db.ordered(affected):
        recall_dispatch(dispatch, "DRIVER_DISQUALIFIED")

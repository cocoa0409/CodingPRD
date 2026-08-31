"""Cross-entity cascades and lazy re-evaluations."""
from core import db, dec, now, touch
import calc


# --------------------------------------------------------------------------
# Gauge lazy calibration re-evaluation (never a client mutation: no version bump)
# --------------------------------------------------------------------------
def refresh_gauge(gauge):
    if gauge["status"] == "IN_SERVICE" and gauge["_cal_due_dt"] is not None:
        if now() >= gauge["_cal_due_dt"]:
            gauge["status"] = "CALIBRATION_DUE"
    return gauge


def gauge_status_from_study(grr_pct, calibration_due_dt):
    if dec(grr_pct) > calc.GRR_RETIRE_PCT:
        return "RETIRED"
    if dec(grr_pct) > calc.GRR_MAX_PCT:
        return "GRR_FAILED"
    if calibration_due_dt is not None and calibration_due_dt > now():
        return "IN_SERVICE"
    return "CALIBRATION_DUE"


# --------------------------------------------------------------------------
# Routing-step cascades
# --------------------------------------------------------------------------
def steps_of(work_order_id):
    rows = [s for s in db.routing_steps.values() if s["work_order_id"] == work_order_id]
    rows.sort(key=lambda s: (s["created_at"], s["_seq"]))
    return rows


def block_steps(work_order_id, from_statuses, reason):
    for step in steps_of(work_order_id):
        if step["status"] in from_statuses:
            step["status"] = "BLOCKED"
            step["blocked_reason"] = reason
            touch(step)


def unblock_steps(work_order_id):
    for step in steps_of(work_order_id):
        if step["status"] == "BLOCKED":
            step["status"] = "PENDING"
            step["blocked_reason"] = None
            touch(step)


# --------------------------------------------------------------------------
# Tool-hold chain: hop 2 (machine DOWN) -> hop 3 (work order INTERRUPTED)
# -> hop 4 (PENDING routing steps BLOCKED)
# --------------------------------------------------------------------------
def machine_down_chain(machine):
    if machine["status"] not in ("RUNNING", "AVAILABLE"):
        return
    was_running = machine["status"] == "RUNNING"
    machine["status"] = "DOWN"
    touch(machine)
    if not was_running:
        machine["current_work_order_id"] = None
        return
    running = None
    for work_order in db.work_orders.values():
        if work_order["machine_id"] == machine["id"] and work_order["machining_status"] == "RUNNING":
            running = work_order
            break
    machine["current_work_order_id"] = None
    if running is None:
        return
    running["machining_status"] = "INTERRUPTED"
    touch(running)
    block_steps(running["id"], ("PENDING",), "UPSTREAM_MACHINE_DOWN")


def held_stations(machine_id):
    return [t for t in db.tool_assignments.values()
            if t["machine_id"] == machine_id and t["status"] in ("OFFSET_HOLD", "LIFE_EXPIRED")]


# --------------------------------------------------------------------------
# Blanket-order helpers
# --------------------------------------------------------------------------
def releases_of(blanket_po_id):
    rows = [r for r in db.kanban_releases.values() if r["blanket_po_id"] == blanket_po_id]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def work_orders_of_release(release_id):
    rows = [w for w in db.work_orders.values() if w["release_id"] == release_id]
    rows.sort(key=lambda w: (w["created_at"], w["_seq"]))
    return rows


def po_expire_if_lapsed(blanket_po):
    """Lazy ACTIVE -> EXPIRED re-evaluation; the caller rejects the request."""
    if blanket_po["status"] != "ACTIVE":
        return False
    if blanket_po["_expires_dt"] is not None and now() >= blanket_po["_expires_dt"]:
        blanket_po["status"] = "EXPIRED"
        touch(blanket_po)
        return True
    return False


# --------------------------------------------------------------------------
# Fulfilment chain hops 2-4
# --------------------------------------------------------------------------
def po_credit_fulfilment(blanket_po, release_qty, qty_good):
    blanket_po["open_released_qty"] = int(blanket_po["open_released_qty"]) - int(release_qty)
    blanket_po["fulfilled_qty"] = int(blanket_po["fulfilled_qty"]) + int(qty_good)
    blanket_po["remaining_qty"] = int(blanket_po["remaining_qty"]) + (int(release_qty) - int(qty_good))
    touch(blanket_po)
    # hop 3 — exhaustion, and hop 4 — quote consumption
    if blanket_po["status"] == "ACTIVE" and blanket_po["remaining_qty"] == 0 \
            and blanket_po["open_released_qty"] == 0:
        blanket_po["status"] = "EXHAUSTED"
        quote = db.quotes.get(blanket_po["quote_id"])
        if quote is not None and quote["status"] == "ACCEPTED":
            quote["status"] = "CONSUMED"
            touch(quote)


def po_return_quantity(blanket_po, release_qty):
    blanket_po["open_released_qty"] = int(blanket_po["open_released_qty"]) - int(release_qty)
    blanket_po["remaining_qty"] = int(blanket_po["remaining_qty"]) + int(release_qty)
    touch(blanket_po)

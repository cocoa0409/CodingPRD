"""Shared state-machine helpers and cascades."""

from clock import CLOCK
from db import DB
from errors import ApiError
from services import calc, holds


# ---------------------------------------------------------------- patron count

def bump_violations(patron, delta):
    """Apply an explicit violation delta, floored at zero."""
    if patron is None:
        return
    current = int(patron.get("draw_violation_count") or 0)
    updated = max(0, current + delta)
    if updated != current:
        patron["draw_violation_count"] = updated
        DB.touch("patron", patron)


# ------------------------------------------------------- allocation lifecycle

def allocation_owner_ids(performance_id, ticket_types):
    return [
        a["id"]
        for a in DB.all("allocation")
        if a["performance_id"] == performance_id and a["ticket_type"] in ticket_types
    ]


def set_allocation_status(allocation, status):
    allocation["status"] = status
    return DB.touch("allocation", allocation)


def cascade_allocation_exhausted(allocation, performance):
    """Waiting entries lose, the queue clears and future holds are freed."""
    for entry in DB.all("draw_entry"):
        if entry["allocation_id"] == allocation["id"] and entry["status"] == "WAITLISTED":
            entry["status"] = "LOSER"
            DB.touch("draw_entry", entry)
    abandon_queue(performance["id"], ("WAITING",))
    holds.release_allocation_holds_for_labels(
        performance["id"], holds.platform_labels(performance["id"]), within_future_only=True
    )


def maybe_allocation_exhausted(allocation, performance):
    """RELEASED -> EXHAUSTED once the day's sold count reaches the release ceiling."""
    if allocation["status"] != "RELEASED":
        return False
    cap = int(allocation.get("daily_release_cap") or 0)
    if cap <= 0:
        return False
    if int(allocation.get("quantity_sold_today") or 0) >= cap:
        cascade_allocation_exhausted(allocation, performance)
        set_allocation_status(allocation, "EXHAUSTED")
        return True
    return False


def maybe_allocation_reopened(allocation):
    """EXHAUSTED -> RELEASED when returned seats reopen the epoch."""
    if allocation["status"] != "EXHAUSTED":
        return False
    cap = int(allocation.get("daily_release_cap") or 0)
    if int(allocation.get("quantity_sold_today") or 0) < cap:
        set_allocation_status(allocation, "RELEASED")
        return True
    return False


def receiver_violation(actor, qa_checked_by):
    """Any second actor counts as a second operator; self-dealing is refused."""
    if qa_checked_by and str(actor) == str(qa_checked_by):
        raise ApiError("ERR_SOD_VIOLATION")


# --------------------------------------------------------------- queue cascade

def abandon_queue(performance_id, statuses):
    touched = []
    for position in DB.all("queue_position"):
        if position["performance_id"] != performance_id:
            continue
        if position["status"] not in statuses:
            continue
        position["status"] = "ABANDONED"
        DB.touch("queue_position", position)
        touched.append(position)
    return touched


# ---------------------------------------------------------- draw entry cascade

def cancel_draw_entries(performance_id, statuses, allocation_ids=None):
    """Cancel entries and draw each affected patron's count down by one."""
    touched = []
    for entry in DB.all("draw_entry"):
        if entry["performance_id"] != performance_id:
            continue
        if allocation_ids is not None and entry["allocation_id"] not in allocation_ids:
            continue
        if entry["status"] not in statuses:
            continue
        entry["status"] = "CANCELLED"
        DB.touch("draw_entry", entry)
        bump_violations(DB.get("patron", entry["patron_id"]), -1)
        touched.append(entry)
    return touched


def cancel_entries_for_patron(patron_id):
    touched = []
    for entry in DB.all("draw_entry"):
        if entry["patron_id"] != patron_id:
            continue
        if entry["status"] not in ("ENTERED", "WINNER", "WAITLISTED"):
            continue
        entry["status"] = "CANCELLED"
        DB.touch("draw_entry", entry)
        bump_violations(DB.get("patron", patron_id), -1)
        touched.append(entry)
    return touched


# ------------------------------------------------------------- hold cascades

def orphan_allocation_holds(performance_id):
    touched = []
    for hold in DB.all("seat_hold"):
        if hold["performance_id"] != performance_id:
            continue
        if hold["hold_kind"] != "ALLOCATION":
            continue
        if hold["status"] != "HELD":
            continue
        hold["status"] = "ORPHANED"
        DB.touch("seat_hold", hold)
        touched.append(hold)
    return touched


# ------------------------------------------------------------- desk lifecycle

def saturate_desk_if_full(desk):
    if desk["status"] == "OPEN" and int(desk["handoffs_today"]) >= int(desk["daily_capacity"]):
        desk["status"] = "SATURATED"
        DB.touch("desk", desk)
        return True
    return False


def reset_desks():
    count = 0
    for desk in DB.all("desk"):
        count += 1
        if desk["status"] == "SATURATED":
            desk["status"] = "OPEN"
            desk["handoffs_today"] = 0
            DB.touch("desk", desk)
        elif int(desk.get("handoffs_today") or 0) != 0:
            desk["handoffs_today"] = 0
            DB.touch("desk", desk, bump=False)
    return count


# ------------------------------------------------------- handoff dispatch

def dispatch_handoff(purchase, performance):
    """Route a purchase to a desk when the market requires an in-person handoff."""
    market = next(
        (m for m in DB.all("market") if m["market_code"] == performance["market_code"]), None
    )
    model = market["handoff_model"] if market else "MOBILE_PUSH"
    if model == "MOBILE_PUSH":
        purchase["handoff_status"] = "NOT_REQUIRED"
        purchase["handoff_token"] = None
        purchase["assign_by"] = None
        return
    candidates = calc.handoff_candidates(performance)
    purchase["handoff_status"] = "PENDING_CONCIERGE"
    purchase["assign_by"] = candidates[0]["desk_code"] if candidates else None
    issue_handoff_token(purchase)


def issue_handoff_token(purchase):
    """A server-issued secret; re-issued minted afresh by every dispatch."""
    import uuid

    purchase["handoff_token"] = "HO-" + uuid.uuid4().hex.upper()[:20]
    return purchase["handoff_token"]
"""Shared business services: ownership, the cost ledger, and every system-driven
cascade described in PRD 2.9, 3.5, 3.7, 3.8 and 3.9."""
from datetime import timedelta

import calc
import db as D
from db import base_entity, db, touch, whole_minutes
from errors import fail


# ---------------------------------------------------------------------------
# Rung 6: ownership for the entity-backed roles.
# ---------------------------------------------------------------------------
ENTITY_BACKED_ROLES = ("Sitter", "RemoteObserver")


def caller_staff(caller):
    """Resolve an entity-backed caller's Staff row. Opaque roles return None."""
    if caller.role not in ENTITY_BACKED_ROLES:
        return None
    staff = db.staff.get(caller.user_id)
    if staff is None:
        fail("ERR_STAFF_NOT_FOUND", "X-User-ID names no Staff row.")
    return staff


def require_owner(caller, owning_staff_id):
    """Compare an entity-backed caller's identity against the owning Staff.id."""
    staff = caller_staff(caller)
    if staff is None:
        return None
    if staff["id"] != owning_staff_id:
        fail("ERR_NOT_RESOURCE_OWNER")
    return staff


# ---------------------------------------------------------------------------
# Pagination for list endpoints.
# ---------------------------------------------------------------------------
def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


# ---------------------------------------------------------------------------
# Cost ledger (PRD 2.10). Rows are append-only; reversal flips status only.
# ---------------------------------------------------------------------------
def post_cost_entry(unit_id, assignment_id, entry_kind, amount_cents, source_pool,
                    segment_index=None, segment_minutes=None,
                    night_differential_applied=False):
    row = base_entity()
    row.update({
        "unit_id": unit_id,
        "assignment_id": assignment_id,
        "entry_kind": entry_kind,
        "amount_cents": amount_cents,
        "status": "POSTED",
        "source_pool": source_pool,
        "segment_index": segment_index,
        "segment_minutes": segment_minutes,
        "night_differential_applied": night_differential_applied,
        "posted_at": db.clock,
        "reversed_at": None,
    })
    db.cost_entries[row["id"]] = row
    return row


def reverse_provisional(assignment):
    """Flip the assignment's PROVISIONAL row to REVERSED. amount_cents untouched."""
    moved = False
    for entry in sorted(calc.cost_entries_of_assignment(assignment["id"]), key=D.sort_key):
        if entry["entry_kind"] == "PROVISIONAL" and entry["status"] == "POSTED":
            entry["status"] = "REVERSED"
            entry["reversed_at"] = db.clock
            touch(entry)
            moved = True
    return moved


def close_open_segment(assignment):
    """Close the assignment's open watch segment at the logical clock and post one
    FINAL_SEGMENT row per calculations.assignment_labor_cost variant `final`."""
    started = assignment.get("current_segment_started_at")
    if started is None:
        return None
    minutes = whole_minutes(db.clock - started)
    if minutes < 0:
        minutes = 0
    staff = db.staff.get(assignment["staff_id"])
    unit = calc.unit_of_assignment(assignment)
    night = calc.is_night(started)
    amount = calc.segment_cost(staff["hourly_rate_cents"], minutes, staff["source_pool"], night)
    index = calc.watch_segment_count(assignment) + 1
    entry = post_cost_entry(
        unit_id=unit["id"] if unit else None,
        assignment_id=assignment["id"],
        entry_kind="FINAL_SEGMENT",
        amount_cents=amount,
        source_pool=staff["source_pool"],
        segment_index=index,
        segment_minutes=minutes,
        night_differential_applied=night,
    )
    assignment["current_segment_started_at"] = None
    return entry


def reeval_unit_budget(unit):
    """OPEN -> RESTRICTED when the recomputed ledger head reaches the budget."""
    if unit is None:
        return
    if unit["status"] == "OPEN" and calc.ledger_head(unit) >= unit["observation_cost_budget_cents"]:
        unit["status"] = "RESTRICTED"
        unit["restriction_reason"] = "BUDGET_THRESHOLD_REACHED"
        touch(unit)


def restrict_unit_for_lapse(unit):
    if unit is None:
        return
    if unit["status"] == "OPEN":
        unit["status"] = "RESTRICTED"
        unit["restriction_reason"] = "OBSERVATION_ORDER_LAPSED"
        touch(unit)


# ---------------------------------------------------------------------------
# Score / interval recomputation (PRD 3.2, 3.3).
# ---------------------------------------------------------------------------
def recompute_score_and_interval(order, variant, rebase_last_reassessed):
    patient = db.patients.get(order["patient_id"])
    age = patient["age_years"] if patient else 0
    score = calc.risk_score(order["risk_categories"], age, variant, order["id"])
    order["elopement_risk_score"] = score
    order["risk_score_variant"] = variant
    interval = calc.interval_hours_for_score(score)
    order["reassessment_interval_hours"] = interval
    if rebase_last_reassessed:
        order["last_reassessed_at"] = db.clock
    order["next_reassessment_due_at"] = order["last_reassessed_at"] + timedelta(hours=interval)
    return score, interval


def recompute_interval_only(order, rebase_last_reassessed):
    interval = calc.interval_hours_for_score(order["elopement_risk_score"])
    order["reassessment_interval_hours"] = interval
    if rebase_last_reassessed:
        order["last_reassessed_at"] = db.clock
    order["next_reassessment_due_at"] = order["last_reassessed_at"] + timedelta(hours=interval)
    return interval


# ---------------------------------------------------------------------------
# Feed release + console cascade (PRD 3.7).
# ---------------------------------------------------------------------------
def release_feed(feed, reason):
    feed["status"] = "RELEASED"
    feed["release_reason"] = reason
    feed["released_at"] = db.clock
    touch(feed)
    station = db.stations.get(feed["station_id"])
    if station is None:
        return
    touch(station)
    if station["status"] == "ACTIVE_MONITORING" and calc.active_feed_count(station) == 0:
        station["status"] = "IDLE"
        observer = db.staff.get(station["observer_staff_id"])
        if observer is not None and observer["status"] == "ON_ASSIGNMENT":
            observer["status"] = "AVAILABLE"
            touch(observer)


def release_active_feeds_of_order(order_id, reason):
    feeds = [f for f in calc.feeds_of_order(order_id) if f["status"] == "ACTIVE"]
    feeds.sort(key=D.sort_key)
    for feed in feeds:
        release_feed(feed, reason)
    return len(feeds)


# ---------------------------------------------------------------------------
# Assignment terminal transitions driven by the system (PRD 3.9).
# ---------------------------------------------------------------------------
def waive_documentation(assignment):
    if assignment["documentation_status"] == "PENDING":
        assignment["documentation_status"] = "WAIVED"


def system_void_assignment(assignment):
    """SCHEDULED -> VOIDED. Returns True when the ledger moved."""
    assignment["watch_status"] = "VOIDED"
    assignment["voided_at"] = db.clock
    waive_documentation(assignment)
    moved = reverse_provisional(assignment)
    touch(assignment)
    return moved


def system_complete_assignment(assignment):
    """ON_WATCH|ON_BREAK -> COMPLETED with completion_reason ORDER_DISCONTINUED."""
    close_open_segment(assignment)
    reverse_provisional(assignment)
    assignment["watch_status"] = "COMPLETED"
    assignment["completion_reason"] = "ORDER_DISCONTINUED"
    assignment["current_segment_started_at"] = None
    assignment["break_started_at"] = None
    assignment["final_cost_cents"] = calc.final_cost_from_ledger(assignment)
    waive_documentation(assignment)
    touch(assignment)
    observer = db.staff.get(assignment["staff_id"])
    if observer is not None and observer["status"] == "ON_ASSIGNMENT":
        observer["status"] = "AVAILABLE"
        touch(observer)
    return True


# ---------------------------------------------------------------------------
# ObservationOrder -> DISCONTINUED cascade (PRD 3.9).
# ---------------------------------------------------------------------------
def discontinue_order(order):
    order["status"] = "DISCONTINUED"
    order["discontinued_at"] = db.clock
    touch(order)
    assignments = calc.assignments_of_order(order["id"])
    ledger_moved = False
    scheduled = sorted([a for a in assignments if a["watch_status"] == "SCHEDULED"], key=D.sort_key)
    for assignment in scheduled:
        if system_void_assignment(assignment):
            ledger_moved = True
    running = sorted(
        [a for a in assignments if a["watch_status"] in ("ON_WATCH", "ON_BREAK")], key=D.sort_key
    )
    for assignment in running:
        system_complete_assignment(assignment)
        ledger_moved = True
    release_active_feeds_of_order(order["id"], "ORDER_TERMINATED")
    if ledger_moved:
        unit = calc.unit_of_order(order)
        if unit is not None:
            touch(unit)
            reeval_unit_budget(unit)


# ---------------------------------------------------------------------------
# ObservationOrder -> LAPSED cascade (PRD 3.3).
# ---------------------------------------------------------------------------
def lapse_order(order):
    order["status"] = "LAPSED"
    order["lapsed_at"] = db.clock
    touch(order)
    release_active_feeds_of_order(order["id"], "ORDER_TERMINATED")
    restrict_unit_for_lapse(calc.unit_of_order(order))


# ---------------------------------------------------------------------------
# The reassessment sweep, run as a side effect of every clock advance (PRD 3.3).
# ---------------------------------------------------------------------------
def run_reassessment_sweep():
    candidates = [
        o for o in db.orders.values() if o["status"] in ("ACTIVE", "REASSESSMENT_DUE")
    ]
    candidates.sort(key=lambda o: (o["next_reassessment_due_at"], o["created_at"], o["_seq"]))
    marked = 0
    lapsed = 0
    grace = timedelta(hours=D.REASSESSMENT_GRACE_HOURS)
    for order in candidates:
        due = order["next_reassessment_due_at"]
        # Precedence is pinned: the lapse rule is considered first, then the due
        # rule; at most one transition per order per clock call.
        if order["status"] == "REASSESSMENT_DUE" and db.clock >= due + grace:
            lapse_order(order)
            lapsed += 1
        elif order["status"] == "ACTIVE" and db.clock >= due:
            order["status"] = "REASSESSMENT_DUE"
            touch(order)
            marked += 1
    return marked, lapsed

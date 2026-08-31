"""Shared domain helpers: lookups, counters, cascades, booth geometry."""
from datetime import timedelta

import calc
from errors import ApiError
from store import db, sort_key, touch

CLOSED_ORDER_STATES = ("DELIVERED", "RECALLED", "CANCELLED")
LIVE_CASTING_STATES = ("PROPOSED", "HOLD_REQUESTED", "HELD", "CONFIRMED", "RECORDED")
ROOM_OCCUPYING = ("SCHEDULED", "CONFIRMED", "IN_PROGRESS", "COMPLETED")
HELD_STATES = ("SCHEDULED", "CONFIRMED", "IN_PROGRESS")


# --------------------------------------------------------------------------
# resolution helpers
# --------------------------------------------------------------------------
def _get(table, row_id, error_id):
    if not isinstance(row_id, str):
        raise ApiError(error_id)
    row = table.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def get_title(row_id):
    return _get(db.titles, row_id, "ERR_TITLE_NOT_FOUND")


def get_cut(row_id):
    return _get(db.cuts, row_id, "ERR_CUT_NOT_FOUND")


def get_character(row_id):
    return _get(db.characters, row_id, "ERR_CHARACTER_NOT_FOUND")


def get_spec(row_id):
    return _get(db.platform_specs, row_id, "ERR_PLATFORM_SPEC_NOT_FOUND")


def get_talent(row_id):
    return _get(db.voice_talents, row_id, "ERR_TALENT_NOT_FOUND")


def get_studio(row_id):
    return _get(db.studios, row_id, "ERR_STUDIO_NOT_FOUND")


def get_order(row_id):
    return _get(db.orders, row_id, "ERR_ORDER_NOT_FOUND")


def get_adaptation(row_id):
    return _get(db.adaptations, row_id, "ERR_ADAPTATION_NOT_FOUND")


def get_assignment(row_id):
    return _get(db.assignments, row_id, "ERR_ASSIGNMENT_NOT_FOUND")


def get_session(row_id):
    return _get(db.sessions, row_id, "ERR_SESSION_NOT_FOUND")


def get_mix_job(row_id):
    return _get(db.mix_jobs, row_id, "ERR_MIX_JOB_NOT_FOUND")


def get_review(row_id):
    return _get(db.reviews, row_id, "ERR_REVIEW_NOT_FOUND")


def get_retake_item(row_id):
    return _get(db.retake_items, row_id, "ERR_RETAKE_ITEM_NOT_FOUND")


def get_payment(row_id):
    return _get(db.payments, row_id, "ERR_PAYMENT_NOT_FOUND")


# --------------------------------------------------------------------------
# relationship helpers
# --------------------------------------------------------------------------
def rows_where(table, **filters):
    out = []
    for row in table.values():
        match = True
        for key, value in filters.items():
            if row.get(key) != value:
                match = False
                break
        if match:
            out.append(row)
    return sorted(out, key=sort_key)


def newest(rows):
    if not rows:
        return None
    return sorted(rows, key=sort_key)[-1]


def order_adaptation(order_id):
    return newest(rows_where(db.adaptations, order_id=order_id))


def newest_mix_job(order_id):
    return newest(rows_where(db.mix_jobs, order_id=order_id))


def newest_review(order_id):
    return newest(rows_where(db.reviews, order_id=order_id))


def newest_payment(assignment_id):
    return newest(rows_where(db.payments, casting_assignment_id=assignment_id))


def order_cut(order):
    return db.cuts.get(order["cut_id"])


def order_spec(order):
    return db.platform_specs.get(order["platform_spec_id"])


def assignment_talent(assignment):
    return db.voice_talents.get(assignment["talent_id"])


def check_order_open(order):
    """Rung 10: ERR_ORDER_LOCKED."""
    if order["status"] in CLOSED_ORDER_STATES:
        raise ApiError("ERR_ORDER_LOCKED")


def live_assignments(order_id):
    return [a for a in rows_where(db.assignments, order_id=order_id)
            if a.get("superseded_by_id") is None]


# --------------------------------------------------------------------------
# counters
# --------------------------------------------------------------------------
def recompute_assignment_minutes(assignment):
    recorded = 0
    retake = 0
    for s in db.sessions.values():
        if s["casting_assignment_id"] != assignment["id"] or s["status"] != "COMPLETED":
            continue
        if s["is_retake"]:
            retake += s["duration_minutes"]
        else:
            recorded += s["duration_minutes"]
    assignment["recorded_minutes"] = recorded
    assignment["retake_minutes"] = retake


def add_studio_minutes(studio, minutes):
    studio["booked_minutes"] = studio["booked_minutes"] + minutes
    touch(studio)


def add_talent_held(talent, minutes):
    talent["held_minutes"] = talent["held_minutes"] + minutes
    touch(talent)


def move_held_to_recorded(talent, minutes):
    talent["held_minutes"] = talent["held_minutes"] - minutes
    talent["recorded_minutes"] = talent["recorded_minutes"] + minutes
    touch(talent)


# --------------------------------------------------------------------------
# booth geometry
# --------------------------------------------------------------------------
def _intersects_half_open(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def _intersects_closed(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end


def studio_buffered_conflict(studio, start_utc, end_utc, exclude_id=None, buffer_others=True):
    """Half-open studio geometry with a trailing turnaround buffer."""
    buffer_delta = timedelta(minutes=studio["turnaround_buffer_minutes"])
    new_end = end_utc + buffer_delta
    for other in db.sessions.values():
        if other["studio_id"] != studio["id"]:
            continue
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        if other["status"] not in ROOM_OCCUPYING:
            continue
        other_end = other["end_utc"] + buffer_delta if buffer_others else other["end_utc"]
        if _intersects_half_open(start_utc, new_end, other["start_utc"], other_end):
            return True
    return False


def talent_closed_conflict(talent_id, start_utc, end_utc, exclude_id=None):
    """Closed, unbuffered talent geometry: touching endpoints DO collide."""
    for other in db.sessions.values():
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        if other["status"] not in ROOM_OCCUPYING:
            continue
        assignment = db.assignments.get(other["casting_assignment_id"])
        if assignment is None or assignment["talent_id"] != talent_id:
            continue
        if _intersects_closed(start_utc, end_utc, other["start_utc"], other["end_utc"]):
            return True
    return False


def studio_day_minutes(studio, day_start, exclude_id=None):
    day = day_start.date()
    total = 0
    for other in db.sessions.values():
        if other["studio_id"] != studio["id"]:
            continue
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        if other["status"] not in ROOM_OCCUPYING:
            continue
        if other["start_utc"].date() != day:
            continue
        total += other["duration_minutes"]
    return total


def talent_day_minutes(talent_id, day_start, exclude_id=None):
    """Recorded plus held minutes on the requested UTC calendar day."""
    day = day_start.date()
    total = 0
    for other in db.sessions.values():
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        if other["status"] not in ROOM_OCCUPYING:
            continue
        assignment = db.assignments.get(other["casting_assignment_id"])
        if assignment is None or assignment["talent_id"] != talent_id:
            continue
        if other["start_utc"].date() != day:
            continue
        total += other["duration_minutes"]
    return total


# --------------------------------------------------------------------------
# order cascades
# --------------------------------------------------------------------------
def advance_order(order, from_states, to_state):
    if order["status"] not in from_states:
        return False
    order["status"] = to_state
    touch(order)
    return True


def cascade_order_to_recording_on_schedule(order):
    """A session landing on the calendar advances CASTING -> RECORDING."""
    return advance_order(order, ("CASTING",), "RECORDING")


# --------------------------------------------------------------------------
# waitlist promotion selector
# --------------------------------------------------------------------------
def run_waitlist_promotion(studio):
    candidates = []
    for row in db.sessions.values():
        if row["studio_id"] != studio["id"] or row["status"] != "WAITLISTED":
            continue
        order = db.orders.get(row["order_id"])
        if order is None or order["status"] not in ("CASTING", "RECORDING"):
            continue
        if studio_buffered_conflict(studio, row["start_utc"], row["end_utc"],
                                    exclude_id=row["id"], buffer_others=False):
            continue
        assignment = db.assignments.get(row["casting_assignment_id"])
        if assignment is None:
            continue
        if talent_closed_conflict(assignment["talent_id"], row["start_utc"], row["end_utc"],
                                  exclude_id=row["id"]):
            continue
        day_booked = studio_day_minutes(studio, row["start_utc"], exclude_id=row["id"])
        if day_booked + row["duration_minutes"] > studio["daily_capacity_minutes"]:
            continue
        candidates.append(row)

    if not candidates:
        return None

    def rank(row):
        order = db.orders[row["order_id"]]
        return (calc.PRIORITY_RANK[order["priority_tier"]], row["start_utc"],
                row["created_at"], row["_seq"])

    winner = sorted(candidates, key=rank)[0]
    assignment = db.assignments[winner["casting_assignment_id"]]
    talent = db.voice_talents[assignment["talent_id"]]

    winner["status"] = "SCHEDULED"
    winner["waitlisted_reason"] = None
    touch(winner)
    add_studio_minutes(studio, winner["duration_minutes"])
    add_talent_held(talent, winner["duration_minutes"])
    cascade_order_to_recording_on_schedule(db.orders[winner["order_id"]])
    return winner

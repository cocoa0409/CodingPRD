"""Aggregate recomputation and in-request cascades (PRD 2.8)."""
from common import (
    COUNTED_ACTIVE,
    ENTERED_POPULATION,
    PLANNABLE_BLOCKS,
    parse_instant,
    shift_instant,
)
import calc
import store
from store import set_fields


# --------------------------------------------------------------- collections
def entries_of_show(show_id):
    return [e for e in store.rows("entries") if e["show_id"] == show_id]


def entries_of_class(class_id):
    return [e for e in store.rows("entries") if e["class_id"] == class_id]


def classes_of_show(show_id):
    return [c for c in store.rows("classes") if c["show_id"] == show_id]


def blocks_of_show(show_id):
    return [b for b in store.rows("blocks") if b["show_id"] == show_id]


def blocks_of_class(class_id):
    return [b for b in store.rows("blocks") if b["class_id"] == class_id]


def slots_of_judge(judge_id):
    return [s for s in store.rows("slots") if s["judge_id"] == judge_id]


def entries_of_dog(dog_id):
    return [e for e in store.rows("entries") if e["dog_id"] == dog_id]


def protests_of_show(show_id):
    return [p for p in store.rows("protests") if p["show_id"] == show_id]


def filings_of_show(show_id):
    return [f for f in store.rows("filings") if f["show_id"] == show_id]


# ------------------------------------------------------------- recomputation
def recompute_class_counts(cls):
    rows = entries_of_class(cls["id"])
    entry_count = len([e for e in rows if e["entry_status"] in ENTERED_POPULATION])
    present_count = len(
        [e for e in rows if e["entry_status"] in ("CHECKED_IN", "JUDGED")]
    )
    return set_fields(cls, entry_count=entry_count, present_count=present_count)


def recompute_slot(slot):
    judge = store.get("judges", slot["judge_id"])
    assigned = len(
        [c for c in store.rows("classes") if c["assigned_slot_id"] == slot["id"]]
    )
    capacity = min(judge["max_daily_dog_count"], calc.MAX_DOGS_PER_JUDGE_PER_DAY)
    return set_fields(
        slot, assigned_class_count=assigned, assigned_dog_capacity=capacity
    )


def recompute_judge_slot_count(judge):
    confirmed = len(
        [s for s in slots_of_judge(judge["id"]) if s["slot_status"] == "CONFIRMED"]
    )
    return set_fields(judge, confirmed_slot_count=confirmed)


def recompute_club_events(club):
    approved = len(
        [
            s
            for s in store.rows("shows")
            if s["club_id"] == club["id"]
            and s["status"] in ("APPROVED", "IN_PROGRESS", "COMPLETED", "RESULTS_FILED")
        ]
    )
    return set_fields(club, events_approved_count=approved)


def recompute_show_money(show):
    rows = entries_of_show(show["id"])
    fee_charged = sum(e["entry_fee_cents"] for e in rows)
    fee_refunded = sum(e["fee_refunded_cents"] for e in rows)
    levy_total = sum(e["levy_cents"] for e in rows)
    confirmed = len(
        [
            e
            for e in rows
            if e["source"] == "HANDLER_SUBMITTED" and e["entry_status"] in COUNTED_ACTIVE
        ]
    )
    return set_fields(
        show,
        fee_charged_cents=fee_charged,
        fee_refunded_cents=fee_refunded,
        fee_collected_cents=fee_charged - fee_refunded,
        levy_total_cents=levy_total,
        confirmed_entry_count=confirmed,
    )


def recompute_show_points(show):
    total = sum(e["points_awarded"] for e in entries_of_show(show["id"]))
    return set_fields(show, points_awarded_total=total)


def recompute_dog(dog):
    rows = entries_of_dog(dog["id"])
    total = sum(e["points_awarded"] for e in rows)
    majors = len([e for e in rows if e["points_awarded"] >= calc.MAJOR_MIN_POINTS])
    return set_fields(dog, championship_points_total=total, majors_count=majors)


def block_geometry(cls, block_start_at, scheduled_dog_count, deferred_dog_count):
    conflict_free, estimate = calc.block_minutes(
        cls["class_level"], scheduled_dog_count, deferred_dog_count
    )
    return {
        "scheduled_dog_count": scheduled_dog_count,
        "conflict_free_minutes": conflict_free,
        "deferred_dog_count": deferred_dog_count,
        "judging_minutes_estimate": estimate,
        "block_end_at": shift_instant(block_start_at, minutes=estimate),
    }


def class_scheduled_dog_count(class_id):
    return len(
        [e for e in entries_of_class(class_id) if e["entry_status"] in COUNTED_ACTIVE]
    )


def class_deferred_dog_count(class_id):
    return len([e for e in entries_of_class(class_id) if e["conflict_deferred"]])


def recompute_block(block):
    cls = store.get("classes", block["class_id"])
    geometry = block_geometry(
        cls,
        block["block_start_at"],
        class_scheduled_dog_count(block["class_id"]),
        class_deferred_dog_count(block["class_id"]),
    )
    return set_fields(block, **geometry)


def recompute_blocks_of_class(class_id):
    for block in blocks_of_class(class_id):
        if block["block_status"] in PLANNABLE_BLOCKS:
            recompute_block(block)


# ------------------------------------------------------- interval predicates
def _span_end(start_at, minutes):
    return shift_instant(start_at, minutes=minutes)


def _overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def occupancy_conflict(show_id, ring_number, candidate_start, candidate_end,
                       exclude_ids):
    for block in blocks_of_show(show_id):
        if block["id"] in exclude_ids:
            continue
        if block["ring_number"] != ring_number:
            continue
        if block["block_status"] not in PLANNABLE_BLOCKS:
            continue
        if _overlaps(
            candidate_start, candidate_end, block["block_start_at"],
            block["block_end_at"],
        ):
            return True
    return False


def rest_conflict(judge_id, candidate_start, candidate_end, exclude_ids):
    buffer_minutes = calc.JUDGE_REST_BUFFER_MINUTES
    for block in store.rows("blocks"):
        if block["id"] in exclude_ids:
            continue
        if block["block_status"] not in PLANNABLE_BLOCKS:
            continue
        slot = store.get("slots", block["slot_id"])
        if slot is None or slot["judge_id"] != judge_id:
            continue
        separated = (
            candidate_start >= _span_end(block["block_end_at"], buffer_minutes)
            or block["block_start_at"] >= _span_end(candidate_end, buffer_minutes)
        )
        if not separated:
            return True
    return False


# ----------------------------------------------------- judge daily dog load
def slot_load(slot_id):
    count = 0
    for entry in store.rows("entries"):
        if entry["entry_status"] not in COUNTED_ACTIVE:
            continue
        cls = store.get("classes", entry["class_id"])
        if cls is not None and cls["assigned_slot_id"] == slot_id:
            count += 1
    return count


def judge_daily_load(judge_id, show_date):
    total = 0
    for slot in slots_of_judge(judge_id):
        if slot["slot_status"] not in ("PROPOSED", "CONFIRMED"):
            continue
        show = store.get("shows", slot["show_id"])
        if show is None or show["show_date"] != show_date:
            continue
        total += slot_load(slot["id"])
    return total


# ------------------------------------------- handler ring conflict resolution
def _pair_order(first, second):
    key_a = (first["block_start_at"], first["created_at"], first["_seq"])
    key_b = (second["block_start_at"], second["created_at"], second["_seq"])
    if key_a > key_b:
        return second, first
    return first, second


def conflict_resolution(show):
    published = [
        b for b in blocks_of_show(show["id"]) if b["block_status"] == "PUBLISHED"
    ]
    deferred_ids = set()
    for index, first in enumerate(published):
        for second in published[index + 1:]:
            if first["ring_number"] == second["ring_number"]:
                continue
            first_end = _span_end(
                first["block_start_at"], first["conflict_free_minutes"]
            )
            second_end = _span_end(
                second["block_start_at"], second["conflict_free_minutes"]
            )
            if not _overlaps(
                first["block_start_at"], first_end,
                second["block_start_at"], second_end,
            ):
                continue
            earlier, later = _pair_order(first, second)
            earlier_handlers = set(
                e["handler_id"]
                for e in entries_of_class(earlier["class_id"])
                if e["entry_status"] in ("CONFIRMED", "CHECKED_IN")
            )
            for entry in entries_of_class(later["class_id"]):
                if entry["entry_status"] not in ("CONFIRMED", "CHECKED_IN"):
                    continue
                if entry["handler_id"] in earlier_handlers:
                    deferred_ids.add(entry["id"])
    for entry in entries_of_show(show["id"]):
        set_fields(entry, conflict_deferred=entry["id"] in deferred_ids)
    for block in blocks_of_show(show["id"]):
        if block["block_status"] in PLANNABLE_BLOCKS:
            recompute_block(block)


# ------------------------------------------------------- championship points
def compute_award(cls):
    """Return (counted_dog_count, winner_points) for a class."""
    show = store.get("shows", cls["show_id"])
    scale = cls["points_scale_override"] or show["championship_points_scale"]
    counted_statuses = calc.counted_statuses_for_scale(scale)
    counted = [
        e for e in entries_of_class(cls["id"])
        if e["entry_status"] in counted_statuses
    ]
    feeder_max = 0
    for feeder in store.rows("classes"):
        if feeder["parent_class_id"] == cls["id"] and feeder["status"] == "COMPLETED":
            feeder_max = max(feeder_max, feeder["base_points"])
    return len(counted), calc.winner_points_for(
        cls["class_level"], len(counted), feeder_max
    )


def rerun_award(cls):
    """Re-run the award over a class in place (protest remedy path)."""
    counted_dog_count, winner_points = compute_award(cls)
    rows = entries_of_class(cls["id"])
    winner = None
    for entry in rows:
        if entry.get("placement") == 1:
            winner = entry
            break
    for entry in rows:
        points = winner_points if (winner is not None and entry["id"] == winner["id"]) else 0
        set_fields(entry, points_awarded=points)
    set_fields(cls, counted_dog_count=counted_dog_count, base_points=winner_points)
    show = store.get("shows", cls["show_id"])
    for dog_id in set(e["dog_id"] for e in rows):
        recompute_dog(store.get("dogs", dog_id))
    recompute_show_points(show)


def entry_fields(show_id, class_id, dog_id, handler_id, source="HANDLER_SUBMITTED",
                 entry_status="RECEIVED", armband_number=None,
                 promoted_from_entry_id=None, entry_fee_cents=0, levy_cents=0):
    """The full ordered field set of an Entry at creation time."""
    return {
        "show_id": show_id,
        "class_id": class_id,
        "dog_id": dog_id,
        "handler_id": handler_id,
        "promoted_from_entry_id": promoted_from_entry_id,
        "source": source,
        "entry_status": entry_status,
        "welfare_status": "CLEAR",
        "armband_number": armband_number,
        "entry_fee_cents": entry_fee_cents,
        "levy_cents": levy_cents,
        "fee_refunded_cents": 0,
        "net_fee_cents": entry_fee_cents,
        "fee_basis": "PROVISIONAL",
        "placement": None,
        "points_awarded": 0,
        "conflict_deferred": False,
    }


def complete_published_blocks(cls):
    """Every PUBLISHED block of the class moves to COMPLETED."""
    for block in blocks_of_class(cls["id"]):
        if block["block_status"] == "PUBLISHED":
            set_fields(block, block_status="COMPLETED")


def heat_blocked(show, cls):
    """RED advisory on an outdoor show blocks performance ring work."""
    return (
        cls["class_level"] == "PERFORMANCE"
        and bool(show["outdoor_venue"])
        and show["current_advisory_level"] == "RED"
    )


def planning_dog_load(judge_id, show, cls):
    """Daily dog load for a judge, counting the class being planned."""
    total = judge_daily_load(judge_id, show["show_date"])
    slot_id = cls["assigned_slot_id"]
    already_counted = False
    if slot_id is not None:
        slot = store.get("slots", slot_id)
        if (
            slot is not None
            and slot["judge_id"] == judge_id
            and slot["slot_status"] in ("PROPOSED", "CONFIRMED")
        ):
            show_of_slot = store.get("shows", slot["show_id"])
            if show_of_slot is not None and show_of_slot["show_date"] == show["show_date"]:
                already_counted = True
    if not already_counted:
        total += class_scheduled_dog_count(cls["id"])
    return total


# ----------------------------------------------------------- title recording
def dogs_of_show(show_id):
    seen = []
    ids = set()
    for entry in entries_of_show(show_id):
        if entry["dog_id"] in ids:
            continue
        dog = store.get("dogs", entry["dog_id"])
        if dog is None:
            continue
        ids.add(entry["dog_id"])
        seen.append(dog)
    return sorted(seen, key=store.sort_key)


def record_titles(show_id):
    """Append every earned code a dog does not already hold. Returns the count."""
    appended = 0
    for dog in dogs_of_show(show_id):
        earned = calc.earned_title_codes(dog)
        codes = list(dog["title_codes"])
        for code in calc.TITLE_CODE_ORDER:
            if code in earned and code not in codes:
                codes.append(code)
                appended += 1
        set_fields(dog, title_codes=codes)
    return appended


def strip_unsupported_titles(show_id):
    """Remove codes the recomputed totals no longer support. Returns the count."""
    removed = 0
    for dog in dogs_of_show(show_id):
        earned = calc.earned_title_codes(dog)
        codes = [c for c in dog["title_codes"] if c in earned]
        removed += len(dog["title_codes"]) - len(codes)
        set_fields(dog, title_codes=codes)
    return removed

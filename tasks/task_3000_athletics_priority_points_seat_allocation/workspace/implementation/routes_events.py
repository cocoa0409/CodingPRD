"""Selection events, slot geometry and the slot lifecycle (PRD section 3.8)."""
from flask import Blueprint

import auth
import calc
import clock
import derive
import envelope
import enums
import num
import serial
import validation as v
from errors import err, invalid, invalid_state
from store import DB, by_created_at, get_path, new_row, touch

bp = Blueprint("events", __name__)


def _windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open windows: touching at a shared boundary instant is permitted."""
    return a_start < b_end and b_start < a_end


def _slot_geometry(event, index):
    stride = int(event["slot_minutes"]) + int(event["slot_buffer_minutes"])
    slot_start = clock.plus_minutes(event["window_start"], index * stride)
    slot_end = clock.plus_minutes(slot_start, int(event["slot_minutes"]))
    return slot_start, slot_end


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
@bp.get("/athletics/point-recalculations/<recalc_id>/selection-events")
def list_recalculation_events(recalc_id):
    auth.require(auth.NO_ANALYST)
    recalc = get_path("recalculation", recalc_id)
    event_type = v.q_enum("event_type", enums.EVENT_TYPES)
    status = v.q_enum("status", enums.EVENT_STATUSES)
    rows = [e for e in DB.events.values() if e["recalculation_id"] == recalc["id"]]
    if event_type is not None:
        rows = [e for e in rows if e["event_type"] == event_type]
    if status is not None:
        rows = [e for e in rows if e["status"] == status]
    return envelope.paginated(by_created_at(rows), serial.event)


@bp.get("/athletics/selection-events/<event_id>")
def get_event(event_id):
    auth.require(auth.NO_ANALYST)
    event = get_path("event", event_id)
    return envelope.ok(serial.event(event))


@bp.get("/athletics/selection-slots")
def list_slots():
    """Ordered by slot_index ascending -- the one collection that overrides
    the created_at ordering (PRD section 2.6)."""
    auth.require(auth.NO_ANALYST)
    event_id = v.q_str("selection_event_id")
    donor_id = v.q_str("donor_id")
    slot_status = v.q_enum("slot_status", enums.SLOT_STATUSES)
    rows = list(DB.slots.values())
    if event_id is not None:
        rows = [s for s in rows if s["selection_event_id"] == event_id]
    if donor_id is not None:
        rows = [s for s in rows if s["donor_id"] == donor_id]
    if slot_status is not None:
        rows = [s for s in rows if s["slot_status"] == slot_status]
    rows = sorted(rows, key=lambda s: (int(s["slot_index"]), s["created_at"], s["_seq"]))
    return envelope.paginated(rows, serial.slot)


@bp.get("/athletics/selection-slots/<slot_id>")
def get_slot(slot_id):
    auth.require(auth.NO_ANALYST)
    slot = get_path("slot", slot_id)
    return envelope.ok(serial.slot(slot))


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------
@bp.post("/athletics/point-recalculations/<recalc_id>/selection-events")
def create_event(recalc_id):
    auth.require(auth.OFFICE)
    recalc = get_path("recalculation", recalc_id)
    body = v.body_dict()
    event_type = v.enum_field(body, "event_type", enums.EVENT_TYPES)
    window_start = v.instant_field(body, "window_start")
    window_end = v.instant_field(body, "window_end")
    slot_minutes = v.int_field(body, "slot_minutes", minimum=1)
    buffer_minutes = v.int_field(body, "slot_buffer_minutes", required=False,
                                 minimum=0, default=0)
    min_points = v.num_field(body, "eligible_donor_min_points", required=False,
                             minimum=0, default=num.dec("0.00"))
    if window_end <= window_start:
        raise invalid("'window_end' must be strictly later than 'window_start'")
    row = new_row(
        recalculation_id=recalc["id"],
        event_type=event_type,
        status="DRAFT",
        window_start=window_start,
        window_end=window_end,
        slot_minutes=slot_minutes,
        slot_buffer_minutes=buffer_minutes,
        eligible_donor_min_points=min_points,
        published_slot_count=0,
        scheduled_slot_count=0,
    )
    DB.events[row["id"]] = row
    return envelope.created(serial.event(row))


@bp.post("/athletics/selection-events/<event_id>/publish-slots")
def publish_slots(event_id):
    auth.require(auth.OFFICE)
    event = get_path("event", event_id)
    v.body_dict()
    if event["status"] not in ("DRAFT", "SLOTS_STALE"):
        raise invalid_state("slots may only be published from DRAFT or SLOTS_STALE")
    recalc = DB.recalculations.get(event["recalculation_id"])
    if recalc is None or recalc["status"] != "CERTIFIED":
        raise err("ERR_RECALCULATION_NOT_CERTIFIED",
                  "the parent recalculation must be in CERTIFIED before slots publish")
    pool = calc.event_pool(event)
    if not pool:
        raise err("ERR_NO_ELIGIBLE_DONORS",
                  "no donor qualifies for this event's candidate pool")
    # All-or-nothing: the geometry is checked before a single slot is written.
    _, last_end = _slot_geometry(event, len(pool) - 1)
    if last_end > event["window_end"]:
        raise err("ERR_SLOT_WINDOW_OVERFLOW",
                  "the last slot would end after the event's window_end")
    for stale in [s for s in DB.slots.values()
                  if s["selection_event_id"] == event["id"] and s["slot_status"] == "STALE"]:
        del DB.slots[stale["id"]]
    for index, donor in enumerate(pool):
        slot_start, slot_end = _slot_geometry(event, index)
        slot = new_row(
            selection_event_id=event["id"],
            donor_id=donor["id"],
            rank_at_publish=donor["rank_position"],
            slot_index=index,
            slot_start=slot_start,
            slot_end=slot_end,
            slot_status="SCHEDULED",
        )
        DB.slots[slot["id"]] = slot
    event["status"] = "SLOTS_PUBLISHED"
    event["published_slot_count"] = len(pool)
    event["scheduled_slot_count"] = len(pool)
    # Republication is the recovery edge: blocked requests come back to life.
    for request in by_created_at(list(DB.requests.values())):
        if request["selection_event_id"] != event["id"] or request["status"] != "BLOCKED":
            continue
        request["status"] = "AWAITING_SELECTION"
        touch(request)
        donor = DB.donors.get(request["donor_id"])
        if donor is not None:
            derive.recompute_pending_request_count(donor)
    touch(event)
    return envelope.ok(serial.event(event))


@bp.post("/athletics/selection-events/<event_id>/gate")
def gate_event(event_id):
    auth.require(auth.OFFICE)
    event = get_path("event", event_id)
    body = v.body_dict()
    to_status = v.enum_field(body, "to_status", enums.EVENT_GATE_STATUSES)
    if to_status == "OPEN":
        if event["status"] != "SLOTS_PUBLISHED":
            raise invalid_state("only an event in SLOTS_PUBLISHED may be opened")
        for other in DB.events.values():
            if other["id"] == event["id"]:
                continue
            if other["recalculation_id"] != event["recalculation_id"]:
                continue
            if other["status"] not in ("SLOTS_PUBLISHED", "OPEN"):
                continue
            if _windows_overlap(event["window_start"], event["window_end"],
                                other["window_start"], other["window_end"]):
                raise err("ERR_SELECTION_WINDOW_OVERLAP",
                          "this event's window overlaps event '%s'" % other["id"])
        event["status"] = "OPEN"
    else:
        if event["status"] != "OPEN":
            raise invalid_state("only an event in OPEN may be closed")
        event["status"] = "CLOSED"
        for slot in derive.event_slots(event):
            if slot["slot_status"] == "SCHEDULED":
                slot["slot_status"] = "FORFEITED"
                touch(slot)
        derive.recompute_scheduled_slot_count(event)
        for request in by_created_at(list(DB.requests.values())):
            if request["selection_event_id"] != event["id"]:
                continue
            if request["status"] not in ("AWAITING_SELECTION", "BLOCKED"):
                continue
            request["status"] = "DENIED"
            request["decision_note"] = (
                "denied automatically because the selection event closed")
            touch(request)
            donor = DB.donors.get(request["donor_id"])
            if donor is not None:
                derive.recompute_pending_request_count(donor)
    touch(event)
    return envelope.ok(serial.event(event))


@bp.post("/athletics/selection-slots/<slot_id>/forfeit")
def forfeit_slot(slot_id):
    caller = auth.require(auth.DONOR_AND_OFFICER)
    slot = get_path("slot", slot_id)
    auth.require_owner(caller, slot["donor_id"])
    body = v.body_dict()
    v.str_field(body, "reason", min_len=1, max_len=None)
    if slot["slot_status"] != "SCHEDULED":
        raise invalid_state("only a SCHEDULED slot may be forfeited")
    slot["slot_status"] = "FORFEITED"
    touch(slot)
    event = DB.events.get(slot["selection_event_id"])
    if event is not None:
        derive.recompute_scheduled_slot_count(event)
    return envelope.ok(serial.slot(slot))

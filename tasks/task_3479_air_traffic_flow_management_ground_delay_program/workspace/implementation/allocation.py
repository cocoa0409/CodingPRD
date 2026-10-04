"""calculations.rbs_slot_allocation — INITIAL mode (TMI activation) and
REAPPLY mode (revision application).

Ration-by-schedule: slots are generated at program_start + k*(3600/rate)
seconds; the last reserved_slots slots (max(GA_MIN_RESERVED,
floor(slot_count*GA_QUOTA_PCT/100))) form the GA pool and are skipped by the
initial carrier allocation; eligible flights (arrival facility match,
ops SCHEDULED/AIRBORNE, control UNCONTROLLED, scheduled_arrival inside the
half-open program window) are ranked by scheduled_arrival ASC then created_at
ASC and take positional slots; flights past the last non-reserved slot are
overflow with a virtual CTA of program_end and stay UNCONTROLLED.

REAPPLY: GA-accommodated flights keep their slots; all other slots are torn
down and rebuilt over the new rate/window; the eligible set is re-snapshotted;
flights whose CTA changed get REVISION_MOVE transactions.
"""

from datetime import timedelta

from constants import GA_MIN_RESERVED, GA_QUOTA_PCT
from ledger import (
    ensure_ledger,
    program_flights,
    recompute_fair_shares,
    recompute_provisional,
    write_transaction,
)
from storage import DB, create_entity, get_clock, touch


def slots_of(tmi_id):
    rows = [s for s in DB["slots"].values() if s["tmi_id"] == tmi_id]
    rows.sort(key=lambda s: (s["slot_index"], s["slot_time"], s["_seq"]))
    return rows


def eligible_flights(tmi):
    """Snapshot predicate (PRD 3.4): arrival facility match, ops SCHEDULED or
    AIRBORNE, control UNCONTROLLED, scheduled_arrival inside the half-open
    program window; ration-by-schedule order."""
    start, end = tmi["program_start"], tmi["program_end"]
    out = [
        f
        for f in DB["flights"].values()
        if f["arrival_facility_id"] == tmi["facility_id"]
        and f["ops_status"] in ("SCHEDULED", "AIRBORNE")
        and f["control_status"] == "UNCONTROLLED"
        and start <= f["scheduled_arrival"] < end
    ]
    out.sort(key=lambda f: (f["scheduled_arrival"], f["created_at"], f["_seq"]))
    return out


def _grid_geometry(tmi):
    interval = 3600 // tmi["controlled_rate"]  # exact: rate divides 3600
    span = int((tmi["program_end"] - tmi["program_start"]).total_seconds())
    slot_count = span // interval
    reserved = max(GA_MIN_RESERVED, slot_count * GA_QUOTA_PCT // 100)
    tmi["_slot_count"] = slot_count
    tmi["_reserved_slots"] = reserved
    return interval, slot_count, reserved


def _assign_common(tmi, carrier_slots, eligible, transaction_type, old_states):
    """Positional assignment. old_states maps flight_id -> (cta, was_slotted,
    was_overflow, prov) captured before any teardown (None in INITIAL mode);
    only flights whose assignment changed are touched and journaled."""
    for position, flight in enumerate(eligible):
        if position < len(carrier_slots):
            slot = carrier_slots[position]
            slot["status"] = "ASSIGNED"
            slot["assigned_flight_id"] = flight["id"]
            if slot["original_flight_id"] is None:
                slot["original_flight_id"] = flight["id"]
            touch(slot)
            new_cta = slot["slot_time"]
            slotted = True
            overflow = False
        else:
            slot = None
            new_cta = tmi["program_end"]
            slotted = False
            overflow = True
        old = old_states.get(flight["id"]) if old_states else None
        old_cta = old[0] if old else None
        old_prov = old[3] if old else 0
        flight["control_status"] = "SLOTTED" if slotted else "UNCONTROLLED"
        flight["controlled_arrival"] = new_cta
        flight["is_overflow"] = overflow
        flight["_tmi_id"] = tmi["id"]
        recompute_provisional(flight)
        changed = (
            old is None
            or old_cta != new_cta
            or old[1] != slotted
            or old[2] != overflow
        )
        if changed:
            touch(flight)
            write_transaction(
                tmi["id"],
                slot["id"] if slot else None,
                flight["id"],
                flight["operator_id"],
                transaction_type,
                old_cta,
                new_cta,
                flight["provisional_delay_minutes"] - old_prov,
            )


def recompute_ledgers(tmi):
    """Rebuild flight_count / attributed_delay_minutes per operator from the
    flights currently holding slots or virtual CTAs in this program."""
    by_operator = {}
    for flight in program_flights(tmi["id"]):
        by_operator.setdefault(flight["operator_id"], []).append(flight)
    ledgers = [l for l in DB["ledgers"].values() if l["tmi_id"] == tmi["id"]]
    for ledger in ledgers:
        flights = by_operator.pop(ledger["operator_id"], [])
        flight_count = len(flights)
        attributed = sum(f["provisional_delay_minutes"] for f in flights)
        if (
            ledger["flight_count"] != flight_count
            or ledger["attributed_delay_minutes"] != attributed
        ):
            ledger["flight_count"] = flight_count
            ledger["attributed_delay_minutes"] = attributed
            touch(ledger)
    for operator_id, flights in by_operator.items():
        ledger = ensure_ledger(operator_id, tmi["id"])
        ledger["flight_count"] = len(flights)
        ledger["attributed_delay_minutes"] = sum(
            f["provisional_delay_minutes"] for f in flights
        )


def activate_allocation(tmi):
    """INITIAL mode: generate the slot grid and run ration-by-schedule."""
    interval, slot_count, reserved = _grid_geometry(tmi)
    carrier_slots = []
    for k in range(slot_count):
        slot_time = tmi["program_start"] + timedelta(seconds=k * interval)
        is_reserved = k >= slot_count - reserved
        row = create_entity(
            "slots",
            {
                "tmi_id": tmi["id"],
                "slot_index": k,
                "slot_time": slot_time,
                "is_ga_reserved": is_reserved,
                "assigned_flight_id": None,
                "original_flight_id": None,
                "status": "OPEN",
            },
        )
        if not is_reserved:
            carrier_slots.append(row)
    _assign_common(tmi, carrier_slots, eligible_flights(tmi), "INITIAL_ASSIGNMENT", None)
    recompute_ledgers(tmi)
    recompute_fair_shares(tmi["id"])


def reapply_allocation(tmi, revision):
    """REAPPLY mode: apply the pending revision, keep GA-accommodated slots,
    tear down and rebuild everything else over the new rate/window."""
    if revision["new_controlled_rate"] is not None:
        tmi["controlled_rate"] = revision["new_controlled_rate"]
    if revision["new_program_end"] is not None:
        tmi["program_end"] = revision["new_program_end"]
    revision["applied"] = True
    revision["applied_at"] = get_clock()

    if tmi["tmi_type"] != "GROUND_DELAY_PROGRAM":
        # Slot machinery is GDP-only (PRD 3.4): for GROUND_STOP, REROUTE and
        # AIRSPACE_FLOW_PROGRAM the revision's new field values applied above
        # are the whole of the apply step — there are no slots to tear down or
        # rebuild, and _grid_geometry would divide by the stored rate of 0.
        return

    ga_ids = {
        r["accommodated_flight_id"]
        for r in DB["ga_requests"].values()
        if r["accommodated_flight_id"]
    }
    old_slots = slots_of(tmi["id"])
    pinned = {}  # flight_id -> slot row kept as-is
    for slot in old_slots:
        if slot["status"] == "ASSIGNED" and slot["assigned_flight_id"] in ga_ids:
            pinned[slot["assigned_flight_id"]] = slot

    # Snapshot pre-teardown flight state for change detection.
    old_states = {}
    for flight in DB["flights"].values():
        if (
            flight.get("_tmi_id") == tmi["id"]
            and flight["controlled_arrival"] is not None
            and flight["id"] not in pinned
        ):
            old_states[flight["id"]] = (
                flight["controlled_arrival"],
                flight["control_status"] == "SLOTTED",
                flight["is_overflow"],
                flight["provisional_delay_minutes"],
            )

    # Tear down non-pinned flights and slots.
    for flight_id in old_states:
        flight = DB["flights"][flight_id]
        flight["controlled_arrival"] = None
        flight["control_status"] = "UNCONTROLLED"
        flight["is_overflow"] = False
        flight["provisional_delay_minutes"] = 0
        flight["_tmi_id"] = None
    for slot in old_slots:
        if not (slot["status"] == "ASSIGNED" and slot["assigned_flight_id"] in pinned):
            del DB["slots"][slot["id"]]

    # Rebuild the grid over the new rate/window; a pinned GA row coincident
    # with a grid instant adopts that grid position (its CTA never changes).
    interval, slot_count, reserved = _grid_geometry(tmi)
    pinned_by_time = {slot["slot_time"]: slot for slot in pinned.values()}
    carrier_slots = []
    for k in range(slot_count):
        slot_time = tmi["program_start"] + timedelta(seconds=k * interval)
        is_reserved = k >= slot_count - reserved
        kept = pinned_by_time.get(slot_time)
        if kept is not None:
            if kept["slot_index"] != k or kept["is_ga_reserved"] != is_reserved:
                kept["slot_index"] = k
                kept["is_ga_reserved"] = is_reserved
                touch(kept)
        else:
            row = create_entity(
                "slots",
                {
                    "tmi_id": tmi["id"],
                    "slot_index": k,
                    "slot_time": slot_time,
                    "is_ga_reserved": is_reserved,
                    "assigned_flight_id": None,
                    "original_flight_id": None,
                    "status": "OPEN",
                },
            )
            if not is_reserved:
                carrier_slots.append(row)

    _assign_common(
        tmi, carrier_slots, eligible_flights(tmi), "REVISION_MOVE", old_states
    )

    # Flights that were in the program but fell out of the re-snapshotted
    # eligible set keep their reverted state; journal the removal.
    for flight_id, old in old_states.items():
        flight = DB["flights"][flight_id]
        if flight.get("_tmi_id") != tmi["id"] or flight["controlled_arrival"] is None:
            old_cta, _, _, old_prov = old
            write_transaction(
                tmi["id"],
                None,
                flight_id,
                flight["operator_id"],
                "REVISION_MOVE",
                old_cta,
                None,
                -old_prov,
            )
            touch(flight)

    recompute_ledgers(tmi)
    recompute_fair_shares(tmi["id"])

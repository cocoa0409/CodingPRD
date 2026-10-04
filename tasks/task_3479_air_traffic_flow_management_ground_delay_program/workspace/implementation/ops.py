"""In-program operations: CDM substitution, compression, GA accommodation.

- Substitution swaps the two flights' CTAs inside one ACTIVE GDP, journals two
  SUBSTITUTION_SWAP transactions, and conserves the assigned-slot multiset.
- Compression (calculations.compression_reallocation) runs the pinned
  evaluation order: snapshot -> released pool -> GA promotion first -> carrier
  waterfall passes -> unclaimed RELEASED slots return to OPEN.
- accommodate() is the shared GA cascade used by adjudication and by
  compression promotion: create the GA flight, assign the slot, journal
  GA_ASSIGNMENT, reconcile the ledger.
"""

from constants import COMPRESSION_MAX_PASSES, GA_MIN_RESERVED
from ledger import (
    ensure_ledger,
    recompute_fair_shares,
    recompute_provisional,
    write_transaction,
)
from storage import DB, create_entity, create_record, get_clock, touch


def ga_flight_ids():
    return {
        r["accommodated_flight_id"]
        for r in DB["ga_requests"].values()
        if r["accommodated_flight_id"]
    }


def assigned_slot_of(tmi_id, flight_id):
    for slot in DB["slots"].values():
        if (
            slot["tmi_id"] == tmi_id
            and slot["status"] == "ASSIGNED"
            and slot["assigned_flight_id"] == flight_id
        ):
            return slot
    return None


def accommodated_count(tmi_id):
    """Reserved slots currently ASSIGNED to GA-created flights (a cancelled GA
    flight releases its slot and thereby frees quota headroom)."""
    ga_ids = ga_flight_ids()
    return sum(
        1
        for slot in DB["slots"].values()
        if slot["tmi_id"] == tmi_id
        and slot["is_ga_reserved"]
        and slot["status"] == "ASSIGNED"
        and slot["assigned_flight_id"] in ga_ids
    )


def reserved_slot_total(tmi):
    return tmi.get("_reserved_slots", GA_MIN_RESERVED)


def earliest_reserved_open_slot(tmi_id, window_start, window_end):
    """Earliest OPEN is_ga_reserved slot whose slot_time lies within the
    request window (half-open per PRD 2.9: start included, end excluded)."""
    candidates = [
        s
        for s in DB["slots"].values()
        if s["tmi_id"] == tmi_id
        and s["is_ga_reserved"]
        and s["status"] == "OPEN"
        and window_start <= s["slot_time"] < window_end
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda s: (s["slot_time"], s["slot_index"]))
    return candidates[0]


def accommodate(request, slot):
    """Full accommodation cascade (PRD 3.7): create the GA flight, assign the
    slot, journal GA_ASSIGNMENT, create/update the operator ledger, mark the
    request ACCOMMODATED. Caller recomputes fair shares."""
    tmi = DB["tmis"][request["tmi_id"]]
    clock = get_clock()
    flight = create_entity(
        "flights",
        {
            "operator_id": request["operator_id"],
            "designator": "GA-" + request["id"][:8],
            "origin": "GA",
            "arrival_facility_id": tmi["facility_id"],
            "scheduled_arrival": request["requested_window_start"],
            "estimated_arrival": request["requested_window_start"],
            "controlled_arrival": slot["slot_time"],
            "last_eta_reported_at": clock,
            "ops_status": "SCHEDULED",
            "control_status": "SLOTTED",
            "is_overflow": False,
            "provisional_delay_minutes": 0,
            "final_delay_minutes": None,
            "_tmi_id": tmi["id"],
        },
    )
    recompute_provisional(flight)
    slot["status"] = "ASSIGNED"
    slot["assigned_flight_id"] = flight["id"]
    if slot["original_flight_id"] is None:
        slot["original_flight_id"] = flight["id"]
    touch(slot)
    write_transaction(
        tmi["id"],
        slot["id"],
        flight["id"],
        flight["operator_id"],
        "GA_ASSIGNMENT",
        None,
        slot["slot_time"],
        flight["provisional_delay_minutes"],
    )
    ledger = ensure_ledger(flight["operator_id"], tmi["id"])
    ledger["flight_count"] += 1
    ledger["attributed_delay_minutes"] += flight["provisional_delay_minutes"]
    touch(ledger)
    request["status"] = "ACCOMMODATED"
    request["accommodated_flight_id"] = flight["id"]
    request["accommodated_slot_time"] = slot["slot_time"]
    touch(request)
    return flight


# --- Substitution --------------------------------------------------------------
def execute_substitution(tmi, flight1, flight2, note):
    """Swap the two flights' CTAs (PRD 3.5). Returns the transaction recorded
    for flight_id_1. Both flights are owned by the acting operator (checked by
    the route) so a single ledger absorbs both deltas."""
    slot1 = assigned_slot_of(tmi["id"], flight1["id"])
    slot2 = assigned_slot_of(tmi["id"], flight2["id"])
    time1, time2 = slot1["slot_time"], slot2["slot_time"]

    old_prov1 = flight1["provisional_delay_minutes"]
    old_prov2 = flight2["provisional_delay_minutes"]

    slot1["assigned_flight_id"] = flight2["id"]
    slot2["assigned_flight_id"] = flight1["id"]
    touch(slot1)
    touch(slot2)

    flight1["controlled_arrival"] = time2
    flight2["controlled_arrival"] = time1
    recompute_provisional(flight1)
    recompute_provisional(flight2)
    touch(flight1)
    touch(flight2)

    delta1 = flight1["provisional_delay_minutes"] - old_prov1
    delta2 = flight2["provisional_delay_minutes"] - old_prov2

    txn1 = write_transaction(
        tmi["id"], slot2["id"], flight1["id"], flight1["operator_id"],
        "SUBSTITUTION_SWAP", time1, time2, delta1, note,
    )
    write_transaction(
        tmi["id"], slot1["id"], flight2["id"], flight2["operator_id"],
        "SUBSTITUTION_SWAP", time2, time1, delta2, note,
    )

    ledger = ensure_ledger(flight1["operator_id"], tmi["id"])
    ledger["attributed_delay_minutes"] += delta1 + delta2
    touch(ledger)
    recompute_fair_shares(tmi["id"])
    return txn1


# --- Compression ---------------------------------------------------------------
def _compression_candidates(tmi_id):
    """Flights holding ASSIGNED slots with ops_status != CANCELLED, in
    ration-by-schedule order."""
    pairs = []
    for slot in DB["slots"].values():
        if slot["tmi_id"] == tmi_id and slot["status"] == "ASSIGNED":
            flight = DB["flights"].get(slot["assigned_flight_id"])
            if flight is not None and flight["ops_status"] != "CANCELLED":
                pairs.append((flight, slot))
    pairs.sort(
        key=lambda p: (
            p[0]["scheduled_arrival"],
            p[0]["created_at"],
            p[0]["_seq"],
        )
    )
    return pairs


def run_compression(tmi):
    """calculations.compression_reallocation with the pinned evaluation order."""
    tmi_id = tmi["id"]
    pool = sorted(
        (s for s in DB["slots"].values() if s["tmi_id"] == tmi_id and s["status"] == "RELEASED"),
        key=lambda s: (s["slot_time"], s["slot_index"]),
    )
    released_slot_count = len(pool)

    # (2a) GA promotion first: WAITLISTED requests ranked HIGH_PRIORITY before
    # STANDARD, then created_at ASC, consume in-window reserved pool slots
    # while the quota has headroom.
    waitlisted = [
        r
        for r in DB["ga_requests"].values()
        if r["tmi_id"] == tmi_id and r["status"] == "WAITLISTED"
    ]
    waitlisted.sort(
        key=lambda r: (
            0 if r["priority_class"] == "HIGH_PRIORITY" else 1,
            r["created_at"],
            r["_seq"],
        )
    )
    promoted = []
    for request in waitlisted:
        if accommodated_count(tmi_id) >= reserved_slot_total(tmi):
            break
        slot = next(
            (
                s
                for s in pool
                if s["is_ga_reserved"]
                and request["requested_window_start"]
                <= s["slot_time"]
                < request["requested_window_end"]
            ),
            None,
        )
        if slot is None:
            continue
        pool.remove(slot)
        accommodate(request, slot)
        promoted.append(request["id"])

    # Reserved-flagged pool slots are available to carrier candidates only
    # when no WAITLISTED GA request exists for this TMI at all.
    waitlist_exists = any(
        r["tmi_id"] == tmi_id and r["status"] == "WAITLISTED"
        for r in DB["ga_requests"].values()
    )

    moves_made = 0
    passes_executed = 0
    while True:
        pass_moves = 0
        for flight, current in _compression_candidates(tmi_id):
            target = next(
                (
                    s
                    for s in pool
                    if s["slot_time"] < current["slot_time"]
                    and (not s["is_ga_reserved"] or not waitlist_exists)
                ),
                None,
            )
            if target is None:
                continue
            pool.remove(target)
            old_time = current["slot_time"]
            old_prov = flight["provisional_delay_minutes"]

            target["status"] = "ASSIGNED"
            target["assigned_flight_id"] = flight["id"]
            if target["original_flight_id"] is None:
                target["original_flight_id"] = flight["id"]
            touch(target)

            current["status"] = "OPEN"
            current["assigned_flight_id"] = None
            touch(current)
            # The freed slot re-enters the pool, kept in slot_time order, and
            # is reusable by later candidates in the same pass.
            pool.append(current)
            pool.sort(key=lambda s: (s["slot_time"], s["slot_index"]))

            flight["controlled_arrival"] = target["slot_time"]
            recompute_provisional(flight)
            touch(flight)
            delta = flight["provisional_delay_minutes"] - old_prov
            write_transaction(
                tmi_id,
                target["id"],
                flight["id"],
                flight["operator_id"],
                "COMPRESSION_MOVE",
                old_time,
                target["slot_time"],
                delta,
            )
            ledger = ensure_ledger(flight["operator_id"], tmi_id)
            ledger["attributed_delay_minutes"] += delta
            touch(ledger)
            pass_moves += 1
            moves_made += 1
        passes_executed += 1
        if pass_moves == 0 or passes_executed >= COMPRESSION_MAX_PASSES:
            break

    # (6) Unclaimed RELEASED slots return to OPEN; count the resulting OPENs.
    for slot in pool:
        if slot["status"] == "RELEASED":
            slot["status"] = "OPEN"
            touch(slot)
    remaining_open = sum(
        1
        for s in DB["slots"].values()
        if s["tmi_id"] == tmi_id and s["status"] == "OPEN"
    )

    run = create_record(
        "compression_runs",
        {
            "tmi_id": tmi_id,
            "released_slot_count": released_slot_count,
            "moves_made": moves_made,
            "passes_executed": passes_executed,
            "promoted_ga_request_ids": list(promoted),
            "remaining_open_slots": remaining_open,
        },
    )
    recompute_fair_shares(tmi_id)
    return run

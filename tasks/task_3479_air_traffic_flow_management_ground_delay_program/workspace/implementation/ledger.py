"""Slot transaction log, operator delay ledgers, and delay computation.

Implements calculations.provisional_vs_final_delay (PROVISIONAL side) and
calculations.operator_delay_distribution (largest-remainder fair share with
the pinned floor-then-top-up rounding order).
"""

from datetime import datetime, timezone
from fractions import Fraction

from storage import DB, create_entity, create_record, touch


def write_transaction(tmi_id, slot_id, flight_id, operator_id, transaction_type,
                      from_slot_time, to_slot_time, delay_delta_minutes, note=None):
    """Append to the program's slot transaction log (denormalized references)."""
    return create_record(
        "transactions",
        {
            "tmi_id": tmi_id,
            "slot_id": slot_id,
            "flight_id": flight_id,
            "operator_id": operator_id,
            "transaction_type": transaction_type,
            "from_slot_time": from_slot_time,
            "to_slot_time": to_slot_time,
            "delay_delta_minutes": delay_delta_minutes,
            "note": note,
        },
    )


def floor_minutes(delta):
    """Whole-minute floor of a timedelta (delays floor after dividing the
    second-level difference by 60, PRD 2.8). Python's // already floors."""
    return int(delta.total_seconds()) // 60


def delay_minutes_between(later, earlier):
    """max(0, floor((later - earlier) / 60s)) — the provisional-delay shape."""
    return max(0, floor_minutes(later - earlier))


def recompute_provisional(flight):
    """PROVISIONAL variant: max(0, floor((controlled - scheduled)/60s));
    0 while control_status == UNCONTROLLED (scaffold flight fields)."""
    if flight["control_status"] != "SLOTTED" or flight["controlled_arrival"] is None:
        flight["provisional_delay_minutes"] = 0
    else:
        flight["provisional_delay_minutes"] = delay_minutes_between(
            flight["controlled_arrival"], flight["scheduled_arrival"]
        )


# --- Ledgers -------------------------------------------------------------------
def find_ledger(operator_id, tmi_id):
    for ledger in DB["ledgers"].values():
        if ledger["operator_id"] == operator_id and ledger["tmi_id"] == tmi_id:
            return ledger
    return None


def ensure_ledger(operator_id, tmi_id):
    """Fetch or create the per-operator per-program ledger (created with zeroed
    counters at version 1)."""
    ledger = find_ledger(operator_id, tmi_id)
    if ledger is None:
        ledger = create_entity(
            "ledgers",
            {
                "operator_id": operator_id,
                "tmi_id": tmi_id,
                "flight_count": 0,
                "attributed_delay_minutes": 0,
                "reversed_delay_minutes": 0,
                "fair_share_minutes": 0,
                "deviation_minutes": 0,
            },
        )
    return ledger


def program_flights(tmi_id):
    """Flights currently holding a slot or a virtual CTA in this program."""
    return [
        f
        for f in DB["flights"].values()
        if f.get("_tmi_id") == tmi_id and f["controlled_arrival"] is not None
    ]


def _earliest_program_scheduled(operator_id, tmi_id):
    """Tie-break key: the operator's earliest in-program flight's
    scheduled_arrival (PRD 3.9); None when the operator has none left."""
    arrivals = [
        f["scheduled_arrival"]
        for f in program_flights(tmi_id)
        if f["operator_id"] == operator_id
    ]
    return min(arrivals) if arrivals else None


def recompute_fair_shares(tmi_id):
    """calculations.operator_delay_distribution: floor each raw share, then
    distribute the leftover one minute at a time by fractional remainder DESC,
    ties broken toward the operator whose earliest in-program flight has the
    earliest scheduled_arrival, then operator created_at ASC."""
    ledgers = [l for l in DB["ledgers"].values() if l["tmi_id"] == tmi_id]
    if not ledgers:
        return
    total_delay = sum(l["attributed_delay_minutes"] for l in ledgers)
    total_flights = sum(l["flight_count"] for l in ledgers)
    if total_flights <= 0:
        for ledger in ledgers:
            changed = (
                ledger["fair_share_minutes"] != 0
                or ledger["deviation_minutes"] != ledger["attributed_delay_minutes"]
            )
            ledger["fair_share_minutes"] = 0
            ledger["deviation_minutes"] = ledger["attributed_delay_minutes"]
            if changed:
                touch(ledger)
        return
    rows = []
    for ledger in ledgers:
        raw = Fraction(total_delay * ledger["flight_count"], total_flights)
        base = raw.numerator // raw.denominator
        rows.append(
            {
                "ledger": ledger,
                "base": base,
                "remainder": raw - base,
                "earliest": _earliest_program_scheduled(ledger["operator_id"], tmi_id),
            }
        )
    leftover = total_delay - sum(r["base"] for r in rows)
    # Largest remainder first; tie-break earliest in-program scheduled_arrival
    # (operators with no remaining in-program flight sort last), then operator
    # created_at ASC.
    far_future = datetime.max.replace(tzinfo=timezone.utc)

    def tie_key(row):
        earliest = row["earliest"] if row["earliest"] is not None else far_future
        operator = DB["operators"].get(row["ledger"]["operator_id"])
        op_created = operator["created_at"] if operator else far_future
        op_seq = operator["_seq"] if operator else 0
        return (-row["remainder"], earliest, op_created, op_seq)

    rows.sort(key=tie_key)
    # Fraction negation for the sort key: sort ascending on -remainder.
    for row in rows[: max(0, leftover)]:
        row["base"] += 1
    for row in rows:
        ledger = row["ledger"]
        new_fair = row["base"]
        new_dev = ledger["attributed_delay_minutes"] - new_fair
        changed = (
            ledger["fair_share_minutes"] != new_fair
            or ledger["deviation_minutes"] != new_dev
        )
        ledger["fair_share_minutes"] = new_fair
        ledger["deviation_minutes"] = new_dev
        if changed:
            touch(ledger)

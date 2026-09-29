"""The sponsor ledger as the single accounting record (PRD section 2.9).

Sponsor money is never adjusted by direct assignment: every movement is an
append, and a program's balances are derived from those appends.
"""
import db
from services import lookup

RESERVATION = "RESERVATION"
RESERVATION_RELEASE = "RESERVATION_RELEASE"
COMMITMENT = "COMMITMENT"
COMMITMENT_REVERSAL = "COMMITMENT_REVERSAL"
FUNDING_ADJUSTMENT = "FUNDING_ADJUSTMENT"

RESERVED_TYPES = (RESERVATION, RESERVATION_RELEASE)
COMMITTED_TYPES = (COMMITMENT, COMMITMENT_REVERSAL)

MEMO_KIT_ISSUANCE = "kit issuance"
MEMO_KIT_SUPERSEDE = "kit supersede"
MEMO_KIT_VOID = "kit void"
MEMO_ENROLLMENT_PAUSED = "enrollment paused"
MEMO_ENROLLMENT_TERMINATED = "enrollment terminated"
MEMO_SHIPMENT_LOST = "shipment lost"
MEMO_CERTIFICATE_SETTLEMENT = "certificate settlement"
MEMO_CERTIFICATE_VOID = "certificate void"


def entries_of(program_id):
    """This program's ledger entries in sequence_no ascending order."""
    rows = [
        e
        for e in db.coll("ledger_entries").values()
        if e["sponsorship_program_id"] == program_id
    ]
    rows.sort(key=lambda e: e["sequence_no"])
    return rows


def next_sequence_no(program_id):
    highest = 0
    for entry in db.coll("ledger_entries").values():
        if entry["sponsorship_program_id"] == program_id:
            if entry["sequence_no"] > highest:
                highest = entry["sequence_no"]
    return highest + 1


def _sums(program_id):
    reserved = 0
    committed = 0
    for entry in db.coll("ledger_entries").values():
        if entry["sponsorship_program_id"] != program_id:
            continue
        if entry["entry_type"] in RESERVED_TYPES:
            reserved += entry["amount_cents"]
        elif entry["entry_type"] in COMMITTED_TYPES:
            committed += entry["amount_cents"]
    return reserved, committed


def append_entry(program, entry_type, amount_cents, kit_id, memo):
    """Append one immutable ledger entry and snapshot the after-balances."""
    entry = db.create_row(
        "ledger_entries",
        {
            "sponsorship_program_id": program["id"],
            "kit_id": kit_id,
            "entry_type": entry_type,
            "amount_cents": amount_cents,
            "sequence_no": next_sequence_no(program["id"]),
            "reserved_after_cents": 0,
            "committed_after_cents": 0,
            "available_after_cents": 0,
            "memo": memo,
        },
        common=False,
    )
    reserved, committed = _sums(program["id"])
    entry["reserved_after_cents"] = reserved
    entry["committed_after_cents"] = committed
    entry["available_after_cents"] = program["funding_ceiling_cents"] - reserved - committed
    return entry


def program_kits(program_id):
    kits = []
    for enrollment in db.ordered(
        "enrollments", lambda e: e["sponsorship_program_id"] == program_id
    ):
        kits.extend(lookup.enrollment_kits(enrollment["id"]))
    return kits


def recompute_program(program, count_flip=True):
    """Recompute the balance triple, the derived counters and the status.

    A crossing of zero in either direction is a real transition and increments
    the program's version (PRD section 2.9).
    """
    reserved, committed = _sums(program["id"])
    program["reserved_cents"] = reserved
    program["committed_cents"] = committed
    program["available_cents"] = program["funding_ceiling_cents"] - reserved - committed

    kits = program_kits(program["id"])
    kit_ids = set(k["id"] for k in kits)
    program["kits_issued_count"] = len([k for k in kits if k["status"] != "VOIDED"])

    settled = [
        c
        for c in db.coll("certificates").values()
        if c["status"] == "ISSUED" and c["kit_id"] in kit_ids
    ]
    program["kits_settled_count"] = len(settled)
    program["final_total_cents"] = sum(c["final_kit_cost_cents"] for c in settled)
    settled_kit_ids = set(c["kit_id"] for c in settled)
    program["provisional_total_cents"] = sum(
        k["provisional_cost_cents"] for k in kits if k["id"] in settled_kit_ids
    )

    previous = program["status"]
    program["status"] = "ACTIVE" if program["available_cents"] > 0 else "EXHAUSTED"
    db.touch(program)
    if count_flip and program["status"] != previous:
        program["version"] = program["version"] + 1
    return program


def recompute_balances(program):
    """Refresh only the derived balance triple (no status evaluation).

    Used mid-request when a cascade hop moves money but the ACTIVE/EXHAUSTED
    evaluation belongs to a single later recomputation step.
    """
    reserved, committed = _sums(program["id"])
    program["reserved_cents"] = reserved
    program["committed_cents"] = committed
    program["available_cents"] = program["funding_ceiling_cents"] - reserved - committed
    return program


def release_reservation(program, kit, memo):
    """Append the RESERVATION_RELEASE that unwinds a kit's provisional cost."""
    return append_entry(
        program,
        RESERVATION_RELEASE,
        -kit["provisional_cost_cents"],
        kit["id"],
        memo,
    )

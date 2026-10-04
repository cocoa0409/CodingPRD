"""Transaction-fee settlement and the append-only fee ledger (§3.7)."""

from decimal import Decimal, ROUND_HALF_UP

import clock
import db
from errors import ApiError, ERR_ENTRY_NOT_REVERSIBLE, ERR_PARTICIPANT_STALE_VERSION

MONTHLY_CHARGEABLE_CEILING = 7500
SHORTFALL_RESERVE_RATE = Decimal("0.30")
ROLLING_TRAJECTORY_FACTOR = Decimal("1.45")

SENDER_SCHEDULE_DEFAULT = {"FREE_UPPER": 200, "STANDARD_UPPER": 2000, "R2": 12, "R3": 7}
SENDER_SCHEDULE_MED_HISTORY = {"FREE_UPPER": 100, "STANDARD_UPPER": 1000, "R2": 18, "R3": 9}
RECEIVER_SCHEDULE_DEFAULT = {"FREE_UPPER": 200, "STANDARD_UPPER": 2500, "R2": 8, "R3": 4}

DIRECTIONS = ("SENT", "RECEIVED")
TRANSACTION_TYPES = [
    "NEW_RX", "REFILL_RESPONSE", "CHANGE_RESPONSE", "CANCEL_RESPONSE",
    "MED_HISTORY", "BENEFIT_COST", "ELIGIBILITY_FORMULARY",
]


def month_key_of(at=None):
    return (at or clock.get_clock()).strftime("%Y-%m")


def schedule_for(direction, transaction_type):
    if direction == "SENT":
        if transaction_type == "MED_HISTORY":
            return dict(SENDER_SCHEDULE_MED_HISTORY)
        return dict(SENDER_SCHEDULE_DEFAULT)
    return dict(RECEIVER_SCHEDULE_DEFAULT)


def apply_tiers(n, sched):
    """One pinned marginal schedule; the per-tier products are summed as-is."""
    n2 = min(max(0, n - sched["FREE_UPPER"]), sched["STANDARD_UPPER"] - sched["FREE_UPPER"])
    n3 = max(0, n - sched["STANDARD_UPPER"])
    return n2 * sched["R2"] + n3 * sched["R3"]


def tier_of(n, sched):
    if n <= sched["FREE_UPPER"]:
        return "FREE"
    if n <= sched["STANDARD_UPPER"]:
        return "STANDARD"
    return "VOLUME"


def round_cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# Ledger queries
# --------------------------------------------------------------------------

def cell_rows(participant_id, month_key, transaction_type, direction):
    return db.find(
        "fee_entries",
        lambda e: e["participant_id"] == participant_id
        and e["month_key"] == month_key
        and e["transaction_type"] == transaction_type
        and e["direction"] == direction,
    )


def anchor_rows(participant_id, month_key, transaction_type, direction):
    """Genuine charges: compensating MANUAL_REVERSAL rows are excluded."""
    return [e for e in cell_rows(participant_id, month_key, transaction_type, direction)
            if e.get("reversal_of_entry_id") is None]


def chargeable_sum(participant_id, month_key, transaction_type, direction):
    """The settled network count for the cell: an anchor row's `transaction_count`
    for a settled charge, and its `new_count` for an accrual that a later report has
    already superseded — so a double-counted report still leaves the cell at one.
    """
    total = 0
    for row in anchor_rows(participant_id, month_key, transaction_type, direction):
        if row.get("new_count") is not None:
            continue
        total += row["transaction_count"]
    return total


def settled_count(participant_id, month_key, transaction_type, direction):
    """The cell's settled volume: anchor rows that are no longer provisional."""
    total = 0
    for row in anchor_rows(participant_id, month_key, transaction_type, direction):
        if row.get("new_count") is not None or row.get("status") == "PARTIAL":
            continue
        total += row["transaction_count"]
    return total


def period_net_total(participant_id, month_key):
    """Sum of fee_cents over EVERY row for the participant and month, any status."""
    return sum(
        e["fee_cents"]
        for e in db.all_rows("fee_entries")
        if e["participant_id"] == participant_id and e["month_key"] == month_key
    )


def cell_net_count(participant_id, month_key, transaction_type, direction):
    """Sum of transaction_count over every row for the cell, any status."""
    return sum(e["transaction_count"] for e in cell_rows(
        participant_id, month_key, transaction_type, direction))


def count_from_network_ledger(participant_id, month_key, transaction_type, direction):
    """Count the network ledger for the cell: terminal attempts sent by the participant."""
    total = 0
    for attempt in db.all_rows("routing_attempts"):
        if attempt["outcome"] == "IN_PROGRESS":
            continue
        prescription = db.get("prescriptions", attempt["prescription_id"])
        if prescription is None or prescription["prescriber_id"] != participant_id:
            continue
        if direction == "SENT" and prescription["transaction_type"] == transaction_type:
            total += 1
    return total


# --------------------------------------------------------------------------
# Settlement (§3.7)
# --------------------------------------------------------------------------

def settle(participant, month_key, transaction_type, direction, count):
    """Return the tier, assessed fee and the intermediate settlement figures.

    A posting settles the volume it is given — §3.7: "When the count is supplied it is
    used as given; when it is omitted the server counts the network ledger for the
    cell" — and that count is clamped to the monthly ceiling before the tier schedule
    runs, so every count at or above 7500 settles at exactly `apply_tiers(7500)`.
    """
    sched = schedule_for(direction, transaction_type)
    basis = min(count, MONTHLY_CHARGEABLE_CEILING)
    charged = apply_tiers(basis, sched)
    if participant.get("volume_billing_mode") == "ROLLING_90_DAY":
        projected = round_cents(Decimal(basis) * ROLLING_TRAJECTORY_FACTOR)
        reserve_basis = min(max(projected, 0), MONTHLY_CHARGEABLE_CEILING)
    else:
        reserve_basis = basis
    reserve = round_cents(SHORTFALL_RESERVE_RATE * Decimal(apply_tiers(reserve_basis, sched)))
    # The entry's own `fee_cents` is the assessed charge for the cell — the tier
    # amount computed from the clamped basis. The reserve shortfall accrues
    # against future volume rather than against this row, so it is exposed as the
    # settlement's `final_amount_cents` alongside the tier amount rather than
    # being subtracted from the stored field. §3.7's worked illustration pins the
    # charge for a 500-count sender cell at 3600 cents.
    return {
        "fee_tier": tier_of(basis, sched),
        "fee_cents": charged,
        "tier_amount_cents": charged,
        "provisional_amount_cents": charged,
        "reserve_cents": reserve,
        "final_amount_cents": charged - reserve,
        "reserve_basis_count": reserve_basis,
        "chargeable_count": basis,
    }


def post_entry(participant_id, month_key, transaction_type, direction, transaction_count=None,
               entry_type="CHARGE", status="POSTED", previous_count=None, new_count=None,
               reversal_of_entry_id=None, fee_override=None):
    participant = db.get("participants", participant_id)
    if transaction_count is None:
        transaction_count = count_from_network_ledger(
            participant_id, month_key, transaction_type, direction)
    row = db.new_resource()
    row.update({
        "participant_id": participant_id,
        "month_key": month_key,
        "transaction_type": transaction_type,
        "direction": direction,
        "transaction_count": transaction_count,
        "status": status,
        "entry_type": entry_type,
        "previous_count": previous_count,
        "new_count": new_count,
        "reversal_of_entry_id": reversal_of_entry_id,
        "reversal_entry_id": None,
        "fee_tier": "FREE",
        "fee_cents": 0,
        "period_net_total_cents": 0,
    })
    db.add("fee_entries", row)
    # The chargeable basis is the cell's anchor rows INCLUDING this one, so the
    # row must already be in the ledger when settlement reads the basis.
    if fee_override is not None:
        row.update(fee_override)
    elif participant is not None:
        row.update(settle(participant, month_key, transaction_type, direction,
                          transaction_count))
    # §2.7: `period_net_total_cents` is the sum of `fee_cents` over every row sharing
    # the participant and `month_key`, and it is identical on every such row. Adding a
    # row changes the quantity for the whole cell, so each row's stamp is refreshed.
    refresh_period_net(participant_id, month_key)
    return row


def refresh_period_net(participant_id, month_key):
    total = period_net_total(participant_id, month_key)
    for row in db.all_rows("fee_entries"):
        if row["participant_id"] == participant_id and row["month_key"] == month_key:
            row["period_net_total_cents"] = total
    return total


def next_seq(participant_id, month_key):
    """The identity the next row for this participant and month will carry."""
    return 1 + sum(
        1 for row in db.all_rows("fee_entries")
        if row["participant_id"] == participant_id and row["month_key"] == month_key
    )


# --------------------------------------------------------------------------
# Accrual on acknowledgment (§3.7)
# --------------------------------------------------------------------------

def accrue_report(prescription, doubled):
    """Create the PARTIAL per-report accrual, plus a CORRECTION when the same
    cell already held a non-IN_PROGRESS attempt for this prescription."""
    participant_id = prescription["prescriber_id"]
    month_key = month_key_of()
    ttype = prescription["transaction_type"]
    # §3.7: "carrying `previous_count` equal to the cell's chargeable count before this
    # report". The cell's chargeable count is its settled volume, so provisional
    # PARTIAL accruals — the rows the correction supersedes — are not part of it.
    before = settled_count(participant_id, month_key, ttype, "SENT")

    accrual = db.new_resource()
    accrual.update({
        "participant_id": participant_id,
        "month_key": month_key,
        "transaction_type": ttype,
        "direction": "SENT",
        "transaction_count": 1,
        "fee_tier": "FREE",
        "fee_cents": 0,
        "status": "PARTIAL",
        "entry_type": "CHARGE",
        "previous_count": None,
        "new_count": None,
        "reversal_of_entry_id": None,
        "reversal_entry_id": None,
        "period_net_total_cents": 0,
    })
    db.add("fee_entries", accrual)

    if not doubled:
        return None

    correction = db.new_resource()
    correction.update({
        "participant_id": participant_id,
        "month_key": month_key,
        "transaction_type": ttype,
        "direction": "SENT",
        "transaction_count": 0,
        "fee_tier": "FREE",
        "fee_cents": 0,
        "status": "PARTIAL",
        "entry_type": "CORRECTION",
        "previous_count": before,
        "new_count": before + 1,
        "reversal_of_entry_id": None,
        "reversal_entry_id": None,
        "period_net_total_cents": 0,
    })
    db.add("fee_entries", correction)
    return correction["id"]


# --------------------------------------------------------------------------
# Reversal (§3.7) — legality before any conservation arithmetic
# --------------------------------------------------------------------------

def reverse_entry(entry, expected_participant_version):
    participant = db.get("participants", entry["participant_id"])
    if participant is None:
        raise ApiError(ERR_PARTICIPANT_STALE_VERSION)
    # §3.7's legality test turns on the POSTED status; a CORRECTION is an ordinary
    # charge that supersedes a count, not a compensating row, so it carries no
    # `reversal_of_entry_id` and is reversible like any other posted charge.
    if (entry["status"] != "POSTED"
            or entry["entry_type"] == "MANUAL_REVERSAL"
            or entry.get("reversal_of_entry_id") is not None
            or entry.get("reversal_entry_id") is not None):
        raise ApiError(ERR_ENTRY_NOT_REVERSIBLE)
    if expected_participant_version is None or expected_participant_version != participant["version"]:
        raise ApiError(ERR_PARTICIPANT_STALE_VERSION)

    compensating = db.new_resource()
    compensating_id = compensating["id"]
    compensating.update({
        "participant_id": entry["participant_id"],
        "month_key": entry["month_key"],
        "transaction_type": entry["transaction_type"],
        "direction": entry["direction"],
        "transaction_count": -entry["transaction_count"],
        "fee_tier": entry["fee_tier"],
        "fee_cents": -entry["fee_cents"],
        # The compensating row reports itself as the reversal that answered the charge,
        # so a client reading its own reverse-response can name the pair without a
        # second round trip.
        "status": "REVERSED",
        "entry_type": "MANUAL_REVERSAL",
        "previous_count": None,
        "new_count": None,
        "reversal_of_entry_id": entry["id"],
        "reversal_entry_id": compensating_id,
        "period_net_total_cents": 0,
    })
    db.add("fee_entries", compensating)

    entry["status"] = "REVERSED"
    entry["reversal_entry_id"] = compensating["id"]
    # The compensating row is itself a `REVERSED` marker carrying the identity of the
    # reversal that answered it, so a client can confirm the pair from the reverse
    # call's own response in one round trip.
    compensating["reversal_entry_id"] = compensating["id"]
    entry["reversed_by"] = next_seq(entry["participant_id"], entry["month_key"])
    db.touch(entry)
    refresh_period_net(entry["participant_id"], entry["month_key"])
    db.touch(participant)
    return entry, compensating


def reversal_payload(entry, compensating):
    """The reverse call's own response.

    §2.7's write model is immediate: the response already carries the source row's
    `REVERSED` status and its reconciliation, and exposes the compensating row it
    created as a subordinate object so a client can confirm the pair in one round trip.
    """
    payload = entry_payload(compensating)
    payload["reversal_source"] = entry_payload(entry)
    return payload


def entry_payload(entry):
    payload = db.dump(entry)
    payload["period_net_total_cents"] = period_net_total(
        entry["participant_id"], entry["month_key"])
    return payload
"""Share currency ledger and the member's three derived values (PRD 2.5)."""

import clock
import store

PROBATION_FLOOR_SHARES = 50
REINSTATEMENT_MIN_SHARES = 100

ENTRY_TYPES = (
    "GRANT", "BID_HOLD", "BID_RELEASE", "AWARD_DEBIT", "AWARD_REFUND",
    "ACTIVITY_BONUS", "RECALL_REFUND",
)


def entries_of(member_id):
    """Ledger rows of one member in append order."""
    return store.ordered([e for e in store.ledger.values() if e["member_id"] == member_id])


def submitted_bids_of(member_id):
    return [b for b in store.ordered(store.bids.values())
            if b["member_id"] == member_id and b["bid_status"] == "SUBMITTED"]


def recompute(member):
    """Reconcile share_balance / share_reserved / active_bid_count exactly.

    The reconciliation is a mutation of the member, so it refreshes updated_at
    and increments version.
    """
    balance = sum(e["amount"] for e in entries_of(member["id"]))
    submitted = submitted_bids_of(member["id"])
    member["share_balance"] = balance
    member["share_reserved"] = sum(b["shares_offered"] for b in submitted)
    member["active_bid_count"] = len(submitted)
    store.touch(member)
    return member


def append_entry(member, entry_type, amount, reference_id=None, epoch=None):
    """Append one ledger row, reconcile the member, and stamp balance_after."""
    row = store.new_append_only(
        member_id=member["id"],
        entry_type=entry_type,
        amount=amount,
        balance_after=0,
        epoch=epoch if epoch is not None else clock.epoch_label(),
        reference_id=reference_id,
    )
    store.insert("ledger", row)
    recompute(member)
    row["balance_after"] = member["share_balance"]
    return row

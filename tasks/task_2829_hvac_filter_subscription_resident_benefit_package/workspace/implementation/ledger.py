"""Append-only ledger and the derived property balance (PRD 2.11)."""
import clock
from errors import fail
from store import base_record, db


def post(sub, entry_type, amount_cents, period_start, period_end, memo,
         source_ref_id):
    """Ledger rows are append-only: never updated, never deleted. billed_party
    snapshots the subscription's billing_party at insert time."""
    rec = base_record(with_version=False)
    rec["subscription_id"] = sub["id"]
    rec["entry_type"] = entry_type
    rec["amount_cents"] = amount_cents
    rec["billed_party"] = sub["billing_party"]
    rec["period_start"] = period_start
    rec["period_end"] = period_end
    rec["source_ref_id"] = source_ref_id
    rec["memo"] = memo
    db.ledger[rec["id"]] = rec
    return rec


def post_one_off(sub, entry_type, amount_cents, memo, source_ref_id, on_date=None):
    day = clock.fmt_date(on_date or clock.today())
    return post(sub, entry_type, amount_cents, day, day, memo, source_ref_id)


def property_balance(property_id):
    total = 0
    for row in db.ledger.values():
        if row["billed_party"] != "PROPERTY_MANAGER":
            continue
        sub = db.subscriptions.get(row["subscription_id"])
        if sub is None or sub["property_id"] != property_id:
            continue
        total += row["amount_cents"]
    return total


def check_credit_ceiling(prop, billing_party, charge_cents):
    """PRD 2.11 / ladder rung 30: applies to property-manager-billed
    subscriptions at a PM_BILLED property, and must prove the ceiling absorbs
    the charge before anything commits."""
    if billing_party != "PROPERTY_MANAGER":
        return
    if prop["billing_mode"] != "PM_BILLED":
        return
    if property_balance(prop["id"]) + charge_cents > prop["credit_limit_cents"]:
        fail("ERR_PROPERTY_CREDIT_LIMIT_EXCEEDED")

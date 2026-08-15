"""Reserve ledger helpers and derived-field recomputation.

The ledger is append-only (PRD 2.8): entries are never edited or deleted.
Every entry insertion recomputes the owning reserve's totals, re-evaluates the
trend alert, and bumps the reserve's version/updated_at (PRD 2.5).
"""
from clock import CLOCK
from db import db, next_seq
from services.calc import alert_status_for
from util import new_id

PARTNER_OUTSTANDING_STATUSES = {"ISSUED", "APPROVED", "CONTESTED", "UPHELD", "REDUCED"}


def touch(entity):
    """A mutation refreshes updated_at and increments version (PRD 2.5)."""
    entity["updated_at"] = CLOCK.now()
    entity["version"] += 1


def reserve_for_home(home_id):
    for r in db["warranty_reserves"].values():
        if r["home_id"] == home_id:
            return r
    return None


def nonvoid_chargeback_for_work_order(work_order_id):
    for c in db["chargebacks"].values():
        if c["work_order_id"] == work_order_id and c["status"] != "VOID":
            return c
    return None


def recompute_reserve(reserve):
    entries = [e for e in db["reserve_entries"].values() if e["reserve_id"] == reserve["id"]]
    balance = sum(e["amount_cents"] for e in entries)
    reserve["balance_cents"] = balance
    reserve["accrued_to_date_cents"] = sum(
        e["amount_cents"] for e in entries if e["kind"] in ("ACCRUAL", "TRUE_UP"))
    reserve["drawn_to_date_cents"] = sum(
        -e["amount_cents"] for e in entries if e["kind"] == "DRAW")
    reserve["recovered_to_date_cents"] = sum(
        e["amount_cents"] for e in entries if e["kind"] == "RECOVERY")
    reserve["alert_status"] = alert_status_for(balance, reserve["expected_lifetime_accrual_cents"])


def post_entry(reserve, kind, amount_cents, month_index=None, work_order_ref=None,
               chargeback_ref=None, claim_ref=None, note=None):
    """Append a ledger line, recompute the reserve, bump the reserve once."""
    entry = {
        "id": new_id(),
        "reserve_id": reserve["id"],
        "kind": kind,
        "amount_cents": amount_cents,
        "month_index": month_index,
        "work_order_ref": work_order_ref,
        "chargeback_ref": chargeback_ref,
        "claim_ref": claim_ref,
        "note": note,
        # Ledger lines carry only id and created_at (PRD 2.5) — no updated_at/version.
        "created_at": CLOCK.now(),
        "_seq": next_seq(),
    }
    db["reserve_entries"][entry["id"]] = entry
    recompute_reserve(reserve)
    touch(reserve)
    return entry


def recompute_partner_outstanding(partner):
    """Sum of outstanding_cents over the partner's open chargebacks."""
    partner["outstanding_chargeback_cents"] = sum(
        c["outstanding_cents"]
        for c in db["chargebacks"].values()
        if c["trade_partner_id"] == partner["id"] and c["status"] in PARTNER_OUTSTANDING_STATUSES
    )


def recompute_partner_open_count(partner):
    """Computed counter: the number of the partner's work orders currently SCHEDULED."""
    partner["open_work_order_count"] = sum(
        1 for w in db["work_orders"].values()
        if w["trade_partner_id"] == partner["id"] and w["status"] == "SCHEDULED"
    )


def recompute_request_cost(service_request):
    """Sum of actual_cost_cents over the request's work orders in COMPLETED/ACCEPTED."""
    total = 0
    for w in db["work_orders"].values():
        if (w["service_request_id"] == service_request["id"]
                and w["status"] in ("COMPLETED", "ACCEPTED")):
            total += w["actual_cost_cents"] or 0
    service_request["actual_cost_cents"] = total


def refresh_chargeback_amounts(chargeback):
    """payable = final when basis FINAL else provisional; outstanding = payable - collected.
    WAIVED/VOID force outstanding to zero."""
    if chargeback["amount_basis"] == "FINAL":
        chargeback["payable_amount_cents"] = chargeback["final_amount_cents"]
    else:
        chargeback["payable_amount_cents"] = chargeback["provisional_amount_cents"]
    if chargeback["status"] in ("WAIVED", "VOID"):
        chargeback["outstanding_cents"] = 0
    else:
        chargeback["outstanding_cents"] = (
            chargeback["payable_amount_cents"] - chargeback["collected_cents"])

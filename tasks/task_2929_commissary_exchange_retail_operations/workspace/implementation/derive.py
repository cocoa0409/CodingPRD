"""Derived figures.

PRD 2.9: derived totals are always recomputed from the current contents of the
set they claim to sum, never adjusted by a delta, so they cannot drift.
"""

import constants as C
from db import db, new_id, new_record


# --------------------------------------------------------------------------
# store fund figures
# --------------------------------------------------------------------------


def ledger_entries_of(store_id, fund=None):
    rows = [e for e in db.ledger.values() if e["store_id"] == store_id]
    if fund is not None:
        rows = [e for e in rows if e["fund"] == fund]
    rows.sort(key=lambda e: (e["created_at"], e["_seq"]))
    return rows


def surcharge_fund_balance_cents(store_id):
    return sum(e["amount_cents"] for e in db.ledger.values()
               if e["store_id"] == store_id and e["fund"] == "SURCHARGE")


def dividend_fund_balance_cents(store_id):
    return sum(e["amount_cents"] for e in db.ledger.values()
               if e["store_id"] == store_id and e["fund"] == "DIVIDEND")


def surcharge_obligated_cents(store_id):
    return sum(p["obligation_cents"] for p in db.projects.values()
               if p["store_id"] == store_id and p["state"] == "APPROVED")


def shipping_allowance_committed_cents(store_id):
    return sum(o["shipping_allowance_cents"] for o in db.special_orders.values()
               if o["store_id"] == store_id
               and o["state"] in ("LOCAL_FILL_PENDING", "OVERSEAS_SHIP_PENDING", "FULFILLED"))


def available_surcharge_cents(store_id):
    return surcharge_fund_balance_cents(store_id) - surcharge_obligated_cents(store_id)


def fund_posture(store_id):
    available = available_surcharge_cents(store_id)
    if available >= C.POSTURE_UNRESTRICTED_FLOOR_CENTS:
        return "UNRESTRICTED"
    if available >= C.POSTURE_CONSTRAINED_FLOOR_CENTS:
        return "CONSTRAINED"
    return "FROZEN"


# --------------------------------------------------------------------------
# ledger entry running balance
# --------------------------------------------------------------------------


def balance_after_cents(entry):
    """Running balance of this entry's (store_id, fund) pairing, walking that
    pairing in created_at ASC with ties broken by entry_type ascending."""
    pairing = [e for e in db.ledger.values()
               if e["store_id"] == entry["store_id"] and e["fund"] == entry["fund"]]
    pairing.sort(key=lambda e: (e["created_at"], e["entry_type"], e["_seq"]))
    running = 0
    for row in pairing:
        running += row["amount_cents"]
        if row["id"] == entry["id"]:
            return running
    return running


def append_ledger_entry(store, fund, entry_type, amount_cents, source_ref_kind, source_ref_id):
    """Fund ledger entries are append-only: id and created_at, no version."""
    entry = new_record(with_version=False)
    entry.update({
        "store_id": store["id"],
        "fund": fund,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "source_ref_kind": source_ref_kind,
        "source_ref_id": source_ref_id,
        "period_close_index": store["period_close_index"],
    })
    db.ledger[entry["id"]] = entry
    return entry


# --------------------------------------------------------------------------
# MWR program funding
# --------------------------------------------------------------------------


def ytd_funded_cents(program_id):
    return sum(-e["amount_cents"] for e in db.ledger.values()
               if e["entry_type"] == "DIVIDEND_TRANSFER" and e["source_ref_id"] == program_id)


# --------------------------------------------------------------------------
# sale lines
# --------------------------------------------------------------------------


def lines_of_sale(sale_id):
    rows = [l for l in db.sale_lines.values() if l["sale_id"] == sale_id]
    rows.sort(key=lambda l: (l["created_at"], l["_seq"]))
    return rows


def lines_by_sale_map():
    grouped = {}
    for line in db.sale_lines.values():
        grouped.setdefault(line["sale_id"], []).append(line)
    for rows in grouped.values():
        rows.sort(key=lambda l: (l["created_at"], l["_seq"]))
    return grouped

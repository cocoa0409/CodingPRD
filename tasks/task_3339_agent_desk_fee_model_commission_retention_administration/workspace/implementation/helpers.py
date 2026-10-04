"""Shared helpers: record lifecycle, serialization, pagination, time-gated reevaluation."""
from datetime import datetime, timedelta, timezone

import clock
from clock import now, fmt, parse, SENTINEL_END
from store import db, new_id


def new_record():
    n = now()
    return {
        "id": new_id(),
        "created_at": fmt(n),
        "updated_at": fmt(n),
        "version": 1,
    }


def touch(rec):
    rec["updated_at"] = fmt(now())
    rec["version"] = rec.get("version", 1) + 1


def paginate(items):
    from flask import request
    from response import err_invalid_request
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        raise err_invalid_request("limit must be an integer")
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        raise err_invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise err_invalid_request("limit out of range")
    if offset < 0:
        raise err_invalid_request("offset out of range")
    total = len(items)
    return items[offset:offset + limit], total, limit, offset


def sort_by_created(items):
    return sorted(items, key=lambda r: (r.get("created_at") or "", r.get("id") or ""))


# ---------------------------------------------------------------------------
# Time-gated reevaluation
# ---------------------------------------------------------------------------

def _recompute_schedule_status(s):
    n = now()
    ef = parse(s["effective_from"])
    et = parse(s["effective_to"])
    if n < ef:
        s["status"] = "DRAFT"
    elif ef <= n < et:
        s["status"] = "ACTIVE"
    else:
        s["status"] = "ARCHIVED"


def reevaluate():
    """Re-evaluate time-gated states against the logical clock."""
    n = now()
    # Offers: OFFERED -> EXPIRED when clock >= updated_at + 72h
    for o in db["offers"].values():
        if o["status"] == "OFFERED":
            upd = parse(o["updated_at"])
            if upd is not None and n >= upd + timedelta(hours=72):
                o["status"] = "EXPIRED"
                touch(o)
    # Invoices: ISSUED/PARTIALLY_PAID -> OVERDUE; OVERDUE -> COLLECTIONS
    for inv in db["invoices"].values():
        due = parse(inv.get("due_date"))
        if due is None:
            continue
        if inv["status"] in ("ISSUED", "PARTIALLY_PAID") and n > due:
            inv["status"] = "OVERDUE"
            touch(inv)
        if inv["status"] == "OVERDUE" and n > due + timedelta(days=30):
            inv["status"] = "COLLECTIONS"
            touch(inv)
            office = db["offices"].get(inv["office_id"])
            if office and office["status"] == "ACTIVE":
                office["status"] = "SUSPENDED"
                touch(office)
    # Fee schedules: recompute status vs clock
    for s in db["fee_schedules"].values():
        old = s["status"]
        _recompute_schedule_status(s)
        if s["status"] != old:
            touch(s)
    # Office trust balances
    for office in db["offices"].values():
        recompute_trust(office)


def recompute_trust(office):
    """trust_balance = held/accrued/hold entries + unpaid invoices in ISSUED/PARTIALLY_PAID/COLLECTIONS (+OVERDUE)."""
    total = 0
    for e in db["entries"].values():
        if e["office_id"] == office["id"] and e["status"] in ("ESCROW_HELD", "OFFICE_FEE_ACCRUED", "DEPARTURE_HOLD"):
            total += e["amount_cents"]
    for inv in db["invoices"].values():
        if inv["office_id"] == office["id"] and inv["status"] in ("ISSUED", "PARTIALLY_PAID", "OVERDUE", "COLLECTIONS"):
            total += inv["amount_due_cents"] - inv["amount_paid_cents"]
    office["trust_balance_cents"] = total


def month_of(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m")


def first_of_month(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    return datetime(y, m, 1, tzinfo=timezone.utc)


def next_month_start(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    if m == 12:
        return datetime(y + 1, 1, 1, tzinfo=timezone.utc)
    return datetime(y, m + 1, 1, tzinfo=timezone.utc)


def valid_month(ym):
    if not isinstance(ym, str) or len(ym) != 7 or ym[4] != "-":
        return False
    try:
        y, m = int(ym[:4]), int(ym[5:7])
        return 1 <= m <= 12
    except ValueError:
        return False

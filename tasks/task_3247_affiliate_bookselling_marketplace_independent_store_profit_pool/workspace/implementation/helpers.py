"""Common helpers: resource bookkeeping, reconciliation, payout sweep, datetime parsing."""
from datetime import datetime, timezone

import db
from errors import err_validation, err_not_found


def touch(resource):
    """Refresh updated_at and bump version."""
    resource["updated_at"] = db.now_wall_iso()
    resource["version"] = resource.get("version", 0) + 1


def base_resource():
    """Common fields for a full-lifecycle resource."""
    ts = db.now_wall_iso()
    return {"id": db.new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def ledger_resource():
    """Ledger entries have only id + created_at."""
    return {"id": db.new_id(), "created_at": db.now_wall_iso()}


def parse_dt(value):
    if not isinstance(value, str):
        raise err_validation("datetime must be an ISO 8601 string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err_validation("invalid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def reconcile_affiliate(store_id=None, partner_id=None):
    """accrued_balance_cents = sum(non-reversed ledger amounts) - sum(PAID payouts)."""
    entries = db.DB.ledger.values()
    payouts = db.DB.payouts.values()
    if store_id is not None:
        total = sum(e["amount_cents"] for e in entries
                    if e.get("affiliate_store_id") == store_id and not e.get("reversed", False))
        paid = sum(p["amount_cents"] for p in payouts
                   if p.get("affiliate_store_id") == store_id and p["status"] == "PAID")
        aff = db.DB.stores.get(store_id)
    else:
        total = sum(e["amount_cents"] for e in entries
                    if e.get("affiliate_partner_id") == partner_id and not e.get("reversed", False))
        paid = sum(p["amount_cents"] for p in payouts
                   if p.get("affiliate_partner_id") == partner_id and p["status"] == "PAID")
        aff = db.DB.partners.get(partner_id)
    if aff is None:
        return
    aff["accrued_balance_cents"] = total - paid


def payout_sweep(store_id=None, partner_id=None):
    """Open a payout if balance >= threshold, no open payout, affiliate ACTIVE."""
    if store_id is not None:
        aff = db.DB.stores.get(store_id)
        open_payout = any(p for p in db.DB.payouts.values()
                          if p.get("affiliate_store_id") == store_id
                          and p["status"] in ("PENDING", "PROCESSING"))
    else:
        aff = db.DB.partners.get(partner_id)
        open_payout = any(p for p in db.DB.payouts.values()
                          if p.get("affiliate_partner_id") == partner_id
                          and p["status"] in ("PENDING", "PROCESSING"))
    if aff is None or open_payout:
        return
    if aff.get("status") != "ACTIVE":
        return
    if aff["accrued_balance_cents"] >= aff["payout_threshold_cents"]:
        p = base_resource()
        p["affiliate_store_id"] = store_id
        p["affiliate_partner_id"] = partner_id
        p["amount_cents"] = aff["accrued_balance_cents"]
        p["status"] = "PENDING"
        p["failure_reason"] = None
        db.DB.payouts[p["id"]] = p


def payout_sweep_all():
    """Sweep every affiliate (used after pool distribution)."""
    for sid in list(db.DB.stores.keys()):
        payout_sweep(store_id=sid)
    for pid in list(db.DB.partners.keys()):
        payout_sweep(partner_id=pid)


def reevaluate_promotions():
    """Re-evaluate promotion lifecycle transitions against the logical clock."""
    now = db.get_clock()
    for promo in db.DB.promotions.values():
        ws = promo["_window_start_dt"]
        we = promo["_window_end_dt"]
        if promo["status"] == "SCHEDULED":
            if now > we:
                promo["status"] = "ENDED"
            elif ws <= now <= we:
                promo["status"] = "ACTIVE"
        elif promo["status"] == "ACTIVE":
            if now > we:
                promo["status"] = "ENDED"


def get_or_404(table, rid):
    r = table.get(rid)
    if r is None:
        raise err_not_found("Resource not found: %s" % rid)
    return r

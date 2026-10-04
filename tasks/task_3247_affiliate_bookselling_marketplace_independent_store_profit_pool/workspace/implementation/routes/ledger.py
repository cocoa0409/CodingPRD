"""Commission ledger entry endpoints."""
from flask import Blueprint, request

import db
import helpers
from middleware import require_roles
from response import ok_object, ok_list, paginate

bp = Blueprint("ledger", __name__)


def ledger_view(e):
    return {
        "id": e["id"],
        "affiliate_store_id": e.get("affiliate_store_id"),
        "affiliate_partner_id": e.get("affiliate_partner_id"),
        "order_id": e.get("order_id"),
        "pool_distribution_id": e.get("pool_distribution_id"),
        "kind": e["kind"],
        "amount_cents": e["amount_cents"],
        "reversed": e["reversed"],
        "created_at": e["created_at"],
    }


@bp.get("/bookshop/ledger-entries/<eid>")
def get_ledger_entry(eid):
    require_roles(["PlatformAdmin", "StoreManager", "Partner", "FinanceOps"])
    e = helpers.get_or_404(db.DB.ledger, eid)
    return ok_object(ledger_view(e))


@bp.get("/bookshop/ledger-entries")
def list_ledger_entries():
    require_roles(["PlatformAdmin", "StoreManager", "Partner", "FinanceOps"])
    args = request.args
    entries = list(db.DB.ledger.values())
    for key in ("affiliate_store_id", "affiliate_partner_id", "order_id",
                "pool_distribution_id", "kind"):
        v = args.get(key)
        if v is not None:
            entries = [e for e in entries if e.get(key) == v]
    page, limit, offset, total = paginate([ledger_view(e) for e in entries], args)
    return ok_list(page, limit, offset, total)

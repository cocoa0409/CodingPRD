"""Buyer endpoints."""
from flask import Blueprint, request

import db
import services as svc
from errors import err, parse_pagination, paginate
from middleware import authenticate, require_role, get_json_body, req_str, opt_bool
from response import envelope, envelope_list

bp = Blueprint("buyers", __name__)


def buyer_public(b):
    return {k: b[k] for k in (
        "id", "email", "display_name", "is_business_account", "status",
        "wallet_credit_cents", "created_at", "updated_at", "version")}


@bp.post("/marketplace/buyers")
def create_buyer():
    _uid, role = authenticate()
    require_role(role, ["Buyer"])
    body = get_json_body()
    email = req_str(body, "email")
    display_name = req_str(body, "display_name")
    is_business = opt_bool(body, "is_business_account", default=False)

    for b in db.buyers.values():
        if b["email"].lower() == email.lower():
            raise err("ERR_DUPLICATE_UNIQUE_FIELD", "email already registered")

    buyer = svc.make_record(db.buyers, {
        "email": email,
        "display_name": display_name,
        "is_business_account": is_business,
        "status": "ACTIVE",
        "wallet_credit_cents": 0,
    })
    return envelope(buyer_public(buyer), "object", 201)


@bp.get("/marketplace/buyers/<bid>")
def get_buyer(bid):
    _uid, role = authenticate()
    require_role(role, ["Buyer", "PlatformAdmin"])
    buyer = db.buyers.get(bid)
    if buyer is None:
        raise err("ERR_NOT_FOUND", "buyer %s not found" % bid)
    return envelope(buyer_public(buyer), "object", 200)


@bp.get("/marketplace/buyers")
def list_buyers():
    _uid, role = authenticate()
    require_role(role, ["PlatformAdmin"])
    limit, offset = parse_pagination(request.args)
    status_f = request.args.get("status")
    items = [b for b in db.buyers.values()
             if status_f is None or b["status"] == status_f]
    page, total, has_more = paginate(items, limit, offset)
    return envelope_list([buyer_public(b) for b in page],
                         limit, offset, total, has_more)

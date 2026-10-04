"""Retailer accounts (PRD 3.7).

POST /farm-network/retailers   (PlatformAdmin, 201)
"""
from flask import Blueprint

import domain
import store
from auth import authenticate, authorize
from clock import now
from responses import ok
from serialize import retailer_out
from validation import get_body, f_str, f_int

bp = Blueprint("retailers", __name__, url_prefix="/farm-network")


@bp.route("/retailers", methods=["POST"])
def create_retailer():
    uid, role = authenticate()
    authorize(role, ("PlatformAdmin",))
    data = get_body()
    name = f_str(data, "name")
    banner = f_str(data, "banner")
    terms = f_int(data, "terms_net_days", minimum=1)
    ts = now()
    retailer = {
        "id": domain.new_id(),
        "name": name,
        "banner": banner,
        "terms_net_days": terms,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.retailers[retailer["id"]] = retailer
    return ok(retailer_out(retailer), 201)

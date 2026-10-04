"""Customer endpoints."""
from flask import Blueprint

from db import store, new_id, now_iso, next_seq
from middleware import actor, require_role
from response import ok_object
from services.serialize import customer_public
from validation import body_json, req_str, req_int

bp = Blueprint("customers", __name__)


@bp.post("/customers")
def create_customer():
    _, role = actor()
    require_role(role, ["PlatformAdmin"])
    data = body_json()
    name = req_str(data, "name")
    home_region = req_str(data, "home_region")
    filling_lines_count = req_int(data, "filling_lines_count", minimum=1)
    ts = now_iso()
    customer = {
        "id": new_id(),
        "name": name,
        "home_region": home_region,
        "filling_lines_count": filling_lines_count,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_created_sort": next_seq(),
    }
    store["customers"][customer["id"]] = customer
    return ok_object(customer_public(customer), code=201)

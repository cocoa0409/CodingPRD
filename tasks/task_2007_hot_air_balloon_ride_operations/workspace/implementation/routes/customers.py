"""Customer endpoints (PRD 3.1): Anonymous self-registration, wallet read."""
from flask import Blueprint

from middleware import authorized, ALL_READ_ROLES
from response import success_object
from services.core import new_record, public_customer
from validate import get_body, req_str, require_path_resource

bp = Blueprint("customers", __name__, url_prefix="/v1")


@bp.post("/customers")
def create_customer():
    authorized(["Anonymous"])
    body = get_body()
    rec = new_record("customers", {
        "name": req_str(body, "name"),
        "email": req_str(body, "email"),
        "wallet_credit_cents": 0,
    })
    return success_object(public_customer(rec), status=201)


@bp.get("/customers/<customer_id>")
def get_customer(customer_id):
    authorized(ALL_READ_ROLES)
    rec = require_path_resource("customers", customer_id, "customer")
    return success_object(public_customer(rec))

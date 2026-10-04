"""Customer endpoints (PRD 3.2, 3.7)."""
from db import db
from errors import not_found, raise_error, invalid_request
from middleware import (
    require_auth,
    body_json,
    get_str,
    get_num,
    get_int,
    pagination_params,
    sort_by_created,
)
from response import success_object, success_array
from serializers import customer as ser_customer
from services import make_record, touch
from . import customers_bp


@customers_bp.route("/customers", methods=["POST"])
def create_customer():
    require_auth(["Customer", "PlatformAdmin"])
    body = body_json()
    email = get_str(body, "email", required=True)
    display_name = get_str(body, "display_name", required=True)
    tip_pct = get_num(body, "stored_tip_default_pct", default=0)
    if tip_pct < 0 or tip_pct > 0.50:
        invalid_request("stored_tip_default_pct must be between 0 and 0.50")
    rec = make_record()
    rec.update(
        {
            "email": email,
            "display_name": display_name,
            "app_user": True,
            "stored_tip_default_pct": tip_pct,
            "wallet_credit_cents": 0,
        }
    )
    db.customers[rec["id"]] = rec
    return success_object(ser_customer(rec), 201)


@customers_bp.route("/customers/<customerId>", methods=["GET"])
def get_customer(customerId):
    require_auth(["Customer", "ShiftManager", "PlatformAdmin"])
    c = db.customers.get(customerId)
    if c is None:
        not_found("Customer not found")
    return success_object(ser_customer(c))


@customers_bp.route("/customers", methods=["GET"])
def list_customers():
    require_auth(["ShiftManager", "PlatformAdmin"])
    customers = sort_by_created(list(db.customers.values()))
    limit, offset = pagination_params()
    total = len(customers)
    page = customers[offset : offset + limit]
    return success_array([ser_customer(c) for c in page], limit, offset, total)


@customers_bp.route("/customers/<customerId>/wallet/adjust", methods=["POST"])
def wallet_adjust(customerId):
    require_auth(["ShiftManager"])
    c = db.customers.get(customerId)
    if c is None:
        not_found("Customer not found")
    body = body_json()
    delta = get_int(body, "delta_cents", required=True)
    reason = get_str(body, "reason", required=True)
    new_balance = c["wallet_credit_cents"] + delta
    if new_balance < 0:
        raise_error("ERR_WALLET_NEGATIVE", "Wallet balance cannot go below 0")
    c["wallet_credit_cents"] = new_balance
    touch(c)
    return success_object(ser_customer(c))

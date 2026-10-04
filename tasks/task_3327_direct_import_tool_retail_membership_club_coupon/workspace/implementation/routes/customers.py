"""Customer endpoints."""
from flask import Blueprint, request
from db import DB
from response import success
from middleware import require_roles, current_identity
from entities import stamp_new, get_or_404
from errors import raise_err

bp = Blueprint("customers", __name__)


@bp.route("/customers", methods=["POST"])
@require_roles("StoreClerk", "Customer", "OpsAdmin")
def create_customer():
    b = request.get_json(silent=True) or {}
    if not b.get("email") or not b.get("full_name"):
        raise_err("ERR_VALIDATION", "email and full_name required")
    for c in DB.customers.values():
        if c["email"] == b["email"]:
            raise_err("ERR_VALIDATION", "Duplicate email")
    rec = stamp_new({
        "email": b["email"],
        "full_name": b["full_name"],
        "store_credit_cents": 0,
    })
    DB.customers[rec["id"]] = rec
    return success(dict(rec), status=201)


@bp.route("/customers/<customerId>", methods=["GET"])
@require_roles("StoreClerk", "Customer", "WarrantyAdjuster", "OpsAdmin")
def get_customer(customerId):
    uid, role = current_identity()
    if role == "Customer" and uid != customerId:
        raise_err("ERR_FORBIDDEN", "Customers may only read their own record")
    return success(dict(get_or_404(DB.customers, customerId)))

"""Lessee registration and read."""
from flask import Blueprint

import serializers as S
from db import store, new_record
from guard import auth, lookup, get_body, v_string, v_int, v_enum, require_customer_owner
from response import success, created

bp = Blueprint("customers", __name__)

CREDIT_TIERS = ("PLATINUM", "GOLD", "STANDARD", "WATCH")


@bp.post("/customers")
def create_customer():
    auth("LeasingAgent")
    body = get_body()
    name = v_string(body, "name")
    billing_email = v_string(body, "billing_email")
    credit_tier = v_enum(body, "credit_tier", CREDIT_TIERS)
    credit_limit_cents = v_int(body, "credit_limit_cents", minimum=0)

    record = new_record(
        name=name,
        billing_email=billing_email,
        credit_tier=credit_tier,
        credit_limit_cents=credit_limit_cents,
        outstanding_balance_cents=0,
        credit_hold=False,
    )
    store.customers[record["id"]] = record
    return created(S.customer(record))


@bp.get("/customers/<customer_id>")
def read_customer(customer_id):
    auth("LeasingAgent", "FleetAdmin", "Customer")
    record = lookup(store.customers, customer_id, "ERR_CUSTOMER_NOT_FOUND")
    return success(S.customer(record))

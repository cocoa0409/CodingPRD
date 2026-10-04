"""Customer airline registration (PRD 3.1)."""
from flask import Blueprint

import svc
from core import (
    ALL_ROLES,
    ApiError,
    body,
    db,
    endpoint,
    f_enum,
    f_str,
    new_row,
    respond_object,
)

bp = Blueprint("customers", __name__, url_prefix="/api")

CREDIT_STANDINGS = ("GOOD", "WATCH", "POOR")


@bp.post("/customers")
@endpoint("ProgramAdmin")
def create_customer():
    payload = body()
    # rung 8 -- airline_code unique
    candidate = payload.get("airline_code")
    if isinstance(candidate, str) and any(
        c["airline_code"] == candidate for c in db.customers.values()
    ):
        raise ApiError("ERR_DUPLICATE_CODE")
    # rung 10 -- body shape
    airline_code = f_str(payload, "airline_code")
    name = f_str(payload, "name")
    credit_standing = f_enum(payload, "credit_standing", CREDIT_STANDINGS)
    customer = new_row(
        "Customer",
        airline_code=airline_code,
        name=name,
        credit_standing=credit_standing,
    )
    db.customers[customer["id"]] = customer
    return respond_object(svc.dump_customer(customer), 201)


@bp.get("/customers/<customer_id>")
@endpoint(*ALL_ROLES)
def get_customer(customer_id):
    return respond_object(svc.dump_customer(svc.need_customer(customer_id)))

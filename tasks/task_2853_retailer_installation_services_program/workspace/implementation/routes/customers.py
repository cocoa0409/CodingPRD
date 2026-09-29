"""Customers: the purchasing side of the programme."""
from flask import Blueprint

import envelope
import fields
import store
from fields import S, auth, body, need, pagination, validate

bp = Blueprint("customers", __name__)

CUSTOMER_CREATE = [
    S("full_name", maxlen=120),
    S("email", maxlen=320),
    S("jurisdiction_id"),
]


@bp.post("/customers")
def create_customer():
    auth(["ProgramAdmin", "ProjectCoordinator"])
    data = validate(body(), CUSTOMER_CREATE)
    need("jurisdictions", data["jurisdiction_id"])
    row = {
        "full_name": data["full_name"],
        "email": data["email"],
        "jurisdiction_id": data["jurisdiction_id"],
        "project_count": 0,
    }
    store.insert("customers", row)
    return envelope.obj(row, 201)


@bp.get("/customers")
def list_customers():
    auth(["ProgramAdmin", "ProjectCoordinator", "ServiceManager"])
    limit, offset = pagination()
    rows = store.all_rows("customers")
    rows = fields.filter_eq(rows, "jurisdiction_id", fields.arg("jurisdiction_id"))
    return envelope.collection(envelope.order_default(rows), limit, offset)


@bp.get("/customers/<row_id>")
def get_customer(row_id):
    auth(["ProgramAdmin", "ProjectCoordinator", "ServiceManager", "Customer"])
    return envelope.obj(need("customers", row_id))

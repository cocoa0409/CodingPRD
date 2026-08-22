"""Owner enrolment and the fiscal statement."""

from flask import Blueprint, request

from db import base_row, db, insert
from middleware import endpoint
from response import object_response, raw_response
from routes import lookup
from services import constants as C
from validation import body, req_state_code, req_str

bp = Blueprint("owners", __name__)


@bp.post("/owners")
@endpoint("BoardAdmin")
def create_owner():
    payload = body()
    legal_name = req_str(payload, "legal_name")
    mailing_state = req_state_code(payload, "mailing_state")
    contact_email = req_str(payload, "contact_email")

    row = base_row()
    row.update(
        {
            "legal_name": legal_name,
            "mailing_state": mailing_state,
            "contact_email": contact_email,
            "standing": "GOOD",
            "posted_arrears_cents": 0,
            "projected_arrears_cents": 0,
            "suspended_since": None,
        }
    )
    insert(db.owners, row)
    return object_response(row, 201)


@bp.get("/owners/<owner_id>")
@endpoint("BoardAdmin", "LivestockOwner", "FeeAdministrator", "BrandRecorder")
def read_owner(owner_id):
    return object_response(lookup.owner(owner_id))


@bp.get("/owners/<owner_id>/statement")
@endpoint("BoardAdmin", "LivestockOwner", "FeeAdministrator")
def owner_statement(owner_id):
    owner = lookup.owner(owner_id)
    orders = [order for order in db.orders.values() if order["owner_id"] == owner["id"]]
    open_order_count = sum(1 for order in orders if order["fee_status"] in C.OPEN_FEE_STATUSES)
    delinquent_order_count = sum(1 for order in orders if order["fee_status"] == "DELINQUENT")
    return raw_response(
        {
            "owner_id": owner["id"],
            "standing": owner["standing"],
            "posted_arrears_cents": owner["posted_arrears_cents"],
            "projected_arrears_cents": owner["projected_arrears_cents"],
            "open_order_count": open_order_count,
            "delinquent_order_count": delinquent_order_count,
        }
    )

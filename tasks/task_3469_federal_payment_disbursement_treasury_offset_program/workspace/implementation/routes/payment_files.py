"""PaymentFile endpoints (PRD §3.4)."""
from flask import Blueprint

from constants import ROLE_PAYMENT_AGENCY_ANALYST
from db import STORE, new_entity
from errors import err_not_found
from middleware import authenticate, get_body, require_roles, spec_field, validate_body
from response import ok
from serializers import serialize_file
from util import gen_id

bp = Blueprint("payment_files", __name__)


@bp.post("/payment-files")
def create_payment_file():
    ctx = authenticate()
    require_roles(ctx, ROLE_PAYMENT_AGENCY_ANALYST)
    data = validate_body(get_body(), [
        spec_field("agency_code", "str", required=True),
        spec_field("settlement_date", "dt", required=True),
    ])
    ent = new_entity()
    ent["id"] = gen_id()
    ent.update({
        "agency_code": data["agency_code"],
        "settlement_date": data["settlement_date"],
        "status": "RECEIVED",
        "payment_count": 0,
        "total_offset_cents": 0,
        "total_disbursed_cents": 0,
    })
    STORE["files"][ent["id"]] = ent
    return ok(serialize_file(ent), 201)


@bp.get("/payment-files/<string:paymentFileId>")
def get_payment_file(paymentFileId):
    authenticate()
    payment_file = STORE["files"].get(paymentFileId)
    if payment_file is None:
        raise err_not_found("Payment file not found")
    return ok(serialize_file(payment_file))

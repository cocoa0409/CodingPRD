"""House, city and deposit ledger accounts."""
from decimal import Decimal

from flask import Blueprint

import db
import response
import shapes
from constants import LEDGER_TYPES, PREFIX
from middleware import ALL_ROLES, CONTROLLER, PROPERTY_ADMIN, authenticate
from services import lookup, serial

bp = Blueprint("ledger_accounts", __name__, url_prefix=PREFIX)


@bp.route("/ledger-accounts", methods=["POST"])
def create_ledger_account():
    authenticate([PROPERTY_ADMIN, CONTROLLER])
    body = shapes.parse([
        shapes.Field("property_id", "string", required=True),
        shapes.Field("ledger_type", "string", required=True, enum=LEDGER_TYPES),
        shapes.Field("account_code", "string", required=True),
        shapes.Field("gl_account_code", "string", required=True),
        shapes.Field("opening_balance_amount", "number", ge=0,
                     default=Decimal("0.00")),
        shapes.Field("credit_limit_amount", "number", ge=0, default=Decimal("0.00")),
    ])
    prop = lookup.get_property(body["property_id"])
    row = db.insert("ledger_accounts", {
        "_kind": "LedgerAccount",
        "property_id": prop["id"],
        "ledger_type": body["ledger_type"],
        "account_code": body["account_code"],
        "gl_account_code": body["gl_account_code"],
        "opening_balance_amount": body["opening_balance_amount"],
        "credit_limit_amount": body["credit_limit_amount"],
    })
    return response.created(serial.ledger_out(row))


@bp.route("/ledger-accounts/<row_id>", methods=["GET"])
def get_ledger_account(row_id):
    authenticate(ALL_ROLES)
    return response.ok(serial.ledger_out(lookup.get_ledger(row_id)))


@bp.route("/ledger-accounts", methods=["GET"])
def list_ledger_accounts():
    authenticate(ALL_ROLES)
    rows = db.all_of("ledger_accounts")
    property_id = shapes.q("property_id")
    ledger_type = shapes.q("ledger_type")
    if property_id is not None:
        rows = [r for r in rows if r["property_id"] == property_id]
    if ledger_type is not None:
        rows = [r for r in rows if r["ledger_type"] == ledger_type]
    items, meta = shapes.page(rows, serial.ledger_out)
    return response.collection(items, meta)

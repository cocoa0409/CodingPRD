"""Hand-posted journal lines and their reversals."""
from flask import Blueprint

import db
import response
import shapes
from constants import CHARGE_TYPES, PREFIX, REASON_CODES
from errors import ApiError
from middleware import (ALL_ROLES, CONTROLLER, FRONT_DESK_AGENT, NIGHT_AUDITOR,
                        authenticate)
from money import q2
from services import derive, lookup, serial

bp = Blueprint("journal", __name__, url_prefix=PREFIX)


@bp.route("/journal-postings", methods=["POST"])
def create_posting():
    user_id, role = authenticate([NIGHT_AUDITOR, FRONT_DESK_AGENT, CONTROLLER])
    body = shapes.parse([
        shapes.Field("business_date_id", "string", required=True),
        shapes.Field("charge_type", "string", required=True, enum=CHARGE_TYPES),
        shapes.Field("amount", "number", required=True),
        shapes.Field("folio_id", "string"),
        shapes.Field("ledger_account_id", "string"),
        shapes.Field("reason_code", "string", enum=REASON_CODES),
        shapes.Field("memo", "string"),
    ])
    if body["amount"] == 0:
        shapes.bad("amount must be non-zero.")
    date_row = lookup.get_date(body["business_date_id"])
    folio = lookup.get_folio(body["folio_id"]) if body["folio_id"] else None
    account = lookup.get_ledger(body["ledger_account_id"]) if body["ledger_account_id"] else None
    lookup.require_not_archived(date_row)
    lookup.require_charges_open(date_row)
    if folio is not None:
        if derive.folio_figures(folio)["settlement_status"] == "TRANSFERRED_TO_CITY_LEDGER":
            raise ApiError("ERR_FOLIO_ALREADY_TRANSFERRED",
                           "The account has been transferred to the city ledger.")
    if body["charge_type"] not in derive.POSTABLE_TYPES:
        raise ApiError("ERR_CHARGE_TYPE_NOT_POSTABLE",
                       "%s may not be posted by a client." % body["charge_type"])
    if folio is not None and folio["property_id"] != date_row["property_id"]:
        raise ApiError("ERR_CROSS_PROPERTY_REFERENCE",
                       "The account belongs to a different property.")
    if account is not None and account["property_id"] != date_row["property_id"]:
        raise ApiError("ERR_CROSS_PROPERTY_REFERENCE",
                       "The ledger account belongs to a different property.")
    amount = q2(body["amount"])
    if folio is not None and body["charge_type"] == "MISC_CHARGE":
        projected = q2(derive.folio_balance(folio) + amount)
        if projected > folio["credit_limit_amount"]:
            raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED",
                           "The charge would carry the account past its credit limit.")
    source = "FRONT_DESK" if role == FRONT_DESK_AGENT else "NIGHT_AUDIT"
    row = derive.append_posting(
        body["charge_type"], amount, date_row, source, user_id, folio=folio,
        ledger_account_id=account["id"] if account else None,
        reason_code=body["reason_code"], memo=body["memo"],
    )
    return response.created(serial.posting_out(row))


@bp.route("/journal-postings/<row_id>/reverse", methods=["POST"])
def reverse_posting(row_id):
    user_id, role = authenticate([NIGHT_AUDITOR, CONTROLLER])
    body = shapes.parse([shapes.Field("memo", "string")])
    original = lookup.get_posting(row_id)
    date_row = lookup.get_date(original["business_date_id"])
    lookup.require_not_archived(date_row)
    lookup.require_reversal_window(date_row)
    if original["reverses_posting_id"] or original["id"] in derive.reversed_posting_ids():
        raise ApiError("ERR_POSTING_ALREADY_REVERSED",
                       "The line is a reversal or has already been reversed.")
    if original["posted_by_user_id"] == user_id:
        raise ApiError("ERR_SELF_REVERSAL_FORBIDDEN",
                       "An operator may not reverse their own line.")
    folio = db.store.folios.get(original["folio_id"]) if original["folio_id"] else None
    source = "FRONT_DESK" if role == FRONT_DESK_AGENT else "NIGHT_AUDIT"
    row = derive.append_posting(
        original["charge_type"], -original["amount"], date_row, source, user_id,
        folio=folio, ledger_account_id=original["ledger_account_id"],
        reason_code=original["reason_code"], memo=body["memo"],
        reverses_posting_id=original["id"],
    )
    return response.created(serial.posting_out(row))


@bp.route("/journal-postings/<row_id>", methods=["GET"])
def get_posting(row_id):
    authenticate(ALL_ROLES)
    return response.ok(serial.posting_out(lookup.get_posting(row_id)))


@bp.route("/journal-postings", methods=["GET"])
def list_postings():
    authenticate(ALL_ROLES)
    rows = db.all_of("postings")
    for key in ("folio_id", "ledger_account_id", "business_date_id",
                "outlet_ticket_id", "allowance_id", "reverses_posting_id",
                "charge_type", "source_channel"):
        value = shapes.q(key)
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    items, meta = shapes.page(rows, serial.posting_out)
    return response.collection(items, meta)

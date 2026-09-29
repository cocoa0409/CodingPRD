"""Guest accounts: reservation, arrival, departure, cancellation, tenders."""
from decimal import Decimal

from flask import Blueprint

import db
import response
import shapes
from constants import MARKET_SEGMENTS, PREFIX, SETTLEMENT_METHODS
from errors import ApiError
from middleware import ALL_ROLES, FRONT_DESK_AGENT, NIGHT_AUDITOR, authenticate
from money import ZERO, q2
from services import calc, derive, lookup, serial

bp = Blueprint("folios", __name__, url_prefix=PREFIX)


@bp.route("/folios", methods=["POST"])
def create_folio():
    authenticate([FRONT_DESK_AGENT, NIGHT_AUDITOR])
    body = shapes.parse([
        shapes.Field("property_id", "string", required=True),
        shapes.Field("arrival_business_date_id", "string", required=True),
        shapes.Field("confirmation_code", "string", required=True),
        shapes.Field("guest_name", "string", required=True),
        shapes.Field("room_number", "string", required=True),
        shapes.Field("nights_count", "integer", required=True, ge=1),
        shapes.Field("contracted_rate_amount", "number", required=True, ge=0),
        shapes.Field("rate_plan_code", "string", required=True),
        shapes.Field("market_segment", "string", required=True, enum=MARKET_SEGMENTS),
        shapes.Field("settlement_method", "string", required=True,
                     enum=SETTLEMENT_METHODS),
        shapes.Field("scheduled_checkout_at", "instant", required=True),
        shapes.Field("is_comp", "boolean", default=False),
        shapes.Field("credit_limit_amount", "number", ge=0,
                     default=Decimal("500.00")),
    ])
    prop = lookup.get_property(body["property_id"])
    date_row = lookup.get_date(body["arrival_business_date_id"])
    lookup.require_not_archived(date_row)
    if date_row["property_id"] != prop["id"]:
        raise ApiError("ERR_CROSS_PROPERTY_REFERENCE",
                       "The arrival day belongs to a different property.")
    row = db.insert("folios", {
        "_kind": "Folio",
        "property_id": prop["id"],
        "arrival_business_date_id": date_row["id"],
        "confirmation_code": body["confirmation_code"],
        "guest_name": body["guest_name"],
        "room_number": body["room_number"],
        "nights_count": body["nights_count"],
        "contracted_rate_amount": q2(body["contracted_rate_amount"]),
        "rate_plan_code": body["rate_plan_code"],
        "market_segment": body["market_segment"],
        "settlement_method": body["settlement_method"],
        "scheduled_checkout_at": body["scheduled_checkout_at"],
        "actual_checkout_at": None,
        "is_comp": body["is_comp"],
        "credit_limit_amount": q2(body["credit_limit_amount"]),
        "stay_status": "RESERVED",
        "settlement_status": "UNSETTLED",
    })
    return response.created(serial.folio_out(row))


@bp.route("/folios/<row_id>", methods=["GET"])
def get_folio(row_id):
    authenticate(ALL_ROLES)
    return response.ok(serial.folio_out(lookup.get_folio(row_id)))


@bp.route("/folios", methods=["GET"])
def list_folios():
    authenticate(ALL_ROLES)
    rows = db.all_of("folios")
    for key in ("property_id", "arrival_business_date_id", "stay_status",
                "settlement_method", "confirmation_code"):
        value = shapes.q(key)
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    settlement_status = shapes.q("settlement_status")
    if settlement_status is not None:
        rows = [r for r in rows if r["settlement_status"] == settlement_status]
    is_comp = shapes.q_bool("is_comp")
    if is_comp is not None:
        rows = [r for r in rows if bool(r["is_comp"]) == is_comp]
    items, meta = shapes.page(rows, serial.folio_out)
    return response.collection(items, meta)


@bp.route("/folios/<row_id>/check-in", methods=["POST"])
def check_in(row_id):
    authenticate([FRONT_DESK_AGENT, NIGHT_AUDITOR])
    folio = lookup.get_folio(row_id)
    date_row = db.store.business_dates.get(folio["arrival_business_date_id"])
    if date_row is not None:
        lookup.require_not_archived(date_row)
        lookup.require_charges_open(date_row)
    if folio["stay_status"] != "RESERVED":
        raise ApiError("ERR_FOLIO_NOT_RESERVED", "The account is not reserved.")
    prop = db.store.properties[folio["property_id"]]
    variance = calc.rate_variance_pct(folio["contracted_rate_amount"],
                                     prop["standard_room_rate_amount"])
    if abs(variance) > prop["rate_variance_tolerance_pct"]:
        covering = lookup.has_active_document(
            folio["id"], "RATE_OVERRIDE", date_row["business_date"]
        ) if date_row else None
        if covering is None:
            raise ApiError("ERR_RATE_VARIANCE_UNAUTHORIZED",
                           "The contracted rate needs active override paperwork.")
    folio["stay_status"] = "IN_HOUSE"
    derive.touch(folio)
    return response.ok(serial.folio_out(folio))


@bp.route("/folios/<row_id>/check-out", methods=["POST"])
def check_out(row_id):
    user_id, _role = authenticate([FRONT_DESK_AGENT, NIGHT_AUDITOR])
    body = shapes.parse([shapes.Field("business_date_id", "string", required=True)])
    folio = lookup.get_folio(row_id)
    date_row = lookup.get_date(body["business_date_id"])
    lookup.require_not_archived(date_row)
    lookup.require_charges_open(date_row)
    if folio["stay_status"] != "IN_HOUSE":
        raise ApiError("ERR_FOLIO_NOT_IN_HOUSE", "The account is not in house.")
    if derive.folio_hold(folio):
        raise ApiError("ERR_DECLINED_AUTH_UNRESOLVED",
                       "The account carries an unresolved declined authorization.")
    prop = db.store.properties[folio["property_id"]]
    departure_at = db.now()
    charge, _overdue = calc.late_checkout_charge(
        folio["scheduled_checkout_at"], departure_at,
        prop["late_checkout_grace_minutes"], folio["contracted_rate_amount"],
    )
    if folio["settlement_method"] == "CREDIT_CARD":
        projected = q2(derive.folio_balance(folio) + charge)
        covered = False
        for auth in derive.auths_of_folio(folio["id"]):
            derive.lapse_authorization(auth, prop)
            if auth["status"] == "APPROVED" and auth["authorized_amount"] >= projected:
                covered = True
        if not covered:
            raise ApiError("ERR_AUTHORIZATION_SHORTFALL",
                           "No approved authorization covers the projected balance.")
    folio["actual_checkout_at"] = departure_at
    folio["stay_status"] = "DEPARTED"
    derive.touch(folio)
    if charge > ZERO:
        derive.append_posting("LATE_CHECKOUT", charge, date_row, "FRONT_DESK",
                              user_id, folio=folio)
    return response.ok(serial.folio_out(folio))


@bp.route("/folios/<row_id>/cancel", methods=["POST"])
def cancel(row_id):
    authenticate([FRONT_DESK_AGENT, NIGHT_AUDITOR])
    folio = lookup.get_folio(row_id)
    if folio["stay_status"] != "RESERVED":
        raise ApiError("ERR_FOLIO_NOT_RESERVED", "The account is not reserved.")
    if derive.folio_balance(folio) != ZERO:
        raise ApiError("ERR_FOLIO_BALANCE_NOT_ZERO",
                       "The account still carries a balance.")
    folio["stay_status"] = "CANCELLED"
    derive.touch(folio)
    return response.ok(serial.folio_out(folio))


@bp.route("/folios/<row_id>/payments", methods=["POST"])
def apply_payment(row_id):
    user_id, _role = authenticate([FRONT_DESK_AGENT, NIGHT_AUDITOR])
    body = shapes.parse([
        shapes.Field("business_date_id", "string", required=True),
        shapes.Field("amount", "number", required=True, gt=0),
        shapes.Field("ledger_account_id", "string"),
        shapes.Field("memo", "string"),
    ])
    folio = lookup.get_folio(row_id)
    date_row = lookup.get_date(body["business_date_id"])
    account = None
    if body["ledger_account_id"]:
        account = lookup.get_ledger(body["ledger_account_id"])
    lookup.require_not_archived(date_row)
    lookup.require_charges_open(date_row)
    if derive.folio_figures(folio)["settlement_status"] == "TRANSFERRED_TO_CITY_LEDGER":
        raise ApiError("ERR_FOLIO_ALREADY_TRANSFERRED",
                       "The account has been transferred to the city ledger.")
    derive.append_posting("PAYMENT", -q2(body["amount"]), date_row, "FRONT_DESK",
                          user_id, folio=folio,
                          ledger_account_id=account["id"] if account else None,
                          memo=body["memo"])
    return response.ok(serial.folio_out(folio))

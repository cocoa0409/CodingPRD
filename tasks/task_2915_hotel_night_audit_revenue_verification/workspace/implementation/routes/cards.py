"""Card authorizations: clock-driven ageing and the follow-up dimension."""
from flask import Blueprint

import db
import response
import shapes
from constants import DECLINE_CODES, FOLLOW_UP_ACTIONS, PREFIX
from errors import ApiError
from middleware import (ALL_ROLES, FRONT_DESK_AGENT, NIGHT_AUDITOR, authenticate)
from money import ZERO, q2
from services import derive, lookup, serial

bp = Blueprint("cards", __name__, url_prefix=PREFIX)

RECORDING_ROLES = [FRONT_DESK_AGENT, NIGHT_AUDITOR]


def _observe(auth):
    """Re-derive ageing on every read: an APPROVED row may already have lapsed.

    The lapse is a system observation, not a caller mutation, so it moves the
    status without touching updated_at or version.
    """
    if auth["status"] != "APPROVED":
        return auth
    folio = db.store.folios.get(auth["folio_id"])
    prop = db.store.properties.get(folio["property_id"]) if folio else None
    if prop is None:
        return auth
    if derive.auth_aging_days(auth) >= int(prop["card_authorization_valid_days"]):
        auth["status"] = "EXPIRED"
    return auth


def _folio_day(folio):
    return db.store.business_dates.get(folio["arrival_business_date_id"])


@bp.route("/card-authorizations", methods=["POST"])
def create_auth():
    _user_id, _role = authenticate(RECORDING_ROLES)
    body = shapes.parse([
        shapes.Field("folio_id", "string", required=True),
        shapes.Field("obtained_at", "instant", required=True),
        shapes.Field("authorized_amount", "number", required=True, gt=0),
    ])
    folio = lookup.get_folio(body["folio_id"])
    row = db.insert("card_auths", {
        "_kind": "CardAuthorization",
        "folio_id": folio["id"],
        "obtained_at": body["obtained_at"],
        "authorized_amount": q2(body["authorized_amount"]),
        "status": "APPROVED",
        "follow_up_status": "NOT_REQUIRED",
        "decline_code": None,
        "captured_amount": None,
        "resolved_by_user_id": None,
        "follow_up_note": None,
    })
    return response.created(serial.auth_out(_observe(row)))


@bp.route("/card-authorizations/<row_id>/decline", methods=["POST"])
def decline_auth(row_id):
    _user_id, _role = authenticate(RECORDING_ROLES)
    body = shapes.parse([
        shapes.Field("decline_code", "string", required=True, enum=DECLINE_CODES),
    ])
    auth = _observe(lookup.get_auth(row_id))
    if auth["status"] != "APPROVED":
        raise ApiError("ERR_AUTHORIZATION_NOT_APPROVED",
                       "Only an approved authorization may be declined.")
    auth["status"] = "DECLINED"
    auth["decline_code"] = body["decline_code"]
    auth["follow_up_status"] = "PENDING"
    derive.touch(auth)
    folio = db.store.folios.get(auth["folio_id"])
    if folio is not None:
        derive.touch(folio)
        day = _folio_day(folio)
        if day is not None:
            derive.touch(day)
    return response.ok(serial.auth_out(auth))


@bp.route("/card-authorizations/<row_id>/capture", methods=["POST"])
def capture_auth(row_id):
    user_id, _role = authenticate([NIGHT_AUDITOR])
    body = shapes.parse([
        shapes.Field("captured_amount", "number", required=True),
        shapes.Field("business_date_id", "string", required=True),
        shapes.Field("ledger_account_id", "string"),
    ])
    auth = lookup.get_auth(row_id)
    date_row = lookup.get_date(body["business_date_id"])
    folio = lookup.get_folio(auth["folio_id"])
    account = (lookup.get_ledger(body["ledger_account_id"])
               if body["ledger_account_id"] else None)
    lookup.require_not_archived(date_row)
    lookup.require_charges_open(date_row)
    _observe(auth)
    if auth["status"] == "EXPIRED":
        raise ApiError("ERR_AUTHORIZATION_EXPIRED",
                       "The authorization has aged past the validity window.")
    if auth["status"] != "APPROVED":
        raise ApiError("ERR_AUTHORIZATION_NOT_APPROVED",
                       "Only an approved authorization may be captured.")
    captured = q2(body["captured_amount"])
    if captured <= ZERO or captured > auth["authorized_amount"]:
        raise ApiError("ERR_CAPTURE_EXCEEDS_AUTHORIZATION",
                       "captured_amount must be positive and at most the hold.")
    auth["status"] = "CAPTURED"
    auth["captured_amount"] = captured
    derive.append_posting("PAYMENT", -captured, date_row, "FRONT_DESK", user_id,
                          folio=folio,
                          ledger_account_id=account["id"] if account else None)
    derive.touch(auth)
    return response.ok(serial.auth_out(auth))


@bp.route("/card-authorizations/<row_id>/follow-up", methods=["POST"])
def follow_up(row_id):
    user_id, _role = authenticate(RECORDING_ROLES)
    body = shapes.parse([
        shapes.Field("follow_up_action", "string", required=True,
                     enum=FOLLOW_UP_ACTIONS),
        shapes.Field("follow_up_note", "string"),
    ])
    auth = lookup.get_auth(row_id)
    action = body["follow_up_action"]
    if action == "CONTACT":
        if auth["follow_up_status"] != "PENDING":
            raise ApiError("ERR_FOLLOW_UP_NOT_PENDING",
                           "The follow-up is not pending.")
    elif auth["follow_up_status"] != "CONTACTED":
        raise ApiError("ERR_FOLLOW_UP_NOT_CONTACTED",
                       "The guest must be contacted first.")
    folio = db.store.folios.get(auth["folio_id"])
    if action == "RESOLVE":
        tenders = [p for p in derive.postings_of_folio(auth["folio_id"])
                   if p["charge_type"] == "PAYMENT"]
        if not tenders:
            raise ApiError("ERR_FOLLOW_UP_NO_REPLACEMENT_TENDER",
                           "A replacement tender must reach the account first.")
    if body["follow_up_note"] is not None:
        auth["follow_up_note"] = body["follow_up_note"]
    if action == "CONTACT":
        auth["follow_up_status"] = "CONTACTED"
    elif action == "RESOLVE":
        auth["follow_up_status"] = "RESOLVED"
        auth["resolved_by_user_id"] = user_id
    else:
        auth["follow_up_status"] = "ESCALATED"
        auth["resolved_by_user_id"] = user_id
    derive.touch(auth)
    if action == "RESOLVE" and folio is not None:
        derive.touch(folio)
        day = _folio_day(folio)
        if day is not None:
            derive.touch(day)
    return response.ok(serial.auth_out(auth))


@bp.route("/card-authorizations/<row_id>", methods=["GET"])
def get_auth(row_id):
    authenticate(ALL_ROLES)
    return response.ok(serial.auth_out(_observe(lookup.get_auth(row_id))))


@bp.route("/card-authorizations", methods=["GET"])
def list_auths():
    authenticate(ALL_ROLES)
    rows = [_observe(r) for r in db.all_of("card_auths")]
    for key in ("folio_id", "status", "follow_up_status"):
        value = shapes.q(key)
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    items, meta = shapes.page(rows, serial.auth_out)
    return response.collection(items, meta)

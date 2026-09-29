"""Sellers and buyers (PRD section 3.1)."""

import re

from flask import Blueprint, request

from auth import begin, not_owner
from calc import LICENSE_STATUSES, fmt_date
from errors import ApiError
from responses import list_response, object_response, pagination
from serializers import buyer_json, seller_json
from services import get_buyer, get_seller
from store import new_record, ordered, store, touch
from validators import bad, body, path_uuid, req_cents, req_enum, req_str

bp = Blueprint("parties", __name__)

STATE_CODE_RE = r"^[A-Z]{2}$"


def _state_code(data):
    value = req_str(data, "state_code", min_len=2, max_len=2)
    if not re.match(STATE_CODE_RE, value):
        bad("Field 'state_code' must be exactly two uppercase letters.")
    return value


# ---------------------------------------------------------------- sellers
@bp.post("/sellers")
def create_seller():
    begin("Broker", "PlatformAdmin")
    data = body()
    legal_name = req_str(data, "legal_name", min_len=1, max_len=120)
    state_code = _state_code(data)
    license_number = req_str(data, "license_number", min_len=1, max_len=40)
    record = new_record()
    record.update({"legal_name": legal_name, "state_code": state_code,
                   "license_number": license_number, "status": "ACTIVE",
                   "suspension_reason_code": None})
    store.sellers[record["id"]] = record
    return object_response(seller_json(record), 201)


@bp.get("/sellers/<identifier>")
def read_seller(identifier):
    role, user_id = begin("Broker", "PlatformAdmin", "Seller")
    if role == "Seller" and identifier != user_id:
        not_owner()
    path_uuid(identifier)
    return object_response(seller_json(get_seller(identifier)))


@bp.get("/sellers")
def list_sellers():
    begin("Broker", "PlatformAdmin")
    limit, offset = pagination()
    state_code = request.args.get("state_code")
    status = request.args.get("status")
    rows = ordered(store.sellers, lambda r: ((state_code is None or r["state_code"] == state_code)
                                             and (status is None or r["status"] == status)))
    return list_response(rows, seller_json, limit, offset)


@bp.post("/sellers/<identifier>/suspend")
def suspend_seller(identifier):
    begin("PlatformAdmin")
    data = body()
    reason = req_str(data, "suspension_reason_code", min_len=1)
    path_uuid(identifier)
    seller = get_seller(identifier)
    seller["status"] = "SUSPENDED"
    seller["suspension_reason_code"] = reason
    touch(seller)
    return object_response(seller_json(seller))


# ---------------------------------------------------------------- buyers
@bp.post("/buyers")
def create_buyer():
    begin("Broker", "PlatformAdmin")
    data = body()
    legal_name = req_str(data, "legal_name", min_len=1, max_len=120)
    state_code = _state_code(data)
    license_status = req_enum(data, "license_status", LICENSE_STATUSES)
    prequalified = req_cents(data, "prequalified_amount_cents")
    record = new_record()
    record.update({"legal_name": legal_name, "state_code": state_code,
                   "license_status": license_status,
                   "prequalified_amount_cents": prequalified,
                   "qualification_status": "PENDING", "qualified_on": None})
    store.buyers[record["id"]] = record
    return object_response(buyer_json(record), 201)


@bp.get("/buyers/<identifier>")
def read_buyer(identifier):
    role, user_id = begin("Broker", "PlatformAdmin", "Buyer")
    if role == "Buyer" and identifier != user_id:
        not_owner()
    path_uuid(identifier)
    return object_response(buyer_json(get_buyer(identifier)))


@bp.get("/buyers")
def list_buyers():
    begin("Broker", "PlatformAdmin")
    limit, offset = pagination()
    state_code = request.args.get("state_code")
    qualification_status = request.args.get("qualification_status")
    license_status = request.args.get("license_status")

    def keep(row):
        return ((state_code is None or row["state_code"] == state_code)
                and (qualification_status is None
                     or row["qualification_status"] == qualification_status)
                and (license_status is None or row["license_status"] == license_status))

    return list_response(ordered(store.buyers, keep), buyer_json, limit, offset)


@bp.post("/buyers/<identifier>/qualify")
def qualify_buyer(identifier):
    begin("Broker", "PlatformAdmin")
    data = body()
    decision = req_enum(data, "decision", ("APPROVE", "DENY"))
    path_uuid(identifier)
    buyer = get_buyer(identifier)
    if buyer["qualification_status"] != "PENDING":
        raise ApiError("ERR_INVALID_BUYER_TRANSITION",
                       "The buyer's qualification has already been decided.")
    if decision == "APPROVE":
        buyer["qualification_status"] = "APPROVED"
        buyer["qualified_on"] = fmt_date(store.clock.date())
    else:
        buyer["qualification_status"] = "REJECTED"
    touch(buyer)
    return object_response(buyer_json(buyer))

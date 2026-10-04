"""Store resource routes, including the independent transfer dimension."""

from flask import Blueprint

import db
import middleware
import schemas
import services
import timeutil
from errors import fail
from response import ok
from routes.common import SHARED, list_records

bp = Blueprint("stores", __name__)

FORMATS = ("URBAN", "SUBURBAN", "RURAL")


@bp.post("/stores")
@middleware.auth(("FranchisorAdmin",))
def create_store():
    payload = middleware.body(
        required=("franchisee_id", "store_number", "state_code", "format",
                  "opened_on", "cold_chain_certified"),
    )
    franchisee = services.require_franchisee(payload["franchisee_id"])
    store_number = middleware.string_value(payload["store_number"], "store_number")
    state_code = middleware.string_value(payload["state_code"], "state_code")
    store_format = middleware.enum_value(payload["format"], FORMATS, "format")
    opened_on = timeutil.required_utc(payload["opened_on"])
    if not isinstance(payload["cold_chain_certified"], bool):
        fail("ERR_INVALID_REQUEST")

    for existing in db.all_of("stores"):
        if existing["store_number"] == store_number:
            fail("ERR_STORE_NUMBER_DUPLICATE")

    record = db.insert("stores", {
        "franchisee_id": franchisee["id"],
        "store_number": store_number,
        "state_code": state_code,
        "format": store_format,
        "opened_on": opened_on,
        "lease_owner": "FRANCHISOR",
        "equipment_owner": "FRANCHISOR",
        "monthly_rent_cents": services.monthly_rent_for_format(store_format),
        "cold_chain_certified": payload["cold_chain_certified"],
        "status": "ACTIVE",
        "transfer_status": "NONE",
        "transfer_target_franchisee_id": None,
        "transfer_price_cents": None,
    })
    return ok(schemas.dump("stores", record), 201)


@bp.get("/stores")
@middleware.auth(SHARED)
def list_stores():
    return list_records("stores", ("franchisee_id", "status", "transfer_status", "state_code"))


@bp.get("/stores/<store_id>")
@middleware.auth(SHARED)
def get_store(store_id):
    store = services.require("stores", store_id)
    return ok(schemas.dump("stores", store))


@bp.post("/stores/<store_id>/transfer-requests")
@middleware.auth(("FranchisorAdmin",))
def open_transfer_request(store_id):
    store = services.require("stores", store_id)
    payload = middleware.body(
        required=("transfer_target_franchisee_id", "transfer_price_cents"),
    )
    target = db.get("franchisees", payload["transfer_target_franchisee_id"])
    if target is None or target["status"] != "ACTIVE":
        fail("ERR_TRANSFEREE_NOT_ELIGIBLE")
    price = middleware.non_negative_int(payload["transfer_price_cents"], "transfer_price_cents")

    if store["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE")
    if store["transfer_status"] not in ("NONE", "DENIED"):
        fail("ERR_INVALID_STATE")
    if target["id"] == store["franchisee_id"]:
        fail("ERR_TRANSFER_CONFLICT")
    if services.agreement_for_store(store_id, statuses=("ACTIVE", "RENEWAL_PENDING", "TERMINATED")):
        if any(a["franchisee_id"] == target["id"]
               for a in services.agreement_for_store(store_id, statuses=("ACTIVE", "RENEWAL_PENDING", "TERMINATED"))):
            fail("ERR_TRANSFER_CONFLICT")

    store["transfer_status"] = "PENDING"
    store["transfer_target_franchisee_id"] = target["id"]
    store["transfer_price_cents"] = price
    db.touch(store)
    return ok(schemas.dump("stores", store))


@bp.post("/stores/<store_id>/transfer-decision")
@middleware.auth(("FranchisorAdmin",))
def decide_transfer(store_id):
    store = services.require("stores", store_id)
    payload = middleware.body(
        required=("decision", "expected_store_version"),
    )
    decision = middleware.enum_value(payload["decision"], ("APPROVE", "DENY"), "decision")
    expected = payload["expected_store_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        fail("ERR_INVALID_REQUEST")
    if expected != store["version"]:
        fail("ERR_STALE_VERSION")
    if store["transfer_status"] != "PENDING":
        fail("ERR_INVALID_STATE")

    if decision == "DENY":
        store["transfer_status"] = "DENIED"
        db.touch(store)
        return ok(schemas.dump("stores", store))

    target_id = store["transfer_target_franchisee_id"]
    target = db.get("franchisees", target_id)
    if target is None or target["status"] != "ACTIVE":
        fail("ERR_TRANSFEREE_NOT_ELIGIBLE")
    covering = services.covering_agreement(store_id)
    if covering is None:
        fail("ERR_NO_OPEN_AGREEMENT")
    if services.dec(target["audit_adjusted_net_worth_cents"]) < services.dec(covering["minimum_net_worth_cents"]):
        fail("ERR_TRANSFER_NET_WORTH_INSUFFICIENT")
    if any(a["franchisee_id"] == target_id
           for a in services.agreement_for_store(store_id, statuses=("ACTIVE", "RENEWAL_PENDING", "TERMINATED"))):
        fail("ERR_TRANSFER_CONFLICT")

    store["transfer_status"] = "APPROVED"
    store["franchisee_id"] = target_id
    db.touch(store)
    for agreement in services.agreement_for_store(store_id, statuses=("ACTIVE", "RENEWAL_PENDING")):
        agreement["status"] = "TERMINATED"
        db.touch(agreement)
    services.recalculate_franchisee(target)
    return ok(schemas.dump("stores", store))
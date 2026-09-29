"""Merchant onboarding and the integration lifecycle."""

from flask import Blueprint

from common import must, serve_list
from db import bump, create_row, db, public
from errors import ApiError, bad
from middleware import (
    arg_enum,
    arg_str,
    authorize,
    body,
    check_enum,
    check_int,
    check_str,
    pagination,
)
from response import object_response

bp = Blueprint("merchants", __name__)

READ_ROLES = ("PlatformAdmin", "FleetDispatcher", "CustomerSupport", "MerchantOperator")
INTEGRATION_STATES = ("PENDING", "ACTIVE", "SUSPENDED")
MERCHANT_GRADES = ("STANDARD", "PREFERRED", "ANCHOR")
INTEGRATION_ACTIONS = ("ACTIVATE", "SUSPEND", "REINSTATE")


@bp.get("/merchants")
def list_merchants():
    user_id, role = authorize(READ_ROLES)
    limit, offset = pagination()
    zone_id = arg_str("zone_id")
    integration_state = arg_enum("integration_state", INTEGRATION_STATES)
    merchant_grade = arg_enum("merchant_grade", MERCHANT_GRADES)
    rows = []
    for merchant in db.merchants.values():
        if role == "MerchantOperator" and merchant["id"] != user_id:
            continue
        if zone_id is not None and merchant["zone_id"] != zone_id:
            continue
        if integration_state is not None and merchant["integration_state"] != integration_state:
            continue
        if merchant_grade is not None and merchant["merchant_grade"] != merchant_grade:
            continue
        rows.append(merchant)
    return serve_list(rows, limit, offset)


@bp.get("/merchants/<merchant_id>")
def get_merchant(merchant_id):
    user_id, role = authorize(READ_ROLES)
    if role == "MerchantOperator" and merchant_id != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    return object_response(public(must("merchants", merchant_id)))


@bp.post("/merchants")
def create_merchant():
    authorize(("PlatformAdmin",))
    payload = body()
    for name in ("zone_id", "name"):
        if name not in payload or payload[name] is None:
            raise bad("Field '%s' is required." % name)
    merchant_grade = check_enum(payload, "merchant_grade", MERCHANT_GRADES, required=False)
    if merchant_grade is None:
        merchant_grade = "STANDARD"
    zone_id = check_str(payload, "zone_id", 1, None)
    name = check_str(payload, "name", 1, 120)
    handoff_sla_seconds = check_int(
        payload, "handoff_sla_seconds", ge=0, required=False, default=300
    )

    zone = must("zones", zone_id)

    merchant = create_row(
        db.merchants,
        {
            "zone_id": zone["id"],
            "name": name,
            "handoff_sla_seconds": handoff_sla_seconds,
            "merchant_grade": merchant_grade,
            "integration_state": "PENDING",
            "escrowed_fee_cents": 0,
            "recognized_fee_cents": 0,
            "released_fee_cents": 0,
            "settlement_variance_cents": 0,
            "exception_count": 0,
        },
    )
    return object_response(public(merchant), 201)


@bp.post("/merchants/<merchant_id>/integration-transitions")
def integration_transition(merchant_id):
    authorize(("PlatformAdmin",))
    payload = body()
    action = check_enum(payload, "action", INTEGRATION_ACTIONS)
    merchant = must("merchants", merchant_id)
    zone = db.zones.get(merchant["zone_id"])

    if action == "ACTIVATE":
        if merchant["integration_state"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if zone is None or zone["permit_state"] != "PERMITTED":
            raise ApiError("ERR_ZONE_NOT_PERMITTED")
        merchant["integration_state"] = "ACTIVE"
    elif action == "SUSPEND":
        if merchant["integration_state"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        merchant["integration_state"] = "SUSPENDED"
    else:  # REINSTATE
        if merchant["integration_state"] != "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if zone is None or zone["permit_state"] != "PERMITTED":
            raise ApiError("ERR_ZONE_NOT_PERMITTED")
        merchant["integration_state"] = "ACTIVE"

    bump(merchant)
    return object_response(public(merchant))

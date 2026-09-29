"""Handsets: reads, carrier activation and the two-step unlock (PRD 3.4)."""
from flask import Blueprint

import clock
import db
import lookups
import response
import serialize
import validate
from constants import (
    CARRIER_ACTIVATED, CARRIER_PENDING, CARRIER_PORT_ELIGIBLE, DQ_CURRENT, DU_ACTIVATED,
    DU_ACTIVATION_STATES, DU_LOCKED, DU_POSSESSION_STATES, DU_UNACTIVATED,
    DU_UNLOCK_REQUESTED, DU_UNLOCKED, DU_WITH_CUSTOMER, ROLE_CUSTOMER, ROLE_PROGRAM_ADMIN,
    ROLE_RETAIL_ASSOCIATE, ROLE_SERVICE_TECHNICIAN, UNLOCK_MIN_PAID_INSTALLMENTS,
)
from errors import ApiError
from middleware import require_owner, require_roles

bp = Blueprint("devices", __name__)

READ_ROLES = (ROLE_CUSTOMER, ROLE_RETAIL_ASSOCIATE, ROLE_SERVICE_TECHNICIAN,
              ROLE_PROGRAM_ADMIN)


def _owning_customer(device_id):
    device = db.device_units.get(device_id)
    if device is None:
        return None
    loan = db.loans.get(device["loan_id"])
    return loan["customer_id"] if loan is not None else None


@bp.get("/device-units")
def list_devices():
    require_roles(*READ_ROLES)
    limit, offset = validate.pagination()
    loan_id = validate.query_str("loan_id")
    device_model_id = validate.query_str("device_model_id")
    carrier_account_id = validate.query_str("carrier_account_id")
    activation_status = validate.query_enum("activation_status", DU_ACTIVATION_STATES)
    possession_status = validate.query_enum("possession_status", DU_POSSESSION_STATES)
    rows = db.values(db.device_units)
    if loan_id is not None:
        rows = [r for r in rows if r["loan_id"] == loan_id]
    if device_model_id is not None:
        rows = [r for r in rows if r["device_model_id"] == device_model_id]
    if carrier_account_id is not None:
        rows = [r for r in rows if r["carrier_account_id"] == carrier_account_id]
    if activation_status is not None:
        rows = [r for r in rows if r["activation_status"] == activation_status]
    if possession_status is not None:
        rows = [r for r in rows if r["possession_status"] == possession_status]
    page, total = validate.paginate(rows, limit, offset)
    return response.list_response([serialize.device_unit(r) for r in page],
                                  limit, offset, total)


@bp.get("/device-units/<device_id>")
def read_device(device_id):
    require_roles(*READ_ROLES)
    require_owner(_owning_customer(device_id))
    record = lookups.device_unit(device_id)
    return response.object_response(serialize.device_unit(record))


@bp.post("/device-units/<device_id>/activation")
def activate_device(device_id):
    require_roles(ROLE_RETAIL_ASSOCIATE, ROLE_SERVICE_TECHNICIAN)
    payload = validate.body()
    carrier_account_id = validate.req_uuid(payload, "carrier_account_id")

    device = lookups.device_unit(device_id)
    account = lookups.carrier_account(carrier_account_id)
    loan = db.loans.get(device["loan_id"])
    if loan is None or account["customer_id"] != loan["customer_id"]:
        raise ApiError("ERR_CROSS_REFERENCE_MISMATCH")

    if device["activation_status"] != DU_UNACTIVATED or \
            device["possession_status"] != DU_WITH_CUSTOMER:
        raise ApiError("ERR_DEVICE_ALREADY_ACTIVATED")
    if account["activation_state"] not in (CARRIER_PENDING, CARRIER_PORT_ELIGIBLE) or \
            account["port_freeze_flag"]:
        raise ApiError("ERR_CARRIER_ACCOUNT_NOT_PORTABLE")

    device["activation_status"] = DU_ACTIVATED
    device["carrier_account_id"] = account["id"]
    device["activated_at"] = clock.now_iso()
    db.touch(device)
    account["activation_state"] = CARRIER_ACTIVATED
    account["active_device_imei"] = device["imei"]
    account["activated_at"] = clock.now_iso()
    db.touch(account)
    return response.object_response(serialize.device_unit(device))


@bp.post("/device-units/<device_id>/unlock-request")
def request_unlock(device_id):
    require_roles(ROLE_CUSTOMER, ROLE_RETAIL_ASSOCIATE)
    require_owner(_owning_customer(device_id))
    validate.body()

    device = lookups.device_unit(device_id)
    loan = db.loans.get(device["loan_id"])
    if loan is not None and loan["delinquency_state"] != DQ_CURRENT:
        raise ApiError("ERR_LOAN_DELINQUENT")
    if device["activation_status"] != DU_ACTIVATED:
        raise ApiError("ERR_DEVICE_NOT_ACTIVATED")
    if device["unlock_status"] not in (DU_LOCKED, DU_UNLOCK_REQUESTED):
        raise ApiError("ERR_DEVICE_ALREADY_UNLOCKED")

    account = db.carrier_accounts.get(device["carrier_account_id"])
    policy_days = account["unlock_policy_days"] if account is not None else 0
    activated_at = clock.parse_iso8601(device["activated_at"])
    moment = clock.now()
    if activated_at is None or \
            clock.whole_day_difference(moment, activated_at) < policy_days:
        raise ApiError("ERR_UNLOCK_POLICY_PERIOD_NOT_ELAPSED")
    if loan is None or loan["paid_installment_count"] < UNLOCK_MIN_PAID_INSTALLMENTS:
        raise ApiError("ERR_UNLOCK_PAYMENT_THRESHOLD_NOT_MET")

    if device["unlock_status"] == DU_LOCKED:
        device["unlock_status"] = DU_UNLOCK_REQUESTED
        device["unlock_requested_at"] = clock.now_iso()
        db.touch(device)
    else:
        device["unlock_status"] = DU_UNLOCKED
        device["unlocked_at"] = clock.now_iso()
        db.touch(device)
        if account is not None and account["activation_state"] == CARRIER_ACTIVATED:
            account["activation_state"] = CARRIER_PORT_ELIGIBLE
            db.touch(account)
    return response.object_response(serialize.device_unit(device))

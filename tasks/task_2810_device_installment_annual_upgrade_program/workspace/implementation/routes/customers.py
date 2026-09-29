"""Enrolment and carrier accounts (PRD 3.1)."""
from flask import Blueprint

import clock
import db
import lookups
import response
import serialize
import validate
from constants import (
    CARRIER_CODES, CARRIER_PENDING, CUSTOMER_ACTIVE, DEFAULT_UNLOCK_POLICY_DAYS,
    ROLE_COLLECTIONS_OFFICER, ROLE_CREDIT_UNDERWRITER, ROLE_CUSTOMER, ROLE_PROGRAM_ADMIN,
    ROLE_RETAIL_ASSOCIATE, ROLE_SERVICE_TECHNICIAN,
)
from errors import ApiError
from middleware import require_owner, require_roles

bp = Blueprint("customers", __name__)


@bp.post("/customers")
def create_customer():
    require_roles(ROLE_RETAIL_ASSOCIATE, ROLE_PROGRAM_ADMIN)
    payload = validate.body()
    full_name = validate.req_str(payload, "full_name")
    email = validate.req_str(payload, "email")
    mobile_number = validate.req_str(payload, "mobile_number")
    if db.find_one(db.customers, email=email) is not None:
        raise ApiError("ERR_DUPLICATE_IDENTIFIER", "email is already enrolled.")
    record = db.insert(db.customers, {
        "full_name": full_name,
        "email": email,
        "mobile_number": mobile_number,
        "status": CUSTOMER_ACTIVE,
        "financing_lock_reason": None,
        "financing_locked_at": None,
        "credit_score_band": None,
        "credit_limit_cents": 0,
    })
    return response.object_response(serialize.customer(record), 201)


@bp.get("/customers/<customer_id>")
def read_customer(customer_id):
    require_roles(ROLE_CUSTOMER, ROLE_RETAIL_ASSOCIATE, ROLE_CREDIT_UNDERWRITER,
                  ROLE_COLLECTIONS_OFFICER, ROLE_PROGRAM_ADMIN)
    require_owner(customer_id)
    record = lookups.customer(customer_id)
    return response.object_response(serialize.customer(record))


@bp.post("/customers/<customer_id>/carrier-accounts")
def create_carrier_account(customer_id):
    require_roles(ROLE_CUSTOMER, ROLE_RETAIL_ASSOCIATE, ROLE_PROGRAM_ADMIN)
    require_owner(customer_id)
    payload = validate.body()
    carrier_code = validate.req_enum(payload, "carrier_code", CARRIER_CODES)
    account_number = validate.req_str(payload, "account_number")
    unlock_policy_days = validate.opt_int(payload, "unlock_policy_days",
                                          default=DEFAULT_UNLOCK_POLICY_DAYS, minimum=0)
    port_freeze_flag = validate.opt_bool(payload, "port_freeze_flag", default=False)
    lookups.customer(customer_id)
    if db.find_one(db.carrier_accounts, account_number=account_number) is not None:
        raise ApiError("ERR_DUPLICATE_IDENTIFIER", "account_number is already registered.")
    record = db.insert(db.carrier_accounts, {
        "customer_id": customer_id,
        "carrier_code": carrier_code,
        "account_number": account_number,
        "unlock_policy_days": unlock_policy_days,
        "activation_state": CARRIER_PENDING,
        "activated_at": None,
        "port_freeze_flag": port_freeze_flag,
        "active_device_imei": None,
    })
    return response.object_response(serialize.carrier_account(record), 201)


@bp.get("/customers/<customer_id>/carrier-accounts")
def list_carrier_accounts(customer_id):
    require_roles(ROLE_CUSTOMER, ROLE_RETAIL_ASSOCIATE, ROLE_SERVICE_TECHNICIAN,
                  ROLE_PROGRAM_ADMIN)
    require_owner(customer_id)
    limit, offset = validate.pagination()
    lookups.customer(customer_id)
    rows = db.find_all(db.carrier_accounts, customer_id=customer_id)
    page, total = validate.paginate(rows, limit, offset)
    return response.list_response([serialize.carrier_account(r) for r in page],
                                  limit, offset, total)

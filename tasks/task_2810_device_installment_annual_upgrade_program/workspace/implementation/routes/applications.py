"""Credit applications and the underwriting decision (PRD 3.2)."""
from flask import Blueprint, g

import calc
import clock
import db
import lookups
import response
import serialize
import validate
from constants import (
    ALLOWED_TERMS, APP_APPROVED, APP_CONDITIONAL_APPROVED, APP_DECLINED, APP_STATUSES,
    APP_SUBMITTED, CREDIT_BANDS, CREDIT_LIMITS, CUSTOMER_FINANCING_LOCKED,
    REASON_CONDITIONAL_DOWN_PAYMENT_REQUIRED, REASON_EXPOSURE_ABOVE_CONDITIONAL_BAND,
    REASON_WITHIN_LIMIT, ROLE_CREDIT_UNDERWRITER, ROLE_CUSTOMER, ROLE_PROGRAM_ADMIN,
    ROLE_RETAIL_ASSOCIATE,
)
from errors import ApiError
from middleware import require_owner, require_roles

bp = Blueprint("applications", __name__)

READ_ROLES = (ROLE_CUSTOMER, ROLE_RETAIL_ASSOCIATE, ROLE_CREDIT_UNDERWRITER,
              ROLE_PROGRAM_ADMIN)


@bp.post("/credit-applications")
def submit_application():
    require_roles(ROLE_CUSTOMER, ROLE_RETAIL_ASSOCIATE)
    raw = validate.body()
    require_owner(raw.get("customer_id") if isinstance(raw.get("customer_id"), str) else None)
    customer_id = validate.req_uuid(raw, "customer_id")
    device_model_id = validate.req_uuid(raw, "device_model_id")
    term_months = validate.req_int(raw, "requested_term_months")
    if term_months not in ALLOWED_TERMS:
        raise ApiError("ERR_INVALID_REQUEST", "requested_term_months must be 12 or 24.")
    declared_down_payment = validate.opt_int(raw, "declared_down_payment_cents",
                                             default=0, minimum=0)
    customer = lookups.customer(customer_id)
    model = lookups.device_model(device_model_id)
    if not model["active"]:
        raise ApiError("ERR_DEVICE_MODEL_INACTIVE")
    if customer["status"] == CUSTOMER_FINANCING_LOCKED:
        raise ApiError("ERR_CUSTOMER_FINANCING_LOCKED")
    if declared_down_payment >= model["retail_price_cents"]:
        raise ApiError("ERR_DOWN_PAYMENT_EXCEEDS_PRICE")
    record = db.insert(db.credit_applications, {
        "customer_id": customer_id,
        "device_model_id": device_model_id,
        "requested_term_months": term_months,
        "declared_down_payment_cents": declared_down_payment,
        "requested_principal_cents": model["retail_price_cents"] - declared_down_payment,
        "credit_score_band": None,
        "credit_limit_cents": 0,
        "exposure_at_decision_cents": 0,
        "approved_principal_cents": 0,
        "conditional_down_payment_required_cents": 0,
        "status": APP_SUBMITTED,
        "decision_reason": None,
        "underwriter_user_id": None,
        "decided_at": None,
    })
    return response.object_response(serialize.credit_application(record), 201)


@bp.get("/credit-applications")
def list_applications():
    require_roles(*READ_ROLES)
    limit, offset = validate.pagination()
    customer_id = validate.query_str("customer_id")
    device_model_id = validate.query_str("device_model_id")
    status = validate.query_enum("status", APP_STATUSES)
    rows = db.values(db.credit_applications)
    if customer_id is not None:
        rows = [r for r in rows if r["customer_id"] == customer_id]
    if device_model_id is not None:
        rows = [r for r in rows if r["device_model_id"] == device_model_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = validate.paginate(rows, limit, offset)
    return response.list_response([serialize.credit_application(r) for r in page],
                                  limit, offset, total)


@bp.get("/credit-applications/<application_id>")
def read_application(application_id):
    require_roles(*READ_ROLES)
    existing = db.credit_applications.get(application_id)
    require_owner(existing["customer_id"] if existing else None)
    record = lookups.credit_application(application_id)
    return response.object_response(serialize.credit_application(record))


@bp.post("/credit-applications/<application_id>/decision")
def decide_application(application_id):
    require_roles(ROLE_CREDIT_UNDERWRITER)
    payload = validate.body()
    band = validate.req_enum(payload, "credit_score_band", CREDIT_BANDS)
    application = lookups.credit_application(application_id)
    if application["status"] != APP_SUBMITTED:
        raise ApiError("ERR_APPLICATION_NOT_DECIDABLE")
    customer = lookups.customer(application["customer_id"])
    if customer["status"] == CUSTOMER_FINANCING_LOCKED:
        raise ApiError("ERR_CUSTOMER_FINANCING_LOCKED")

    outcome, exposure, approved_principal, conditional = calc.credit_decision(
        band, application["requested_principal_cents"],
        serialize.customer_outstanding_principal(customer["id"]))
    application["credit_score_band"] = band
    application["credit_limit_cents"] = CREDIT_LIMITS[band]
    application["exposure_at_decision_cents"] = exposure
    application["approved_principal_cents"] = approved_principal
    application["conditional_down_payment_required_cents"] = conditional
    if outcome == "APPROVED":
        application["status"] = APP_APPROVED
        application["decision_reason"] = REASON_WITHIN_LIMIT
    elif outcome == "CONDITIONAL_APPROVED":
        application["status"] = APP_CONDITIONAL_APPROVED
        application["decision_reason"] = REASON_CONDITIONAL_DOWN_PAYMENT_REQUIRED
    else:
        application["status"] = APP_DECLINED
        application["decision_reason"] = REASON_EXPOSURE_ABOVE_CONDITIONAL_BAND
    application["underwriter_user_id"] = g.user_id
    application["decided_at"] = clock.now_iso()
    db.touch(application)

    customer["credit_score_band"] = band
    customer["credit_limit_cents"] = CREDIT_LIMITS[band]
    db.touch(customer)
    return response.object_response(serialize.credit_application(application))

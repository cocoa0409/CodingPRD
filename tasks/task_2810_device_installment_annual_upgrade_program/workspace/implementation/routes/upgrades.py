"""The annual upgrade: eligibility, reservation, trade-in declaration and the
successor loan (PRD 3.8, 3.9)."""
from flask import Blueprint

import calc
import clock
import db
import lookups
import response
import serialize
import validate
from constants import (
    CARRIER_ACTIVATED, CARRIER_PENDING, CARRIER_PORT_ELIGIBLE, CONDITIONS,
    CUSTOMER_FINANCING_LOCKED, DQ_CURRENT, DU_ACTIVATED, DU_RETURN_PENDING, DU_RETURNED,
    DU_WITH_CUSTOMER, ELIGIBILITY_THRESHOLD_BPS, IMEI_LENGTH, LOAN_ACTIVE,
    QUOTE_CONSUMED, QUOTE_ISSUED, QUOTE_UPGRADE_ROLLOVER, ROLE_CUSTOMER,
    ROLE_PROGRAM_ADMIN, ROLE_RETAIL_ASSOCIATE, ROLE_SERVICE_TECHNICIAN,
    ROLLOVER_SHORTFALL_LIMIT_CENTS, TI_DECLARED, TI_GRADED, TI_SETTLED, UR_COMPLETED,
    UR_ELIGIBILITY_PASSED, UR_NON_TERMINAL, UR_STATUSES, UR_TRADE_IN_DECLARED,
    UR_TRADE_IN_GRADED,
)
from errors import ApiError
from middleware import require_owner, require_roles
from services import cascades
from services import loans as loan_service
from services import upgrades as upgrade_service

bp = Blueprint("upgrades", __name__)

READ_ROLES = (ROLE_CUSTOMER, ROLE_RETAIL_ASSOCIATE, ROLE_SERVICE_TECHNICIAN,
              ROLE_PROGRAM_ADMIN)


def _request_owner(request_id):
    request = db.upgrade_requests.get(request_id)
    return request["customer_id"] if request is not None else None


@bp.post("/upgrade-requests")
def open_upgrade_request():
    require_roles(ROLE_CUSTOMER, ROLE_RETAIL_ASSOCIATE)
    raw = validate.body()
    raw_loan_id = raw.get("loan_id")
    owning_loan = db.loans.get(raw_loan_id) if isinstance(raw_loan_id, str) else None
    require_owner(owning_loan["customer_id"] if owning_loan is not None else None)

    loan_id = validate.req_uuid(raw, "loan_id")
    target_model_id = validate.req_uuid(raw, "target_device_model_id")
    window_start = validate.req_instant(raw, "fulfillment_window_start")
    expected_version = validate.req_int(raw, "expected_loan_version")

    model = lookups.device_model(target_model_id)
    loan = lookups.loan(loan_id)

    if expected_version != loan["version"]:
        raise ApiError("ERR_STALE_LOAN_VERSION")

    if loan["status"] != LOAN_ACTIVE:
        raise ApiError("ERR_LOAN_NOT_ACTIVE")
    if loan["delinquency_state"] != DQ_CURRENT:
        raise ApiError("ERR_LOAN_DELINQUENT")
    device = cascades.device_for_loan(loan["id"])
    if device is None or device["activation_status"] != DU_ACTIVATED:
        raise ApiError("ERR_DEVICE_NOT_ACTIVATED")
    if not model["active"]:
        raise ApiError("ERR_DEVICE_MODEL_INACTIVE")

    customer = lookups.customer(loan["customer_id"])
    if customer["status"] == CUSTOMER_FINANCING_LOCKED:
        raise ApiError("ERR_CUSTOMER_FINANCING_LOCKED")

    moment = clock.now()
    if moment < clock.parse_iso8601(loan["upgrade_window_opens_at"]):
        raise ApiError("ERR_UPGRADE_WINDOW_NOT_OPEN")
    if window_start < moment:
        raise ApiError("ERR_FULFILLMENT_WINDOW_IN_PAST")

    window_finish = upgrade_service.window_end(window_start)
    clashes = upgrade_service.overlapping_reservation_count(
        model["id"], window_start, window_finish, loan["id"])
    if clashes >= model["concurrent_reservation_capacity"]:
        raise ApiError("ERR_MODEL_CAPACITY_EXHAUSTED")
    for other in db.values(db.loans):
        if other["id"] == loan["id"] or other["customer_id"] != customer["id"]:
            continue
        if other["status"] == LOAN_ACTIVE and other["device_model_id"] == model["id"]:
            raise ApiError("ERR_DUPLICATE_MODEL_ON_CUSTOMER")

    ratio_bps = calc.eligibility_ratio_bps(loan["paid_installment_count"],
                                          loan["term_months"])
    if ratio_bps < ELIGIBILITY_THRESHOLD_BPS:
        raise ApiError("ERR_UPGRADE_THRESHOLD_NOT_MET")

    for existing in db.values(db.upgrade_requests):
        if existing["loan_id"] == loan["id"] and existing["status"] in UR_NON_TERMINAL:
            cascades.supersede_request(existing)

    record = db.insert(db.upgrade_requests, {
        "loan_id": loan["id"],
        "customer_id": customer["id"],
        "target_device_model_id": model["id"],
        "new_loan_id": None,
        "payoff_quote_id": None,
        "fulfillment_window_start": clock.format_iso8601(window_start),
        "fulfillment_window_end": clock.format_iso8601(window_finish),
        "paid_installment_count_at_request": loan["paid_installment_count"],
        "eligibility_ratio_bps": ratio_bps,
        "trade_in_credit_projection_cents": 0,
        "projected_rollover_balance_cents": 0,
        "credit_shortfall_cents": 0,
        "funding_flag": None,
        "status": UR_ELIGIBILITY_PASSED,
        "additional_down_payment_cents": 0,
        "expiry_reason": None,
        "completed_at": None,
    })
    upgrade_service.refresh_funding_projection(record)
    db.touch(model)
    loan["upgrade_hold_flag"] = True
    db.touch(loan)
    return response.object_response(serialize.upgrade_request(record), 201)


@bp.get("/upgrade-requests")
def list_upgrade_requests():
    require_roles(*READ_ROLES)
    limit, offset = validate.pagination()
    filters = {
        "loan_id": validate.query_str("loan_id"),
        "customer_id": validate.query_str("customer_id"),
        "target_device_model_id": validate.query_str("target_device_model_id"),
        "new_loan_id": validate.query_str("new_loan_id"),
        "payoff_quote_id": validate.query_str("payoff_quote_id"),
        "status": validate.query_enum("status", UR_STATUSES),
    }
    rows = db.values(db.upgrade_requests)
    for field, wanted in filters.items():
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    page, total = validate.paginate(rows, limit, offset)
    return response.list_response([serialize.upgrade_request(r) for r in page],
                                  limit, offset, total)


@bp.get("/upgrade-requests/<request_id>")
def read_upgrade_request(request_id):
    require_roles(*READ_ROLES)
    require_owner(_request_owner(request_id))
    record = lookups.upgrade_request(request_id)
    return response.object_response(serialize.upgrade_request(record))


@bp.post("/upgrade-requests/<request_id>/trade-in-declaration")
def declare_trade_in(request_id):
    require_roles(ROLE_CUSTOMER, ROLE_RETAIL_ASSOCIATE)
    require_owner(_request_owner(request_id))
    payload = validate.body()
    device_unit_id = validate.req_uuid(payload, "device_unit_id")
    declared_condition = validate.req_enum(payload, "declared_condition", CONDITIONS)

    request = lookups.upgrade_request(request_id)
    device = lookups.device_unit(device_unit_id)
    if device["loan_id"] != request["loan_id"]:
        raise ApiError("ERR_CROSS_REFERENCE_MISMATCH")

    if request["status"] != UR_ELIGIBILITY_PASSED:
        raise ApiError("ERR_UPGRADE_REQUEST_NOT_AWAITING_TRADE_IN")
    if device["possession_status"] != DU_WITH_CUSTOMER:
        raise ApiError("ERR_DEVICE_ALREADY_ACTIVATED")
    if clock.now() >= clock.parse_iso8601(request["fulfillment_window_end"]):
        raise ApiError("ERR_FULFILLMENT_WINDOW_ELAPSED")

    model = db.device_models.get(device["device_model_id"])
    base_credit = model["trade_in_base_credit_cents"] if model is not None else 0
    trade_in = db.insert(db.trade_ins, {
        "upgrade_request_id": request["id"],
        "device_unit_id": device["id"],
        "declared_condition": declared_condition,
        "credit_estimate_cents": calc.declared_credit(base_credit, declared_condition),
        "graded_condition": None,
        "credit_final_cents": None,
        "diagnostic_result": None,
        "latest_report_sequence_no": 0,
        "credit_variance_cents": 0,
        "dispute_count": 0,
        "dispute_reason": None,
        "status": TI_DECLARED,
        "received_at": None,
        "graded_at": None,
        "settled_at": None,
    })
    cascades.set_possession(device, DU_RETURN_PENDING)
    request["status"] = UR_TRADE_IN_DECLARED
    upgrade_service.refresh_funding_projection(request)
    db.touch(request)
    return response.object_response(serialize.trade_in(trade_in), 201)


@bp.post("/upgrade-requests/<request_id>/completion")
def complete_upgrade(request_id):
    require_roles(ROLE_RETAIL_ASSOCIATE)
    payload = validate.body()
    quote_id = validate.req_uuid(payload, "payoff_quote_id")
    target_imei = validate.req_str(payload, "target_imei")
    additional_down_payment = validate.opt_int(
        payload, "additional_down_payment_cents", default=0, minimum=0)

    request = lookups.upgrade_request(request_id)
    quote = lookups.payoff_quote(quote_id)
    if quote["loan_id"] != request["loan_id"]:
        raise ApiError("ERR_CROSS_REFERENCE_MISMATCH")
    if quote["quote_type"] != QUOTE_UPGRADE_ROLLOVER:
        raise ApiError("ERR_PAYOFF_QUOTE_TYPE_MISMATCH")

    loan = lookups.loan(request["loan_id"])
    if loan["status"] != LOAN_ACTIVE:
        raise ApiError("ERR_LOAN_NOT_ACTIVE")
    if request["status"] != UR_TRADE_IN_GRADED:
        raise ApiError("ERR_UPGRADE_REQUEST_NOT_COMPLETABLE")
    trade_in = cascades.trade_in_for_request(request["id"])
    if trade_in is None or trade_in["status"] != TI_GRADED:
        raise ApiError("ERR_TRADE_IN_INVALID_STATE")
    if quote["status"] != QUOTE_ISSUED:
        raise ApiError("ERR_PAYOFF_QUOTE_NOT_ISSUED")

    moment = clock.now()
    if moment >= clock.parse_iso8601(quote["expires_at"]):
        raise ApiError("ERR_PAYOFF_QUOTE_EXPIRED")
    if moment >= clock.parse_iso8601(request["fulfillment_window_end"]):
        raise ApiError("ERR_FULFILLMENT_WINDOW_ELAPSED")

    if len(target_imei) != IMEI_LENGTH or not target_imei.isdigit() or \
            loan_service.imei_registered(target_imei):
        raise ApiError("ERR_IMEI_ALREADY_REGISTERED")

    target_model = lookups.device_model(request["target_device_model_id"])
    figures = calc.rollover_math(quote["total_payoff_cents"],
                                trade_in["credit_final_cents"] or 0,
                                additional_down_payment,
                                target_model["retail_price_cents"])
    if figures["net_rollover_cents"] > ROLLOVER_SHORTFALL_LIMIT_CENTS:
        raise ApiError("ERR_ROLLOVER_SHORTFALL_EXCEEDS_LIMIT")

    old_device = cascades.device_for_loan(loan["id"])
    carrier_account_id = old_device["carrier_account_id"] if old_device else None

    quote["status"] = QUOTE_CONSUMED
    quote["consumed_at"] = clock.format_iso8601(moment)
    db.touch(quote)

    loan_service.close_as_rolled_over(loan)
    if old_device is not None:
        cascades.set_possession(old_device, DU_RETURNED)
    cascades.unlock_device_on_closure(loan)

    successor = loan_service.mint_loan(
        customer_id=loan["customer_id"],
        credit_application_id=None,
        device_model_id=target_model["id"],
        down_payment_cents=0,
        origination_fee_cents=figures["origination_fee_cents"],
        rolled_over_balance_cents=figures["net_rollover_cents"],
        principal_cents=figures["principal_cents"],
        term_months=loan["term_months"],
        monthly_premium_cents=target_model["monthly_protection_premium_cents"],
        imei=target_imei,
        predecessor_loan_id=loan["id"],
        carrier_account_id=carrier_account_id,
    )

    account = db.carrier_accounts.get(carrier_account_id)
    if account is not None and account["activation_state"] in (
            CARRIER_ACTIVATED, CARRIER_PORT_ELIGIBLE):
        account["activation_state"] = CARRIER_PENDING
        account["active_device_imei"] = target_imei
        account["activated_at"] = None
        db.touch(account)

    trade_in["status"] = TI_SETTLED
    trade_in["settled_at"] = clock.format_iso8601(moment)
    db.touch(trade_in)

    db.touch(target_model)

    request["status"] = UR_COMPLETED
    request["completed_at"] = clock.format_iso8601(moment)
    request["new_loan_id"] = successor["id"]
    request["payoff_quote_id"] = quote["id"]
    request["additional_down_payment_cents"] = additional_down_payment
    db.touch(request)

    customer = db.customers.get(loan["customer_id"])
    if customer is not None:
        db.touch(customer)
    return response.object_response(serialize.loan(successor), 201)

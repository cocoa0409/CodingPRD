"""Origination, the loan reads, money in, payoff pricing and cancellation
(PRD 3.3, 3.5, 3.7)."""
from flask import Blueprint, g

import calc
import clock
import db
import lookups
import response
import serialize
import validate
from constants import (
    APP_APPROVED, APP_CONDITIONAL_APPROVED, APP_ORIGINATED, CUSTOMER_FINANCING_LOCKED,
    DQ_STATES, EVENT_TYPES, IMEI_LENGTH, INST_STATUSES, LOAN_ACTIVE, LOAN_STATUSES,
    POSTING_PAYMENT, POSTING_PAYOFF, POSTING_REVERSAL, POSTING_TYPES,
    QUOTE_EARLY_CANCELLATION, QUOTE_ISSUED, QUOTE_STATUSES, QUOTE_TYPES,
    QUOTE_UPGRADE_ROLLOVER, QUOTE_VALIDITY_DAYS, ROLE_COLLECTIONS_OFFICER,
    ROLE_CREDIT_UNDERWRITER, ROLE_CUSTOMER, ROLE_PROGRAM_ADMIN, ROLE_RETAIL_ASSOCIATE,
    ROLE_SERVICE_TECHNICIAN, UR_RESERVING_STATUSES,
)
from errors import ApiError
from middleware import require_owner, require_roles
from services import cascades
from services import loans as loan_service
from services import payments

bp = Blueprint("loans", __name__)


def _owning_customer(loan_id):
    loan = db.loans.get(loan_id)
    return loan["customer_id"] if loan is not None else None


@bp.post("/loans")
def originate():
    require_roles(ROLE_RETAIL_ASSOCIATE)
    payload = validate.body()
    application_id = validate.req_uuid(payload, "credit_application_id")
    down_payment = validate.req_int(payload, "down_payment_cents", minimum=0)
    imei = validate.req_str(payload, "imei")

    application = lookups.credit_application(application_id)
    if application["status"] not in (APP_APPROVED, APP_CONDITIONAL_APPROVED):
        raise ApiError("ERR_APPLICATION_NOT_APPROVED")
    if application["underwriter_user_id"] is not None and \
            application["underwriter_user_id"] == g.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    customer = lookups.customer(application["customer_id"])
    if customer["status"] == CUSTOMER_FINANCING_LOCKED:
        raise ApiError("ERR_CUSTOMER_FINANCING_LOCKED")
    if len(imei) != IMEI_LENGTH or not imei.isdigit() or loan_service.imei_registered(imei):
        raise ApiError("ERR_IMEI_ALREADY_REGISTERED")

    model = lookups.device_model(application["device_model_id"])
    principal = model["retail_price_cents"] - down_payment
    if application["status"] == APP_CONDITIONAL_APPROVED and \
            down_payment < application["conditional_down_payment_required_cents"]:
        raise ApiError("ERR_DOWN_PAYMENT_INSUFFICIENT")
    outstanding = serialize.customer_outstanding_principal(customer["id"])
    if outstanding + principal > customer["credit_limit_cents"]:
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED")

    loan = loan_service.mint_loan(
        customer_id=customer["id"],
        credit_application_id=application["id"],
        device_model_id=model["id"],
        down_payment_cents=down_payment,
        origination_fee_cents=0,
        rolled_over_balance_cents=0,
        principal_cents=principal,
        term_months=application["requested_term_months"],
        monthly_premium_cents=model["monthly_protection_premium_cents"],
        imei=imei,
        predecessor_loan_id=None,
    )
    application["status"] = APP_ORIGINATED
    db.touch(application)
    db.touch(customer)
    return response.object_response(serialize.loan(loan), 201)


@bp.get("/loans")
def list_loans():
    require_roles(ROLE_CUSTOMER, ROLE_RETAIL_ASSOCIATE, ROLE_CREDIT_UNDERWRITER,
                  ROLE_COLLECTIONS_OFFICER, ROLE_PROGRAM_ADMIN)
    limit, offset = validate.pagination()
    filters = {
        "customer_id": validate.query_str("customer_id"),
        "credit_application_id": validate.query_str("credit_application_id"),
        "device_model_id": validate.query_str("device_model_id"),
        "predecessor_loan_id": validate.query_str("predecessor_loan_id"),
        "status": validate.query_enum("status", LOAN_STATUSES),
        "delinquency_state": validate.query_enum("delinquency_state", DQ_STATES),
    }
    rows = db.values(db.loans)
    for field, wanted in filters.items():
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    page, total = validate.paginate(rows, limit, offset)
    return response.list_response([serialize.loan(r) for r in page], limit, offset, total)


@bp.get("/loans/<loan_id>")
def read_loan(loan_id):
    require_roles(ROLE_CUSTOMER, ROLE_RETAIL_ASSOCIATE, ROLE_CREDIT_UNDERWRITER,
                  ROLE_SERVICE_TECHNICIAN, ROLE_COLLECTIONS_OFFICER, ROLE_PROGRAM_ADMIN)
    require_owner(_owning_customer(loan_id))
    loan = lookups.loan(loan_id)
    return response.object_response(serialize.loan(loan))


@bp.get("/loans/<loan_id>/installments")
def list_installments(loan_id):
    require_roles(ROLE_CUSTOMER, ROLE_RETAIL_ASSOCIATE, ROLE_COLLECTIONS_OFFICER,
                  ROLE_PROGRAM_ADMIN)
    require_owner(_owning_customer(loan_id))
    limit, offset = validate.pagination()
    status = validate.query_enum("status", INST_STATUSES)
    loan = lookups.loan(loan_id)
    rows = serialize.loan_installments(loan["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = validate.paginate(rows, limit, offset)
    return response.list_response([serialize.installment(r) for r in page],
                                  limit, offset, total)


@bp.get("/loans/<loan_id>/delinquency-events")
def list_delinquency_events(loan_id):
    require_roles(ROLE_CUSTOMER, ROLE_COLLECTIONS_OFFICER, ROLE_PROGRAM_ADMIN)
    require_owner(_owning_customer(loan_id))
    limit, offset = validate.pagination()
    event_type = validate.query_enum("event_type", EVENT_TYPES)
    loan = lookups.loan(loan_id)
    rows = [r for r in db.values(db.delinquency_events) if r["loan_id"] == loan["id"]]
    if event_type is not None:
        rows = [r for r in rows if r["event_type"] == event_type]
    page, total = validate.paginate(rows, limit, offset)
    return response.list_response([serialize.delinquency_event(r) for r in page],
                                  limit, offset, total)


@bp.get("/loans/<loan_id>/payoff-quotes")
def list_payoff_quotes(loan_id):
    require_roles(ROLE_CUSTOMER, ROLE_RETAIL_ASSOCIATE, ROLE_COLLECTIONS_OFFICER,
                  ROLE_PROGRAM_ADMIN)
    require_owner(_owning_customer(loan_id))
    limit, offset = validate.pagination()
    quote_type = validate.query_enum("quote_type", QUOTE_TYPES)
    status = validate.query_enum("status", QUOTE_STATUSES)
    loan = lookups.loan(loan_id)
    rows = [r for r in db.values(db.payoff_quotes) if r["loan_id"] == loan["id"]]
    if quote_type is not None:
        rows = [r for r in rows if r["quote_type"] == quote_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = validate.paginate(rows, limit, offset)
    return response.list_response([serialize.payoff_quote(r) for r in page],
                                  limit, offset, total)


@bp.post("/loans/<loan_id>/payments")
def post_payment(loan_id):
    require_roles(ROLE_CUSTOMER, ROLE_RETAIL_ASSOCIATE, ROLE_COLLECTIONS_OFFICER,
                  ROLE_PROGRAM_ADMIN)
    require_owner(_owning_customer(loan_id))
    payload = validate.body()
    posting_type = validate.req_enum(payload, "posting_type", POSTING_TYPES)
    amount_cents = validate.req_int(payload, "amount_cents", minimum=0)
    if posting_type == POSTING_REVERSAL:
        reverses_posting_id = validate.req_uuid(payload, "reverses_posting_id")
    else:
        reverses_posting_id = validate.opt_uuid(payload, "reverses_posting_id")

    loan = lookups.loan(loan_id)
    target = None
    if reverses_posting_id is not None:
        target = lookups.payment_posting(reverses_posting_id)
        if target["loan_id"] != loan["id"]:
            raise ApiError("ERR_CROSS_REFERENCE_MISMATCH")

    if loan["status"] != LOAN_ACTIVE:
        raise ApiError("ERR_LOAN_NOT_ACTIVE")
    if posting_type == POSTING_REVERSAL:
        if target["posting_type"] not in (POSTING_PAYMENT, POSTING_PAYOFF):
            raise ApiError("ERR_POSTING_ALREADY_REVERSED")
        if payments.already_reversed(target["id"]):
            raise ApiError("ERR_POSTING_ALREADY_REVERSED")
    else:
        target = None
        if not payments.has_allocatable_installment(loan):
            raise ApiError("ERR_NOTHING_TO_ALLOCATE")

    if amount_cents < 1:
        raise ApiError("ERR_INVALID_POSTING_AMOUNT")
    if posting_type == POSTING_REVERSAL and amount_cents != target["amount_cents"]:
        raise ApiError("ERR_INVALID_POSTING_AMOUNT")

    posting = payments.post_money(loan, posting_type, amount_cents, target, clock.now())
    return response.object_response(serialize.payment_posting(posting), 201)


@bp.post("/loans/<loan_id>/payoff-quotes")
def price_payoff_quote(loan_id):
    require_roles(ROLE_CUSTOMER, ROLE_RETAIL_ASSOCIATE, ROLE_COLLECTIONS_OFFICER,
                  ROLE_PROGRAM_ADMIN)
    require_owner(_owning_customer(loan_id))
    payload = validate.body()
    quote_type = validate.req_enum(payload, "quote_type", QUOTE_TYPES)

    loan = lookups.loan(loan_id)
    if loan["status"] != LOAN_ACTIVE:
        raise ApiError("ERR_LOAN_NOT_ACTIVE")
    if quote_type == QUOTE_UPGRADE_ROLLOVER:
        live = [r for r in db.values(db.upgrade_requests)
                if r["loan_id"] == loan["id"] and r["status"] in UR_RESERVING_STATUSES]
        if not live:
            raise ApiError(
                "ERR_UPGRADE_REQUEST_NOT_FOUND",
                "An UPGRADE_ROLLOVER quote requires a live upgrade request on the loan.")

    moment = clock.now()
    figures = calc.payoff_figures(loan, serialize.loan_installments(loan["id"]),
                                  quote_type, moment)
    record = dict(figures)
    record["loan_id"] = loan["id"]
    record["quote_type"] = quote_type
    record["issued_at"] = clock.format_iso8601(moment)
    record["expires_at"] = clock.format_iso8601(
        clock.add_days(moment, QUOTE_VALIDITY_DAYS))
    record["status"] = QUOTE_ISSUED
    record["consumed_at"] = None
    quote = db.insert(db.payoff_quotes, record)
    cascades.supersede_standing_quotes(loan, keep_id=quote["id"], quote_type=quote_type)
    db.touch(loan)
    return response.object_response(serialize.payoff_quote(quote), 201)


@bp.post("/loans/<loan_id>/cancellation")
def cancel_program(loan_id):
    require_roles(ROLE_CUSTOMER, ROLE_RETAIL_ASSOCIATE, ROLE_PROGRAM_ADMIN)
    require_owner(_owning_customer(loan_id))
    payload = validate.body()
    quote_id = validate.req_uuid(payload, "payoff_quote_id")
    payment_amount = validate.req_int(payload, "payment_amount_cents", minimum=0)

    loan = lookups.loan(loan_id)
    quote = lookups.payoff_quote(quote_id)
    if quote["loan_id"] != loan["id"]:
        raise ApiError("ERR_CROSS_REFERENCE_MISMATCH")
    if quote["quote_type"] != QUOTE_EARLY_CANCELLATION:
        raise ApiError("ERR_PAYOFF_QUOTE_TYPE_MISMATCH")
    if loan["status"] != LOAN_ACTIVE:
        raise ApiError("ERR_LOAN_NOT_ACTIVE")
    if quote["status"] != QUOTE_ISSUED:
        raise ApiError("ERR_PAYOFF_QUOTE_NOT_ISSUED")
    if clock.parse_iso8601(quote["expires_at"]) <= clock.now():
        raise ApiError("ERR_PAYOFF_QUOTE_EXPIRED")
    if payment_amount != quote["total_payoff_cents"]:
        raise ApiError("ERR_PAYOFF_AMOUNT_MISMATCH")

    loan_service.close_as_paid_off(loan, quote, payment_amount)
    customer = db.customers.get(loan["customer_id"])
    if customer is not None:
        db.touch(customer)
    return response.object_response(serialize.loan(loan))

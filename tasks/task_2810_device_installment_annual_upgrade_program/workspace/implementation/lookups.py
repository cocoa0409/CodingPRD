"""Existence resolution (PRD 2.7 band 4).  Path segments resolve left to right;
body references resolve in the order the PRD names them."""
import db
from errors import ApiError


def _get(store, identifier, error_id):
    record = store.get(identifier) if isinstance(identifier, str) else None
    if record is None:
        raise ApiError(error_id)
    return record


def customer(identifier):
    return _get(db.customers, identifier, "ERR_CUSTOMER_NOT_FOUND")


def device_model(identifier):
    return _get(db.device_models, identifier, "ERR_DEVICE_MODEL_NOT_FOUND")


def carrier_account(identifier):
    return _get(db.carrier_accounts, identifier, "ERR_CARRIER_ACCOUNT_NOT_FOUND")


def credit_application(identifier):
    return _get(db.credit_applications, identifier, "ERR_CREDIT_APPLICATION_NOT_FOUND")


def loan(identifier):
    return _get(db.loans, identifier, "ERR_LOAN_NOT_FOUND")


def device_unit(identifier):
    return _get(db.device_units, identifier, "ERR_DEVICE_UNIT_NOT_FOUND")


def upgrade_request(identifier):
    return _get(db.upgrade_requests, identifier, "ERR_UPGRADE_REQUEST_NOT_FOUND")


def trade_in(identifier):
    return _get(db.trade_ins, identifier, "ERR_TRADE_IN_NOT_FOUND")


def payoff_quote(identifier):
    return _get(db.payoff_quotes, identifier, "ERR_PAYOFF_QUOTE_NOT_FOUND")


def payment_posting(identifier):
    return _get(db.payment_postings, identifier, "ERR_PAYMENT_POSTING_NOT_FOUND")

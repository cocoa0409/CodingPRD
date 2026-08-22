"""Shared lookup, listing and entitlement helpers for the route layer."""
import db
from constants import DEALER_CHANNELS
from errors import ApiError
from middleware import ROLE_DEALER, ROLE_HOLDER


def _lookup(collection, identifier, error_id):
    record = collection.get(identifier) if identifier is not None else None
    if record is None:
        raise ApiError(error_id, "The requested resource does not exist.")
    return record


def get_fund(identifier):
    return _lookup(db.store.funds, identifier, "ERR_FUND_NOT_FOUND")


def get_share_class(identifier):
    return _lookup(db.store.share_classes, identifier, "ERR_SHARE_CLASS_NOT_FOUND")


def get_account(identifier):
    return _lookup(db.store.accounts, identifier, "ERR_ACCOUNT_NOT_FOUND")


def get_position(identifier):
    return _lookup(db.store.positions, identifier, "ERR_POSITION_NOT_FOUND")


def get_nav_record(identifier):
    return _lookup(db.store.nav_records, identifier, "ERR_NAV_RECORD_NOT_FOUND")


def get_trade(identifier):
    return _lookup(db.store.trades, identifier, "ERR_TRADE_NOT_FOUND")


def get_distribution(identifier):
    return _lookup(db.store.distributions, identifier, "ERR_DISTRIBUTION_NOT_FOUND")


def get_payment(identifier):
    return _lookup(db.store.payments, identifier, "ERR_PAYMENT_NOT_FOUND")


def get_plan(identifier):
    return _lookup(db.store.plans, identifier, "ERR_PLAN_NOT_FOUND")


def get_registration(identifier):
    return _lookup(db.store.registrations, identifier, "ERR_REGISTRATION_NOT_FOUND")


def get_case(identifier):
    return _lookup(db.store.cases, identifier, "ERR_CASE_NOT_FOUND")


def get_reconciliation(identifier):
    return _lookup(db.store.reconciliations, identifier, "ERR_RECONCILIATION_NOT_FOUND")


def get_ledger_entry(identifier):
    return _lookup(db.store.ledger_entries, identifier, "ERR_LEDGER_ENTRY_NOT_FOUND")


def require_ownership(caller, account_id):
    """Order-of-rejection step 6."""
    if caller.role == ROLE_HOLDER and caller.user_id != account_id:
        raise ApiError("ERR_ACCOUNT_OWNERSHIP_REQUIRED",
                       "An account holder may only act on their own account.")


def require_dealer_channel(caller, account_channel):
    """Order-of-rejection step 7."""
    if caller.role == ROLE_DEALER and account_channel not in DEALER_CHANNELS:
        raise ApiError("ERR_DEALER_CHANNEL_REQUIRED",
                       "Dealer operations may only act on networked or omnibus accounts.")


def sorted_records(records):
    return sorted(records, key=lambda r: r["created_at"])


def page(records, limit, offset):
    ordered = sorted_records(records)
    total = len(ordered)
    return ordered[offset:offset + limit], total


def filter_equals(records, field, value):
    if value is None:
        return records
    return [r for r in records if r.get(field) == value]

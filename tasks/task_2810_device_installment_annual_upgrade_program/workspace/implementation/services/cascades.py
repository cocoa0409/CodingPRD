"""Cross-entity cascades: collections events, financing locks, reservation
releases, trade-in cancellations and loan-closure device effects.

Every entity a cascade reaches has its own updated_at refreshed and its own
version advanced (PRD 2.8).
"""
import clock
import db
from constants import (
    APP_APPROVED, APP_CONDITIONAL_APPROVED, APP_SUBMITTED, APP_VOIDED_BY_LOCK,
    CARRIER_ACTIVATED, CARRIER_PORT_ELIGIBLE, COVERAGE_ACTIVE, COVERAGE_SUSPENDED, CUSTOMER_ACTIVE,
    CUSTOMER_FINANCING_LOCKED, DQ_DEFAULT, DU_ACTIVATED, DU_DEACTIVATED, DU_LOCKED,
    DU_RETURN_FAILED, DU_RETURN_PENDING, DU_RETURNED, DU_UNLOCK_REQUESTED, DU_UNLOCKED,
    DU_WITH_CUSTOMER, EV_DEFAULT_DECLARED, EV_FINANCING_LOCK_APPLIED,
    EV_FINANCING_LOCK_RELEASED,
    EXPIRY_CUSTOMER_FINANCING_LOCKED, EXPIRY_SUPERSEDED_BY_NEW_REQUEST,
    LOCK_REASON_DEFAULTED_LOAN, QUOTE_ISSUED, QUOTE_SUPERSEDED, REASON_CUSTOMER_FINANCING_LOCKED,
    TI_CANCELLED, TI_DECLARED, TI_DISPUTED, TI_GRADED, TI_RECEIVED, UR_EXPIRED,
    UR_NON_TERMINAL, UR_SUPERSEDED, UR_TRADE_IN_DECLARED, UR_TRADE_IN_GRADED,
)


# --- collections audit trail ---

def add_event(loan, event_type, from_state=None, to_state=None, amount_cents=0,
              days_past_due=None):
    record = {
        "loan_id": loan["id"],
        "event_type": event_type,
        "from_state": from_state,
        "to_state": to_state,
        "days_past_due_at_event": loan["days_past_due"] if days_past_due is None else days_past_due,
        "amount_cents": amount_cents,
        "occurred_at": clock.now_iso(),
    }
    return db.insert(db.delinquency_events, record, append_only=True)


# --- device helpers ---

def device_for_loan(loan_id):
    for unit in db.values(db.device_units):
        if unit["loan_id"] == loan_id:
            return unit
    return None


def set_possession(device, possession):
    """A handset moving to RETURNED also deactivates (PRD 3.4)."""
    if device is None or device["possession_status"] == possession:
        return device
    device["possession_status"] = possession
    if possession == DU_RETURNED:
        device["returned_at"] = clock.now_iso()
        if device["activation_status"] == DU_ACTIVATED:
            device["activation_status"] = DU_DEACTIVATED
            device["activated_at"] = None
    elif possession == DU_WITH_CUSTOMER:
        device["returned_at"] = None
    db.touch(device)
    return device


def unlock_device_on_closure(loan):
    """A loan reaching PAID_OFF or ROLLED_OVER unlocks its handset outright and
    lets the carrier account go portable (PRD 3.4, 3.7)."""
    device = device_for_loan(loan["id"])
    if device is None:
        return None
    if device["unlock_status"] in (DU_LOCKED, DU_UNLOCK_REQUESTED):
        device["unlock_status"] = DU_UNLOCKED
        device["unlocked_at"] = clock.now_iso()
        db.touch(device)
        account = db.carrier_accounts.get(device["carrier_account_id"])
        if account is not None and account["activation_state"] == CARRIER_ACTIVATED:
            account["activation_state"] = CARRIER_PORT_ELIGIBLE
            db.touch(account)
    return device


# --- payoff quotes ---

def supersede_standing_quotes(loan, keep_id=None, quote_type=None):
    for quote in db.values(db.payoff_quotes):
        if quote["loan_id"] != loan["id"] or quote["status"] != QUOTE_ISSUED:
            continue
        if keep_id is not None and quote["id"] == keep_id:
            continue
        if quote_type is not None and quote["quote_type"] != quote_type:
            continue
        quote["status"] = QUOTE_SUPERSEDED
        db.touch(quote)


# --- trade-ins ---

def trade_in_for_request(request_id):
    for record in db.values(db.trade_ins):
        if record["upgrade_request_id"] == request_id:
            return record
    return None


def cancel_trade_in(trade_in):
    """The owning request ended without settling (PRD 3.9)."""
    if trade_in is None or trade_in["status"] not in (TI_DECLARED, TI_RECEIVED, TI_GRADED, TI_DISPUTED):
        return trade_in
    zero_credit = trade_in["status"] in (TI_GRADED, TI_DISPUTED)
    trade_in["status"] = TI_CANCELLED
    if zero_credit:
        trade_in["credit_final_cents"] = 0
    db.touch(trade_in)
    device = db.device_units.get(trade_in["device_unit_id"])
    if device is not None and device["possession_status"] in (
            DU_RETURN_PENDING, DU_RETURNED, DU_RETURN_FAILED):
        set_possession(device, DU_WITH_CUSTOMER)
    return trade_in


# --- upgrade reservations ---

def release_reservation(request, bump_loan_version=True):
    """Give back the capacity slot the request was holding (PRD 3.8)."""
    model = db.device_models.get(request["target_device_model_id"])
    if model is not None:
        db.touch(model)
    loan = db.loans.get(request["loan_id"])
    if loan is not None and loan["upgrade_hold_flag"]:
        loan["upgrade_hold_flag"] = False
        db.touch(loan, bump_version=bump_loan_version)
    if request["status"] in (UR_TRADE_IN_DECLARED, UR_TRADE_IN_GRADED):
        cancel_trade_in(trade_in_for_request(request["id"]))


def expire_request(request, reason, bump_loan_version=True):
    release_reservation(request, bump_loan_version=bump_loan_version)
    request["status"] = UR_EXPIRED
    request["expiry_reason"] = reason
    db.touch(request)
    return request


def supersede_request(request):
    release_reservation(request)
    request["status"] = UR_SUPERSEDED
    request["expiry_reason"] = EXPIRY_SUPERSEDED_BY_NEW_REQUEST
    db.touch(request)
    return request


# --- financing lock ---

def void_customer_applications(customer):
    for application in db.values(db.credit_applications):
        if application["customer_id"] != customer["id"]:
            continue
        if application["status"] in (APP_SUBMITTED, APP_APPROVED, APP_CONDITIONAL_APPROVED):
            application["status"] = APP_VOIDED_BY_LOCK
            application["decision_reason"] = REASON_CUSTOMER_FINANCING_LOCKED
            db.touch(application)


def expire_customer_requests(customer, bump_loan_version=True):
    for request in db.values(db.upgrade_requests):
        if request["customer_id"] != customer["id"]:
            continue
        if request["status"] in UR_NON_TERMINAL:
            expire_request(request, EXPIRY_CUSTOMER_FINANCING_LOCKED,
                           bump_loan_version=bump_loan_version)


def apply_financing_lock(customer, reason, expire_requests=False, bump_loan_version=True):
    """Lock the customer out of new financing.  Returns True when the status
    actually moved ACTIVE -> FINANCING_LOCKED."""
    moved = customer["status"] != CUSTOMER_FINANCING_LOCKED
    if moved:
        customer["status"] = CUSTOMER_FINANCING_LOCKED
        customer["financing_lock_reason"] = reason
        customer["financing_locked_at"] = clock.now_iso()
        db.touch(customer)
        void_customer_applications(customer)
        if expire_requests:
            expire_customer_requests(customer, bump_loan_version=bump_loan_version)
    return moved


def release_financing_lock(customer):
    customer["status"] = CUSTOMER_ACTIVE
    customer["financing_lock_reason"] = None
    customer["financing_locked_at"] = None
    db.touch(customer)


def release_default_lock_if_clear(customer, loan):
    """A cure out of DEFAULT returns the customer to ACTIVE once no loan of
    theirs is still in DEFAULT and the lock was a defaulted-loan lock (PRD 3.5)."""
    if customer["status"] != CUSTOMER_FINANCING_LOCKED:
        return False
    if customer["financing_lock_reason"] != LOCK_REASON_DEFAULTED_LOAN:
        return False
    for other in db.values(db.loans):
        if other["customer_id"] != customer["id"]:
            continue
        if other["id"] == loan["id"]:
            continue
        if other["delinquency_state"] == DQ_DEFAULT:
            return False
    release_financing_lock(customer)
    add_event(loan, EV_FINANCING_LOCK_RELEASED)
    return True


def declare_default(loan, from_state, bump_loan_version=True):
    """The full default side-effect set (PRD 3.6)."""
    if loan["protection_coverage_status"] == COVERAGE_ACTIVE:
        loan["protection_coverage_status"] = COVERAGE_SUSPENDED
    loan["delinquency_state"] = DQ_DEFAULT
    db.touch(loan, bump_version=bump_loan_version)
    add_event(loan, EV_DEFAULT_DECLARED, from_state=from_state, to_state=DQ_DEFAULT)
    customer = db.customers.get(loan["customer_id"])
    if customer is not None:
        moved = apply_financing_lock(customer, LOCK_REASON_DEFAULTED_LOAN,
                                     expire_requests=True,
                                     bump_loan_version=bump_loan_version)
        if moved:
            add_event(loan, EV_FINANCING_LOCK_APPLIED)

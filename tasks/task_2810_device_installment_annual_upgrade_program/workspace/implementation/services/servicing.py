"""Collections: delinquency ladder, late fees, ageing and the nightly sweep
(PRD 3.5 cure rules, 3.6 servicing run)."""
import calc
import clock
import db
import serialize
from constants import (
    COVERAGE_ACTIVE, COVERAGE_SUSPENDED, DQ_CURRENT, DQ_DEFAULT, DQ_GRACE, DQ_DELINQUENT,
    EV_CURED, EV_DELINQUENCY_ENTERED, EV_GRACE_ENTERED, EV_LATE_FEE_ASSESSED,
    EXPIRY_FULFILLMENT_WINDOW_ELAPSED, INST_PARTIALLY_PAID, INST_PAST_DUE, INST_SCHEDULED,
    LATE_FEE_CENTS, LATE_FEE_GRACE_DAYS, LOAN_ACTIVE, QUOTE_EXPIRED, QUOTE_ISSUED,
    UR_EXPIRED, UR_NON_TERMINAL, UR_RESERVING_STATUSES,
)
from services import cascades

UNSATISFIED_STATUSES = (INST_SCHEDULED, INST_PARTIALLY_PAID, INST_PAST_DUE)


def unsatisfied_installments(loan, moment):
    rows = []
    for installment in serialize.loan_installments(loan["id"]):
        if installment["status"] not in UNSATISFIED_STATUSES:
            continue
        if clock.parse_iso8601(installment["due_date"]) <= moment:
            rows.append(installment)
    return rows


def days_past_due_for(loan, moment):
    rows = unsatisfied_installments(loan, moment)
    if not rows:
        return 0
    return max(clock.whole_day_difference(moment, clock.parse_iso8601(r["due_date"]))
               for r in rows)


def is_cured(loan, moment):
    """No installment is still in arrears at or before the clock (PRD 3.5)."""
    for installment in serialize.loan_installments(loan["id"]):
        if installment["status"] not in (INST_PAST_DUE, INST_PARTIALLY_PAID):
            continue
        if clock.parse_iso8601(installment["due_date"]) <= moment:
            return False
    return True


def enter_current(loan, from_state, bump_loan_version=True):
    loan["delinquency_state"] = DQ_CURRENT
    loan["days_past_due"] = 0
    db.touch(loan, bump_version=bump_loan_version)
    cascades.add_event(loan, EV_CURED, from_state=from_state, to_state=DQ_CURRENT)
    if from_state == DQ_DEFAULT:
        if loan["protection_coverage_status"] == COVERAGE_SUSPENDED:
            loan["protection_coverage_status"] = COVERAGE_ACTIVE
            db.touch(loan, bump_version=bump_loan_version)
        customer = db.customers.get(loan["customer_id"])
        if customer is not None:
            cascades.release_default_lock_if_clear(customer, loan)


def _enter_label(loan, from_state, to_state, bump_loan_version=True):
    if to_state == DQ_CURRENT:
        enter_current(loan, from_state, bump_loan_version=bump_loan_version)
        return
    if to_state == DQ_DEFAULT:
        cascades.declare_default(loan, from_state, bump_loan_version=bump_loan_version)
        return
    loan["delinquency_state"] = to_state
    db.touch(loan, bump_version=bump_loan_version)
    event = EV_GRACE_ENTERED if to_state == DQ_GRACE else EV_DELINQUENCY_ENTERED
    cascades.add_event(loan, event, from_state=from_state, to_state=to_state)


def recompute_after_payment(loan, moment):
    """A payment either cures the loan outright or leaves the label alone
    while refreshing days_past_due (PRD 3.5)."""
    previous = loan["delinquency_state"]
    if is_cured(loan, moment):
        if previous != DQ_CURRENT:
            enter_current(loan, previous)
        else:
            loan["days_past_due"] = 0
    else:
        loan["days_past_due"] = days_past_due_for(loan, moment)


def recompute_after_reversal(loan, moment):
    """A reversal restores the arrears position the target posting had cleared,
    label included (PRD 3.5)."""
    previous = loan["delinquency_state"]
    loan["days_past_due"] = days_past_due_for(loan, moment)
    target = calc.delinquency_label(loan["days_past_due"])
    if target != previous:
        _enter_label(loan, previous, target)


def run_daily_sweep(moment):
    """POST /servicing/daily-run (PRD 3.6)."""
    active_loans = [loan for loan in db.values(db.loans) if loan["status"] == LOAN_ACTIVE]
    pre_request_states = {req["id"]: req["status"] for req in db.upgrade_requests.values()}
    pre_quote_states = {quote["id"]: quote["status"] for quote in db.payoff_quotes.values()}

    processed = 0
    transitioned = 0
    fees_assessed = 0
    defaulted = 0

    for loan in active_loans:
        processed += 1
        before_state = loan["delinquency_state"]
        before_days = loan["days_past_due"]
        before_fee = loan["outstanding_late_fee_cents"]

        overdue = unsatisfied_installments(loan, moment)
        days = 0
        if overdue:
            days = max(clock.whole_day_difference(moment, clock.parse_iso8601(r["due_date"]))
                       for r in overdue)
        loan["days_past_due"] = days

        for installment in overdue:
            own_days = clock.whole_day_difference(
                moment, clock.parse_iso8601(installment["due_date"]))
            if own_days > LATE_FEE_GRACE_DAYS and not installment["late_fee_assessed"]:
                installment["late_fee_cents"] = installment["late_fee_cents"] + LATE_FEE_CENTS
                installment["late_fee_assessed"] = True
                db.touch(installment)
                fees_assessed += LATE_FEE_CENTS
                cascades.add_event(loan, EV_LATE_FEE_ASSESSED, amount_cents=LATE_FEE_CENTS,
                                   days_past_due=days)

        for installment in overdue:
            if installment["status"] == INST_SCHEDULED and installment["paid_amount_cents"] == 0:
                installment["status"] = INST_PAST_DUE
                db.touch(installment)
            elif installment["status"] == INST_PARTIALLY_PAID and \
                    0 < installment["paid_amount_cents"] < installment["amount_due_cents"]:
                installment["status"] = INST_PAST_DUE
                db.touch(installment)

        serialize.recompute_loan_ledger(loan)

        target = calc.delinquency_label(days)
        if target != before_state:
            _enter_label(loan, before_state, target, bump_loan_version=True)
            transitioned += 1
            if target == DQ_DEFAULT:
                defaulted += 1

        if (loan["delinquency_state"] != before_state or loan["days_past_due"] != before_days
                or loan["outstanding_late_fee_cents"] != before_fee):
            db.touch(loan)

    # Retire stale paper: upgrade requests whose fulfillment window has run out.
    for request in db.values(db.upgrade_requests):
        if request["status"] not in UR_RESERVING_STATUSES:
            continue
        window_end = clock.parse_iso8601(request["fulfillment_window_end"])
        if window_end <= moment:
            cascades.expire_request(request, EXPIRY_FULFILLMENT_WINDOW_ELAPSED,
                                    bump_loan_version=False)

    for quote in db.values(db.payoff_quotes):
        if quote["status"] != QUOTE_ISSUED:
            continue
        if clock.parse_iso8601(quote["expires_at"]) <= moment:
            quote["status"] = QUOTE_EXPIRED
            db.touch(quote)

    expired_requests = sum(
        1 for request in db.upgrade_requests.values()
        if request["status"] == UR_EXPIRED and pre_request_states.get(request["id"]) in UR_NON_TERMINAL)
    expired_quotes = sum(
        1 for quote in db.payoff_quotes.values()
        if quote["status"] == QUOTE_EXPIRED and pre_quote_states.get(quote["id"]) == QUOTE_ISSUED)

    return {
        "processed_loan_count": processed,
        "transitioned_loan_count": transitioned,
        "late_fees_assessed_cents": fees_assessed,
        "defaulted_loan_count": defaulted,
        "expired_upgrade_request_count": expired_requests,
        "expired_quote_count": expired_quotes,
    }

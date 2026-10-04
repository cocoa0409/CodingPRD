"""Account servicing: transactions, promotional plans, balances, payments,
delinquency and charge-off (PRD §3.4, §3.5)."""
from flask import request

from core import auth, clock, computations, domain
from core.auth import optional_field, require_field
from core.errors import ERR_INVALID_STATE, ERR_RESOURCE_NOT_FOUND, fail
from core.store import add, store, touch
from .common import listing, single

_VALID_CHANNELS = ("IN_STORE", "DIGITAL")
_VALID_BUCKETS = ("PRINCIPAL", "PROMO_PRINCIPAL")


def _not_found(what):
    return fail(ERR_RESOURCE_NOT_FOUND, f"{what} does not exist.")


def require_account(account_id):
    account = store.accounts.get(account_id)
    if not account:
        raise _not_found("Account")
    return account


def require_plan(plan_id):
    plan = store.promo_plans.get(plan_id)
    if not plan:
        raise _not_found("PromoPlan")
    return plan


def register(app):

    # --- Transaction ------------------------------------------------------

    @app.post("/servicing/transactions")
    def create_transaction():
        _user_id, role = auth.require_role("Cardholder", "ProgramAdmin")
        payload = auth.body()
        account_id = require_field(payload, "account_id", "string")
        merchant_name = require_field(payload, "merchant_name", "string")
        amount_cents = require_field(payload, "amount_cents", "int")
        channel = auth.enum_field(payload, "transaction_channel", _VALID_CHANNELS)
        promo_requested = optional_field(payload, "promo_requested", "bool", False)

        account = require_account(account_id)
        if role == "Cardholder" and _user_id != account_id:
            raise fail("ERR_UNAUTHORIZED",
                       "A Cardholder may only act on the account named by X-User-ID.")
        program = domain.get_program_of_account(account)
        if not program:
            raise _not_found("CreditProgram")

        promo_term = optional_field(payload, "promo_term_months", "int")
        if promo_requested:
            # Term membership is evaluated before the minimum-charge floor
            # (PRD §3.4).
            if promo_term not in computations.SUPPORTED_PROMO_TERMS:
                raise fail("ERR_INVALID_PROMO_TERM",
                           "promo_term_months must be one of 6, 12, 18 or 24.")
            agreement = domain.get_agreement_of_program(program) or {}
            if amount_cents < agreement.get("minimum_charge_cents", 0):
                raise fail("ERR_PROMO_MINIMUM_CHARGE",
                           "The promotional purchase is below the agreement minimum_charge_cents.")

        # The credit check is applied to every purchase regardless of
        # promotional election (PRD §3.4): the new amount_cents added to the
        # account's current outstanding_balance_cents may not exceed the
        # account's credit_limit_cents.
        limit = account.get("credit_limit_cents", 0)
        outstanding = account.get("outstanding_balance_cents", 0)
        if outstanding + amount_cents > limit:
            raise fail("ERR_CREDIT_LIMIT_EXCEEDED",
                       "The purchase would exceed the account's credit limit.")

        if program.get("program_status") == "CLOSED":
            raise fail("ERR_PROGRAM_CLOSED",
                       "The account's program is CLOSED.")

        transaction = add("transactions", {
            "account_id": account_id,
            "merchant_name": merchant_name,
            "amount_cents": amount_cents,
            "transaction_channel": channel,
            "transaction_status": "POSTED",
            "promo_requested": promo_requested,
            "promo_term_months": promo_term,
            # Logical-clock posting instant; drives the dispute filing window.
            "_posted_at": clock.now_iso(),
        })
        if promo_requested:
            _create_promo_plan(transaction, account, program, promo_term)
        return single(transaction, 201)

    @app.get("/servicing/transactions")
    def list_transactions():
        auth.require_role("ProgramAdmin", "CardholderService", "Cardholder")
        return listing(list(store.transactions.values()),
                       {"account_id": request.args.get("account_id")})

    @app.get("/servicing/transactions/<transaction_id>")
    def read_transaction(transaction_id):
        auth.require_role("ProgramAdmin", "CardholderService", "Cardholder")
        transaction = store.transactions.get(transaction_id)
        if not transaction:
            raise _not_found("Transaction")
        return single(transaction)

    # --- Account ----------------------------------------------------------

    @app.get("/servicing/accounts")
    def list_accounts():
        auth.require_role("ProgramAdmin", "CardholderService", "Underwriter")
        return listing(list(store.accounts.values()),
                       {"program_id": request.args.get("program_id")})

    @app.get("/servicing/accounts/<account_id>")
    def read_account(account_id):
        _user_id, role = auth.require_role(
            "ProgramAdmin", "CardholderService", "Cardholder", "Underwriter")
        account = require_account(account_id)
        if role == "Cardholder" and _user_id != account_id:
            raise fail("ERR_UNAUTHORIZED",
                       "A Cardholder may only read the account named by X-User-ID.")
        return single(account)

    @app.post("/servicing/accounts/<account_id>/post-payment")
    def post_payment(account_id):
        _user_id, role = auth.require_role("Cardholder", "ProgramAdmin")
        account = require_account(account_id)
        if role == "Cardholder" and _user_id != account_id:
            raise fail("ERR_UNAUTHORIZED",
                       "A Cardholder may only pay the account named by X-User-ID.")
        payload = auth.body()
        amount = require_field(payload, "payment_amount_cents", "int")
        program = domain.get_program_of_account(account)
        if program and program.get("program_status") == "CLOSED":
            raise fail("ERR_PROGRAM_CLOSED",
                       "The account's program is CLOSED and no longer services payments.")

        due = account.get("outstanding_balance_cents", 0)
        minimum_due = computations.minimum_payment_due(account)
        status = account.get("account_status")

        _apply_payment_to_slices(account, amount)

        if status == "DELINQUENT":
            if due > 0 and amount >= due:
                account["account_status"] = "PAID_OFF"
                _zero_slices(account)
            elif amount >= minimum_due:
                account["account_status"] = "ACTIVE"
        elif status == "ACTIVE":
            if due > 0 and amount >= due:
                account["account_status"] = "PAID_OFF"
                _zero_slices(account)
        elif status == "PAID_OFF" and amount >= due and due > 0:
            _zero_slices(account)

        domain.recompute_account_balance(account)
        account["last_payment_at"] = clock.now_iso()
        touch(account)
        if program:
            domain.refresh_program(program)
        return single(account)

    @app.post("/servicing/accounts/<account_id>/schedule-payment")
    def schedule_payment(account_id):
        auth.require_role("Cardholder", "ProgramAdmin")
        account = require_account(account_id)
        payload = auth.body()
        due_date = require_field(payload, "due_date", "string")
        try:
            due_at = clock.parse(due_date)
        except ValueError:
            raise fail("ERR_INVALID_REQUEST", "due_date must be an ISO 8601 instant.")
        if due_at < clock.now():
            raise fail("ERR_PAYMENT_DUE_IN_PAST",
                       "A scheduled payment due date may not precede the logical clock.")
        store.payment_due[account_id] = clock.fmt(due_at)
        touch(account)
        return single(account)

    @app.post("/servicing/accounts/<account_id>/charge-off")
    def charge_off(account_id):
        auth.require_role("ProgramAdmin")
        account = require_account(account_id)
        if account["account_status"] != "DELINQUENT":
            raise fail(ERR_INVALID_STATE, "Only a DELINQUENT account can be charged off.")
        due_text = store.payment_due.get(account_id)
        days_past = 0
        if due_text:
            days_past = clock.days_between(clock.parse(due_text), clock.now())
        if days_past < computations.CHARGE_OFF_WINDOW_DAYS:
            raise fail("ERR_CHARGEOFF_WINDOW_NOT_MET",
                       "The account's payment due date is not yet 180 logical days past.")
        # Hop 1: the account status change is the chain origin.
        account["account_status"] = "CHARGED_OFF"
        touch(account)
        # Hop 2: caused by hop 1 — every plan on the account expires at zero.
        domain.expire_plans_on_account(account)
        # Hop 3: caused by hop 2 — the program's exposure, receivable and
        # profitability are recomputed.
        program = domain.get_program_of_account(account)
        domain.refresh_program(program)
        return single(account)

    @app.post("/servicing/accounts/<account_id>/balances")
    def create_balance(account_id):
        auth.require_role("ProgramAdmin")
        account = require_account(account_id)
        payload = auth.body()
        principal = require_field(payload, "principal_balance_cents", "int")
        bucket = auth.enum_field(payload, "balance_bucket", _VALID_BUCKETS)
        row = add("scheduled_balances", {
            "account_id": account_id,
            "principal_balance_cents": principal,
            "balance_bucket": bucket,
            "recorded_at": clock.now_iso(),
        })
        domain.recompute_account_balance(account)
        program = domain.get_program_of_account(account)
        domain.refresh_program(program)
        return single(row, 201)

    @app.get("/servicing/accounts/<account_id>/balances")
    def list_account_balances(account_id):
        auth.require_role("ProgramAdmin", "CardholderService", "Cardholder", "Underwriter")
        require_account(account_id)
        return listing(domain.balances_of_account(account_id))

    @app.get("/servicing/balances")
    def list_balances():
        auth.require_role("ProgramAdmin", "CardholderService", "Underwriter")
        return listing(list(store.scheduled_balances.values()),
                       {"account_id": request.args.get("account_id")})

    @app.get("/servicing/accounts/<account_id>/loyalty")
    def account_loyalty(account_id):
        _user_id, role = auth.require_role("Cardholder", "CardholderService", "ProgramAdmin")
        account = require_account(account_id)
        if role == "Cardholder" and _user_id != account_id:
            raise fail("ERR_UNAUTHORIZED",
                       "A Cardholder may only read the account named by X-User-ID.")
        postings = [p for p in store.benefit_postings.values()
                    if p.get("account_id") == account_id]
        last_posted = max((p.get("posted_at") for p in postings), default=None)
        return single({
            "linked_loyalty_balance": account.get("linked_loyalty_balance", 0),
            "posting_count": len(postings),
            "last_posted_at": last_posted,
        })

    # --- PromoPlan --------------------------------------------------------

    @app.get("/servicing/promo-plans")
    def list_promo_plans():
        auth.require_role("ProgramAdmin", "CardholderService", "Underwriter")
        return listing(list(store.promo_plans.values()), {
            "program_id": request.args.get("program_id"),
            "account_id": request.args.get("account_id"),
            "transaction_id": request.args.get("transaction_id"),
        })

    @app.get("/servicing/promo-plans/<plan_id>")
    def read_promo_plan(plan_id):
        auth.require_role("ProgramAdmin", "CardholderService", "Cardholder", "Underwriter")
        return single(require_plan(plan_id))

    @app.post("/servicing/promo-plans/<plan_id>/expire")
    def expire_promo_plan(plan_id):
        auth.require_role("ProgramAdmin")
        plan = require_plan(plan_id)
        if plan["plan_status"] != "ACTIVE":
            raise fail(ERR_INVALID_STATE, "Only an ACTIVE plan can expire.")
        if not domain.is_plan_expired(plan):
            raise fail("ERR_PROMO_NOT_EXPIRED",
                       "The logical clock has not reached the plan's promo_expires_at.")
        domain.expire_plan(plan)
        touch(plan)
        domain.refresh_plan_exposure(plan)
        return single(plan)

    @app.post("/servicing/promo-plans/<plan_id>/reopen")
    def reopen_promo_plan(plan_id):
        auth.require_role("CardholderService")
        plan = require_plan(plan_id)
        if plan["plan_status"] != "EXPIRED":
            raise fail(ERR_INVALID_STATE, "Only an EXPIRED plan can be reopened.")
        program = domain.get_program_of_plan(plan)
        agreement = domain.get_agreement_of_program(program) or {}
        plan["plan_status"] = "ACTIVE"
        plan["subsidy_at_risk_cents"] = domain.compute_subsidy_at_risk(plan, agreement)
        touch(plan)
        domain.refresh_plan_exposure(plan)
        return single(plan)


def _create_promo_plan(transaction, account, program, promo_term):
    agreement = domain.get_agreement_of_program(program) or {}
    program_id = program["id"]
    principal = transaction["amount_cents"]
    start = clock.now()
    expires = start + _term_span(promo_term)
    qualifying = principal >= agreement.get("minimum_charge_cents", 0)
    plan = add("promo_plans", {
        "program_id": program_id,
        "account_id": account["id"],
        "transaction_id": transaction["id"],
        "promo_term_months": promo_term,
        "promo_principal_cents": principal,
        "qualifying_flag": qualifying,
        "subsidy_at_application_cents": computations.subsidy_at_application(principal, promo_term),
        "subsidy_at_risk_cents": 0,
        "net_subsidy_cents": None,
        "promo_start_at": clock.fmt(start),
        "promo_expires_at": clock.fmt(expires),
        "plan_status": "ACTIVE",
    })
    plan["subsidy_at_risk_cents"] = domain.compute_subsidy_at_risk(plan, agreement)
    domain.refresh_plan_exposure(plan)
    return plan


def _term_span(months):
    from datetime import timedelta
    return timedelta(days=months * 30)


def _apply_payment_to_slices(account, amount):
    remaining = amount
    for row in sorted(domain.balances_of_account(account["id"]),
                      key=lambda r: r.get("created_at", "")):
        if remaining <= 0:
            break
        applied = min(row["principal_balance_cents"], remaining)
        row["principal_balance_cents"] -= applied
        remaining -= applied


def _zero_slices(account):
    for row in domain.balances_of_account(account["id"]):
        row["principal_balance_cents"] = 0
"""Dispute handling branded as the retailer, with the three-hop exposure and
loyalty clawback cascades (PRD §3.8)."""
from flask import request

from core import auth, clock, computations, domain
from core.auth import require_field
from core.errors import ERR_INVALID_STATE, ERR_RESOURCE_NOT_FOUND, fail
from core.store import add, store, touch
from .common import listing, single

_VALID_REASONS = ("FRAUD", "GOODS_NOT_RECEIVED", "UNAUTHORIZED",
                  "DUPLICATE_CHARGE", "SERVICE_NOT_RENDERED")
_VALID_OUTCOMES = ("CARDHOLDER", "MERCHANT")


def _not_found(what):
    return fail(ERR_RESOURCE_NOT_FOUND, f"{what} does not exist.")


def register(app):

    @app.post("/servicing/disputes")
    def create_dispute():
        _user_id, role = auth.require_role("CardholderService", "Cardholder")
        payload = auth.body()
        transaction_id = require_field(payload, "transaction_id", "string")
        account_id = require_field(payload, "account_id", "string")
        reason = auth.enum_field(payload, "dispute_reason", _VALID_REASONS)

        transaction = store.transactions.get(transaction_id)
        if not transaction:
            raise _not_found("Transaction")
        account = store.accounts.get(account_id)
        if not account:
            raise _not_found("Account")
        if role == "Cardholder" and _user_id != account_id:
            raise fail("ERR_UNAUTHORIZED",
                       "A Cardholder may only dispute on the account named by X-User-ID.")

        # Duplicate-dispute check precedes the filing-window check (PRD §3.8).
        for case in store.disputes.values():
            if (case.get("transaction_id") == transaction_id
                    and case.get("case_status") in ("OPEN", "UNDER_REVIEW")):
                raise fail("ERR_DISPUTE_ALREADY_OPEN",
                           "An OPEN or UNDER_REVIEW dispute already exists on this transaction.")

        program = domain.get_program_of_account(account)
        agreement = domain.get_agreement_of_program(program) if program else {}
        grace = (agreement or {}).get("dispute_grace_days", 0)
        window = computations.DISPUTE_WINDOW_DAYS + grace
        posted_at = store.transactions[transaction_id].get("_posted_at") or transaction.get("created_at")
        elapsed = clock.days_between(clock.parse(posted_at), clock.now())
        if elapsed > window:
            raise fail("ERR_DISPUTE_PERIOD_EXPIRED",
                       "The disputed purchase posted outside the filing window.")

        partner = domain.get_partner_of_account(account)
        case = add("disputes", {
            "transaction_id": transaction_id,
            "account_id": account_id,
            "dispute_reason": reason,
            "case_status": "OPEN",
            "resolution_outcome": None,
            "resolved_at": None,
            "chargeback_amount_cents": None,
            "program_exposure_delta_cents": 0,
            "servicing_brand_name": (partner or {}).get("retailer_name", ""),
        })

        # Hop 1: the transaction status change is the chain origin.
        transaction["transaction_status"] = "DISPUTED"
        transaction["updated_at"] = clock.now_iso()
        before = program.get("free_look_exposure_cents", 0) if program else 0
        # Hop 2: caused by hop 1 — the purchase's plans drop to zero exposure.
        domain.zero_plans_on_transaction(transaction_id)
        # Hop 3: caused by hop 2 — the owning program's exposure is recomputed.
        domain.refresh_program(program)
        case["program_exposure_delta_cents"] = (
            (program.get("free_look_exposure_cents", 0) if program else 0) - before)
        return single(case, 201)

    @app.get("/servicing/disputes")
    def list_disputes():
        auth.require_role("ProgramAdmin", "CardholderService")
        return listing(list(store.disputes.values()), {
            "account_id": request.args.get("account_id"),
            "transaction_id": request.args.get("transaction_id"),
        })

    @app.get("/servicing/disputes/<case_id>")
    def read_dispute(case_id):
        auth.require_role("ProgramAdmin", "CardholderService", "Cardholder")
        case = store.disputes.get(case_id)
        if not case:
            raise _not_found("DisputeCase")
        return single(case)

    @app.post("/servicing/disputes/<case_id>/review")
    def review_dispute(case_id):
        auth.require_role("CardholderService")
        case = store.disputes.get(case_id)
        if not case:
            raise _not_found("DisputeCase")
        if case["case_status"] != "OPEN":
            raise fail(ERR_INVALID_STATE, "Only an OPEN case can move into review.")
        case["case_status"] = "UNDER_REVIEW"
        touch(case)
        return single(case)

    @app.post("/servicing/disputes/<case_id>/resolve")
    def resolve_dispute(case_id):
        auth.require_role("CardholderService")
        case = store.disputes.get(case_id)
        if not case:
            raise _not_found("DisputeCase")
        payload = auth.body()
        outcome = auth.enum_field(payload, "resolution_outcome", _VALID_OUTCOMES)
        if case["case_status"] != "UNDER_REVIEW":
            raise fail(ERR_INVALID_STATE, "Only an UNDER_REVIEW case can be resolved.")

        transaction = store.transactions.get(case["transaction_id"])
        account = store.accounts.get(case["account_id"])
        program = domain.get_program_of_account(account) if account else None
        agreement = domain.get_agreement_of_program(program) if program else {}

        if outcome == "CARDHOLDER":
            grace = (agreement or {}).get("dispute_grace_days", 0)
            posted_at = transaction.get("_posted_at") or transaction.get("created_at")
            if clock.days_between(clock.parse(posted_at), clock.now()) > (
                    computations.DISPUTE_WINDOW_DAYS + grace):
                raise fail("ERR_DISPUTE_PERIOD_EXPIRED",
                           "The disputed purchase posted outside the filing window.")
            # Hop 1: record the chargeback and land in the cardholder-favored state.
            case["chargeback_amount_cents"] = transaction["amount_cents"]
            case["case_status"] = "RESOLVED_FAVOR_CARDHOLDER"
            case["resolution_outcome"] = "CARDHOLDER"
            case["resolved_at"] = clock.now_iso()
            case["program_exposure_delta_cents"] = 0
            # Hop 2: a clawback posting is raised against the earn posting.
            _raise_clawback(transaction, account)
            # The purchase returns to POSTED, permanently chargeback-discharged;
            # its plan keeps a zero exposure rather than being recomputed.
            transaction["transaction_status"] = "POSTED"
            transaction["updated_at"] = clock.now_iso()
        else:
            case["case_status"] = "RESOLVED_FAVOR_MERCHANT"
            case["resolution_outcome"] = "MERCHANT"
            case["resolved_at"] = clock.now_iso()
            case["chargeback_amount_cents"] = None
            # Hop 1: the plan's exposure is recomputed and the purchase returns
            # to POSTED.
            before = (program.get("free_look_exposure_cents", 0) if program else 0)
            domain.restore_plans_on_transaction(transaction["id"])
            transaction["transaction_status"] = "POSTED"
            transaction["updated_at"] = clock.now_iso()
            domain.refresh_program(program)
            case["program_exposure_delta_cents"] = (
                (program.get("free_look_exposure_cents", 0) if program else 0) - before)

        touch(case)
        return single(case)

    @app.post("/servicing/disputes/<case_id>/withdraw")
    def withdraw_dispute(case_id):
        auth.require_role("CardholderService")
        case = store.disputes.get(case_id)
        if not case:
            raise _not_found("DisputeCase")
        if case["case_status"] != "OPEN":
            raise fail(ERR_INVALID_STATE, "Only an OPEN case can be withdrawn.")
        case["case_status"] = "CLOSED"
        transaction = store.transactions.get(case["transaction_id"])
        if transaction:
            transaction["transaction_status"] = "POSTED"
            transaction["updated_at"] = clock.now_iso()
        touch(case)
        return single(case)


def _raise_clawback(transaction, account):
    """Create the DISPUTE_CLAWBACK posting, reverse the earn, adjust points."""
    earns = [p for p in store.benefit_postings.values()
             if p.get("transaction_id") == transaction["id"]
             and p.get("posting_reason") == "PURCHASE_EARN"
             and p.get("posted_status") == "POSTED"]
    if not earns:
        return
    original = sorted(earns, key=lambda p: p.get("created_at", ""))[0]
    clawback_points = -1 * original["points_amount"]
    partner = domain.get_partner_of_account(account) if account else None
    add("benefit_postings", {
        "account_id": original["account_id"],
        "transaction_id": transaction["id"],
        "posting_reason": "DISPUTE_CLAWBACK",
        "points_amount": clawback_points,
        "posts_to_retailer_loyalty": original.get("posts_to_retailer_loyalty", True),
        "loyalty_program_code": original.get("loyalty_program_code"),
        "posted_status": "POSTED",
        "posted_at": clock.now_iso(),
    })
    if account is not None:
        account["linked_loyalty_balance"] = (
            account.get("linked_loyalty_balance", 0) - original["points_amount"])
    original["posted_status"] = "REVERSED"
    original["updated_at"] = clock.now_iso()
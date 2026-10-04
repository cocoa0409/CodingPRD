"""Benefit postings and the cardholder loyalty scheme (PRD §3.8)."""
from flask import request

from core import auth, clock, domain
from core.auth import optional_field, require_field
from core.errors import ERR_RESOURCE_NOT_FOUND, fail
from core.store import add, store, touch
from .common import listing, single

_VALID_REASONS = ("PURCHASE_EARN", "PROMO_BONUS", "DISPUTE_CLAWBACK")


def _not_found(what):
    return fail(ERR_RESOURCE_NOT_FOUND, f"{what} does not exist.")


def register(app):

    @app.post("/servicing/benefit-postings")
    def create_benefit_posting():
        auth.require_role("CardholderService", "ProgramAdmin")
        payload = auth.body()
        account_id = require_field(payload, "account_id", "string")
        transaction_id = require_field(payload, "transaction_id", "string")
        reason = auth.enum_field(payload, "posting_reason", _VALID_REASONS)
        points = require_field(payload, "points_amount", "int")
        posts_to_retailer = optional_field(payload, "posts_to_retailer_loyalty", "bool", True)

        account = store.accounts.get(account_id)
        if not account:
            raise _not_found("Account")
        if not store.transactions.get(transaction_id):
            raise _not_found("Transaction")

        partner = domain.get_partner_of_account(account)
        if posts_to_retailer and partner and partner.get("loyalty_link_enabled") is False:
            raise fail("ERR_LOYALTY_LINK_DISABLED",
                       "The retailer's loyalty_link_enabled is false.")

        posting = add("benefit_postings", {
            "account_id": account_id,
            "transaction_id": transaction_id,
            "posting_reason": reason,
            "points_amount": points,
            "posts_to_retailer_loyalty": posts_to_retailer,
            "loyalty_program_code": partner.get("loyalty_program_code") if posts_to_retailer else None,
            "posted_status": "POSTED",
            "posted_at": clock.now_iso(),
        })
        _apply_posting(account, points)
        return single(posting, 201)

    @app.get("/servicing/benefit-postings")
    def list_benefit_postings():
        auth.require_role("ProgramAdmin", "CardholderService", "Cardholder")
        return listing(list(store.benefit_postings.values()), {
            "account_id": request.args.get("account_id"),
            "transaction_id": request.args.get("transaction_id"),
        })

    @app.get("/servicing/benefit-postings/<posting_id>")
    def read_benefit_posting(posting_id):
        auth.require_role("ProgramAdmin", "CardholderService", "Cardholder")
        posting = store.benefit_postings.get(posting_id)
        if not posting:
            raise _not_found("BenefitPosting")
        return single(posting)


def _apply_posting(account, points):
    account["linked_loyalty_balance"] = account.get("linked_loyalty_balance", 0) + points
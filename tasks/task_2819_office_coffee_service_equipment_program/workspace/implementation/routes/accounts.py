"""Account onboarding, program posture and cancellation (PRD 3.1)."""
from flask import Blueprint

import calc
import cascade
import lookup
import serializers
import shape
from authz import (ROLE_ACCOUNT_MANAGER, ROLE_BILLING_SPECIALIST, ROLE_CUSTOMER_CONTACT,
                  ROLE_PROGRAM_ADMIN, authenticate)
from envelope import created, ok
from errors import ApiError
from store import db, insert, snapshot, touch

bp = Blueprint("accounts", __name__)

BILLING_MODES = ("CONSOLIDATED", "PER_SITE")
OPERATING_POSTURES = ("ONBOARDING", "ACTIVE", "AT_RISK")


@bp.post("/ocs/accounts")
def create_account():
    authenticate((ROLE_ACCOUNT_MANAGER,))
    fields = shape.fields()
    legal_name = fields.string("legal_name", min_len=1, max_len=200)
    billing_mode = fields.enum("billing_mode", BILLING_MODES)
    baseline = fields.integer("green_index_baseline_micros", minimum=1)
    protection_days = fields.integer("price_protection_days", required=False, minimum=0)
    if protection_days is None:
        protection_days = 90
    row = insert(db.accounts, {
        "legal_name": legal_name,
        "billing_mode": billing_mode,
        "program_posture": "ONBOARDING",
        "green_index_baseline_micros": baseline,
        "green_price_factor_bps": 10000,
        "price_protection_days": protection_days,
        "price_protection_until": None,
        "escalated_site_count": 0,
        "receivable_balance_cents": 0,
        "allied_attachment_bps": 0,
        "cancel_reason": None,
        "retrieval_due_by": None,
        "cancelled_at": None,
    })
    return created(serializers.account(row))


@bp.get("/ocs/accounts")
def list_accounts():
    authenticate((ROLE_ACCOUNT_MANAGER, ROLE_BILLING_SPECIALIST, ROLE_PROGRAM_ADMIN))
    rows = lookup.eq_filter(list(db.accounts.values()), "program_posture")
    rows = lookup.eq_filter(rows, "billing_mode")
    return lookup.listing(rows, serializers.account)


@bp.get("/ocs/accounts/<account_id>")
def read_account(account_id):
    authenticate((ROLE_ACCOUNT_MANAGER, ROLE_BILLING_SPECIALIST, ROLE_PROGRAM_ADMIN,
                  ROLE_CUSTOMER_CONTACT))
    return ok(serializers.account(lookup.account(account_id)))


@bp.post("/ocs/accounts/<account_id>/cancel")
def cancel_account(account_id):
    authenticate((ROLE_ACCOUNT_MANAGER,))
    fields = shape.fields()
    cancel_reason = fields.string("cancel_reason", min_len=1)
    retrieval_due_by = fields.instant("retrieval_due_by")
    account = lookup.account(account_id)
    if account["program_posture"] not in OPERATING_POSTURES:
        raise ApiError("ERR_ACCOUNT_NOT_OPERATING",
                       "Account posture %s cannot be cancelled." % account["program_posture"])
    cascade.cancel_account(account, cancel_reason, retrieval_due_by)
    return ok(serializers.account(account))


@bp.post("/ocs/accounts/<account_id>/recompute-allied-attachment")
def recompute_allied_attachment(account_id):
    authenticate((ROLE_BILLING_SPECIALIST, ROLE_ACCOUNT_MANAGER))
    account = lookup.account(account_id)
    before = snapshot(account)
    account["allied_attachment_bps"] = calc.allied_attachment_bps(account["id"])
    touch(account, before)
    return ok(serializers.account(account))

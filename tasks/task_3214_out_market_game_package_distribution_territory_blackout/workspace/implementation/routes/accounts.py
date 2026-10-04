"""Accounts: register, list, get, update, flag/clear commercial misuse, close."""
from flask import Blueprint, request

from db import db
from errors import (
    err_duplicate, err_invalid_request, err_already_terminal, err_invalid_state,
)
from middleware import require_roles
from paginate import parse_pagination, paginate
from response import success
from services import (
    new_resource, touch, get_or_404, resolve_market, withdraw_entitlements,
)
from validate import body_json, req_string, req_enum, req_zip, opt_string

bp = Blueprint("accounts", __name__)


def _email_taken(email, exclude_id=None):
    for a in db.accounts.values():
        if exclude_id is not None and a["id"] == exclude_id:
            continue
        if a["email"].lower() == email.lower():
            return True
    return False


@bp.post("/accounts/register")
def register_account():
    body = body_json()
    email = req_string(body, "email")
    full_name = req_string(body, "full_name")
    account_kind = req_enum(body, "account_kind", {"RESIDENTIAL", "COMMERCIAL"})
    billing_zip = req_zip(body, "billing_zip")
    if _email_taken(email):
        raise err_duplicate("Account email already exists")

    account = new_resource()
    account.update({
        "email": email,
        "full_name": full_name,
        "account_kind": account_kind,
        "billing_zip": billing_zip,
        "billing_market_code": resolve_market(billing_zip),
        "status": "ACTIVE",
        "commercial_flag_reason": None,
    })
    db.accounts[account["id"]] = account
    return success(account, status=201)


@bp.get("/accounts")
@require_roles("PlatformAdmin", "ComplianceAuditor", "SupportAgent")
def list_accounts(auth):
    limit, offset = parse_pagination()
    status = request.args.get("status")
    account_kind = request.args.get("account_kind")
    items = sorted(db.accounts.values(), key=lambda r: r["created_at"])
    if status is not None:
        items = [a for a in items if a["status"] == status]
    if account_kind is not None:
        items = [a for a in items if a["account_kind"] == account_kind]
    window, page = paginate(items, limit, offset)
    return success(window, pagination=page)


@bp.get("/accounts/<aid>")
@require_roles("PlatformAdmin", "ComplianceAuditor", "SupportAgent")
def get_account(aid, auth):
    account = get_or_404(db.accounts, aid)
    return success(account)


@bp.put("/accounts/<aid>")
@require_roles("PlatformAdmin", "SupportAgent")
def update_account(aid, auth):
    account = get_or_404(db.accounts, aid)
    body = body_json()
    full_name = opt_string(body, "full_name")
    billing_zip = None
    if body is not None and isinstance(body, dict) and body.get("billing_zip") is not None:
        billing_zip = req_zip(body, "billing_zip")
    changed = False
    if full_name is not None and full_name != account["full_name"]:
        account["full_name"] = full_name
        changed = True
    if billing_zip is not None and billing_zip != account["billing_zip"]:
        account["billing_zip"] = billing_zip
        account["billing_market_code"] = resolve_market(billing_zip)
        changed = True
    if changed:
        touch(account)
    return success(account)


@bp.post("/accounts/<aid>/flag-commercial-misuse")
@require_roles("ComplianceAuditor")
def flag_commercial_misuse(aid, auth):
    account = get_or_404(db.accounts, aid)
    if account["status"] == "CLOSED":
        raise err_already_terminal()
    if account["status"] != "ACTIVE" or account["account_kind"] != "RESIDENTIAL":
        raise err_invalid_state()
    body = body_json()
    reason = req_string(body, "reason")
    account["status"] = "SUSPENDED"
    account["commercial_flag_reason"] = reason
    touch(account)
    for sub in db.subscriptions.values():
        if sub["account_id"] == account["id"] and sub["status"] == "ACTIVE":
            if sub["entitlement_state"] != "SUSPENDED":
                sub["entitlement_state"] = "SUSPENDED"
                touch(sub)
    return success(account)


@bp.post("/accounts/<aid>/clear-commercial-flag")
@require_roles("ComplianceAuditor")
def clear_commercial_flag(aid, auth):
    account = get_or_404(db.accounts, aid)
    if account["status"] == "CLOSED":
        raise err_already_terminal()
    if account["status"] != "SUSPENDED":
        raise err_invalid_state()
    account["status"] = "ACTIVE"
    account["commercial_flag_reason"] = None
    touch(account)
    for sub in db.subscriptions.values():
        if (
            sub["account_id"] == account["id"]
            and sub["status"] == "ACTIVE"
            and sub["entitlement_state"] == "SUSPENDED"
        ):
            sub["entitlement_state"] = "ENABLED"
            touch(sub)
    return success(account)


@bp.post("/accounts/<aid>/close")
@require_roles("PlatformAdmin")
def close_account(aid, auth):
    account = get_or_404(db.accounts, aid)
    if account["status"] == "CLOSED":
        raise err_already_terminal()
    account["status"] = "CLOSED"
    touch(account)
    for sub in db.subscriptions.values():
        if sub["account_id"] == account["id"] and sub["status"] == "ACTIVE":
            sub["status"] = "CANCELLED"
            sub["cancelled_at"] = db.clock.now_iso()
            sub["entitlement_state"] = "REVOKED"
            touch(sub)
            withdraw_entitlements(sub, "SUBSCRIPTION_CANCELLED")
    return success(account)

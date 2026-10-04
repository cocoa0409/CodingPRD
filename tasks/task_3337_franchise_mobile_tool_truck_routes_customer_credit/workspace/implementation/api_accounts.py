"""Credit account reads and posture transitions."""

from flask import Blueprint, request

import auth
import clock
import envelope
import lookup
import recompute
import store
from errors import fail

bp = Blueprint("accounts", __name__, url_prefix="/retail")

ACCOUNT_ROLES = ("PlatformAdmin", "FranchiseOwner", "FranchiseManager", "CreditOfficer",
                 "Technician")
POSTURE_ACTIONS = ("SUSPEND", "REINSTATE", "CHARGE_OFF", "SETTLE_CHARGE_OFF", "CLOSE")


def _visible_accounts(user_id, role):
    rows = store.ordered(store.accounts)
    if role == "Technician":
        rows = [a for a in rows if a.get("technician_id") == user_id]
    return rows


@bp.get("/credit-accounts")
def list_accounts():
    user_id, role = auth.require(*ACCOUNT_ROLES)
    rows = _visible_accounts(user_id, role)
    technician_filter = request.args.get("technician_id")
    if role == "Technician" and technician_filter and technician_filter != user_id:
        fail("ERR_UNAUTHORIZED")
    rows = envelope.filter_query(rows, {
        "technician_id": "technician_id",
        "account_status": "account_status",
        "account_kind": "account_kind",
        "recourse_holder": "recourse_holder",
        "application_id": "application_id",
    })
    for account in rows:
        recompute.recompute_account(account)
    page, pagination = envelope.paginate(rows)
    return envelope.ok_list(page, pagination=pagination)


@bp.get("/credit-accounts/<account_id>")
def get_account(account_id):
    user_id, role = auth.require(*ACCOUNT_ROLES)
    account = lookup.account(account_id)
    if role == "Technician":
        auth.ensure_technician_self(user_id, role, account.get("technician_id"))
    recompute.recompute_account(account)
    return envelope.ok(account)


@bp.post("/credit-accounts/<account_id>/status")
def advance_account(account_id):
    auth.require("CreditOfficer", "FranchiseManager")
    account = lookup.account(account_id)
    payload = envelope.body()
    action = envelope.as_enum(payload, "action", POSTURE_ACTIONS)

    status = account.get("account_status")
    if status == "CLOSED":
        fail("ERR_ACCOUNT_ALREADY_CLOSED")

    if action == "SUSPEND":
        if status != "ACTIVE":
            fail("ERR_ACCOUNT_NOT_ACTIVE")
        if account.get("credit_available_cents", 0) != 0:
            fail("ERR_INVALID_STATE", "The account still has credit headroom.")
        store.set_field(account, "account_status", "SUSPENDED")
    elif action == "REINSTATE":
        if status == "SUSPENDED":
            if account.get("credit_available_cents", 0) <= 0:
                fail("ERR_INVALID_STATE", "The account is still fully drawn.")
        elif status == "DELINQUENT":
            if account.get("missed_payment_count", 0) != 0:
                fail("ERR_INVALID_STATE", "The account still carries missed payments.")
            if account.get("accrued_finance_charge_cents", 0) != 0:
                fail("ERR_INVALID_STATE", "The account still carries an accrued finance charge.")
        else:
            fail("ERR_ACCOUNT_NOT_SUSPENDED")
        store.set_field(account, "account_status", "ACTIVE")
    elif action == "CHARGE_OFF":
        if status not in ("ACTIVE", "DELINQUENT"):
            fail("ERR_INVALID_STATE")
        if not charge_off_due(account):
            fail("ERR_CHARGE_OFF_NOT_DUE")
        store.set_field(account, "account_status", "CHARGED_OFF")
    elif action == "SETTLE_CHARGE_OFF":
        if status != "CHARGED_OFF":
            fail("ERR_INVALID_STATE")
        if account.get("current_balance_cents", 0) != 0:
            fail("ERR_ACCOUNT_HAS_BALANCE")
        store.set_field(account, "account_status", "CLOSED")
    else:
        if account.get("current_balance_cents", 0) != 0:
            fail("ERR_ACCOUNT_HAS_BALANCE")
        store.set_field(account, "account_status", "CLOSED")

    account["account_status_changed_at"] = clock.fmt_week(clock.now())
    store.stamp(account)
    recompute.recompute_account(account)
    recompute.recompute_account_dependants(account)
    return envelope.ok(account)


def charge_off_due(account):
    changed = clock.week_start(clock.parse_utc(account.get("account_status_changed_at")))
    return calc_charge_off_due(changed, clock.current_week_start())


def calc_charge_off_due(changed_week, current_week):
    import calc
    return calc.charge_off_due(changed_week, current_week)

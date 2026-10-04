"""Weekly payment booking, collection, miss, cancel and reversal."""

from flask import Blueprint, request

import auth
import calc
import clock
import envelope
import lookup
import recompute
import store
from errors import fail

bp = Blueprint("payments", __name__, url_prefix="/retail")

SOURCES = ("TRUCK_COLLECTION", "FRANCHISOR_DRAFT", "SETTLEMENT_APPLIED")
PAYMENT_ACTIONS = ("COLLECT", "MISS", "REVERSE", "CANCEL")
READ_ROLES = ("PlatformAdmin", "FranchiseOwner", "FranchiseManager", "CreditOfficer",
              "Technician", "RouteSalesRep")


@bp.post("/credit-accounts/<account_id>/payments")
def book_payment(account_id):
    user_id, role = auth.require("RouteSalesRep")
    account = lookup.account(account_id)
    auth.ensure_owned(user_id, role, auth.account_owner_id(account))
    payload = envelope.body()
    amount_cents = envelope.as_int(payload, "amount_cents", minimum=1)
    collection_source = envelope.as_enum(payload, "collection_source", SOURCES)
    raw_week = envelope.as_str(payload, "expected_week_start")
    expected_week_start = clock.parse_utc(raw_week)
    if not clock.is_monday_midnight(expected_week_start):
        fail("ERR_PAYMENT_WEEK_IN_PAST")
    if expected_week_start < clock.current_week_start():
        fail("ERR_PAYMENT_WEEK_IN_PAST")

    payment = store.create(
        store.payments,
        account_id=account["id"],
        amount_cents=amount_cents,
        collection_source=collection_source,
        expected_week_start=clock.fmt_week(expected_week_start),
        effective_iso_week=None,
        payment_status="BOOKED",
        charge_applied_cents=0,
    )
    store.payment_applications[payment["id"]] = {"charges": {}, "principal": 0}
    recompute.recompute_account(account)
    return envelope.ok(payment, 201)


@bp.get("/credit-accounts/<account_id>/payments")
def list_payments(account_id):
    user_id, role = auth.require(*READ_ROLES)
    account = lookup.account(account_id)
    if role == "Technician":
        auth.ensure_technician_self(user_id, role, account.get("technician_id"))
    rows = [p for p in store.ordered(store.payments) if p.get("account_id") == account["id"]]
    rows = envelope.filter_query(rows, {
        "payment_status": "payment_status",
        "collection_source": "collection_source",
    })
    page, pagination = envelope.paginate(rows)
    return envelope.ok_list(page, pagination=pagination)


@bp.get("/credit-accounts/<account_id>/finance-charges")
def list_charges(account_id):
    user_id, role = auth.require("PlatformAdmin", "FranchiseOwner", "FranchiseManager",
                                 "CreditOfficer", "Technician")
    account = lookup.account(account_id)
    if role == "Technician":
        auth.ensure_technician_self(user_id, role, account.get("technician_id"))
    rows = [c for c in store.ordered(store.charges) if c.get("account_id") == account["id"]]
    rows = envelope.filter_query(rows, {"charge_status": "charge_status"})
    page, pagination = envelope.paginate(rows)
    return envelope.ok_list(page, pagination=pagination)


@bp.post("/credit-accounts/<account_id>/payments/<payment_id>/status")
def advance_payment(account_id, payment_id):
    user_id, role = auth.require("RouteSalesRep", "FranchiseManager", "CreditOfficer")
    account = lookup.account(account_id)
    payment = lookup.payment(account, payment_id)
    payload = envelope.body()
    action = envelope.as_enum(payload, "action", PAYMENT_ACTIONS)

    allowed = {
        "COLLECT": ("RouteSalesRep",),
        "MISS": ("FranchiseManager",),
        "CANCEL": ("FranchiseManager",),
        "REVERSE": ("CreditOfficer",),
    }[action]
    if role not in allowed:
        fail("ERR_UNAUTHORIZED")
    if role == "RouteSalesRep":
        auth.ensure_owned(user_id, role, auth.account_owner_id(account))
    if account.get("account_status") == "CLOSED":
        fail("ERR_ACCOUNT_ALREADY_CLOSED")

    status = payment.get("payment_status")
    if action == "COLLECT":
        _collect(account, payment)
    elif action == "MISS":
        _miss(account, payment)
    elif action == "CANCEL":
        if status != "BOOKED":
            fail("ERR_PAYMENT_NOT_BOOKED")
        store.set_field(payment, "payment_status", "CANCELLED")
    else:
        if status != "COLLECTED":
            fail("ERR_PAYMENT_NOT_COLLECTED")
        _reverse(account, payment)

    store.stamp(payment)
    recompute.recompute_account(account)
    recompute.recompute_account_dependants(account)
    return envelope.ok(payment)


def _collect(account, payment):
    status = payment.get("payment_status")
    if status == "BOOKED":
        if account.get("account_status") not in ("ACTIVE", "SUSPENDED", "DELINQUENT"):
            fail("ERR_ACCOUNT_NOT_ACTIVE")
    elif status == "MISSED":
        if account.get("account_status") != "DELINQUENT":
            fail("ERR_ACCOUNT_NOT_DELINQUENT")
    else:
        fail("ERR_PAYMENT_NOT_BOOKED")
    if payment.get("amount_cents", 0) <= 0:
        fail("ERR_INVALID_REQUEST", "amount_cents must be a positive integer.")

    current_week = clock.fmt_week(clock.current_week_start())
    open_charges = sorted(
        [c for c in store.charges.values()
         if c.get("account_id") == account["id"] and c.get("charge_status") == "OPEN"],
        key=lambda c: (c.get("accrual_iso_week") or "", c.get("accrual_seq", 0),
                       c.get("created_at") or ""),
    )
    applied, principal_reduction, takes = calc.payment_allocation(
        payment.get("amount_cents", 0), open_charges)
    for charge_id, amount in takes:
        charge = store.charges[charge_id]
        charge["collection_applied_cents"] += amount
        if charge["collection_applied_cents"] >= charge["charge_amount_cents"]:
            charge["charge_status"] = "CLOSED"
            charge["charge_resolved_iso_week"] = current_week
        store.stamp(charge)
    store.payment_applications[payment["id"]] = {
        "charges": {cid: amt for cid, amt in takes},
        "principal": principal_reduction,
    }
    account["principal_balance_cents"] = account.get("principal_balance_cents", 0) - principal_reduction
    store.set_field(payment, "payment_status", "COLLECTED")
    store.set_field(payment, "effective_iso_week", current_week)
    store.set_field(payment, "charge_applied_cents", applied)
    recompute.recompute_account(account)
    if account.get("account_status") == "SUSPENDED" and account.get("credit_available_cents", 0) > 0:
        store.set_field(account, "account_status", "ACTIVE")
        account["account_status_changed_at"] = clock.fmt_week(clock.now())


def _miss(account, payment):
    if payment.get("payment_status") != "BOOKED":
        fail("ERR_PAYMENT_NOT_BOOKED")
    if account.get("account_status") not in ("ACTIVE", "SUSPENDED"):
        fail("ERR_INVALID_STATE")
    expected = clock.parse_utc(payment.get("expected_week_start"))
    if expected >= clock.current_week_start():
        fail("ERR_INVALID_STATE", "The booking is not yet overdue.")
    store.set_field(payment, "payment_status", "MISSED")
    store.set_field(payment, "effective_iso_week", None)
    store.set_field(account, "account_status", "DELINQUENT")
    account["account_status_changed_at"] = clock.fmt_week(clock.now())
    recompute.recompute_account(account)


def _reverse(account, payment):
    ledger = store.payment_applications.get(payment["id"], {"charges": {}, "principal": 0})
    for charge_id, amount in ledger.get("charges", {}).items():
        charge = store.charges.get(charge_id)
        if charge is None:
            continue
        charge["collection_applied_cents"] = max(0, charge["collection_applied_cents"] - amount)
        if charge["collection_applied_cents"] == 0:
            charge["charge_status"] = "OPEN"
            charge["charge_resolved_iso_week"] = None
        store.stamp(charge)
    account["principal_balance_cents"] = account.get("principal_balance_cents", 0) + ledger.get("principal", 0)
    store.set_field(payment, "payment_status", "REVERSED")
    store.payment_applications[payment["id"]] = {"charges": {}, "principal": 0}
    recompute.recompute_account(account)

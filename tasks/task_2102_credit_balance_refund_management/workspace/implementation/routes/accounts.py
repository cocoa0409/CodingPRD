"""Patient accounts and the ledger spine (PRD 3.1)."""
from flask import Blueprint, request

import auth
import cascade
import db
import derive
import response
import validation as v
from errors import ApiError

bp = Blueprint("accounts", __name__)


@bp.post("/patient-accounts")
@auth.require(auth.SYSTEM_ADMIN, auth.CREDIT_ANALYST)
def create_account():
    data = v.body()
    # rank 4 - body foreign keys
    v.fk_exists("payer", data, "primary_payer_id")
    # rank 6 - body shape
    account_number = v.req_str(data, "account_number")
    mrn = v.req_str(data, "mrn")
    patient_name = v.req_str(data, "patient_name")
    guarantor_state_code = v.req_enum(data, "guarantor_state_code", v.STATE_CODES)
    primary_payer_id = v.req_str(data, "primary_payer_id")
    financial_class = v.req_enum(data, "financial_class", v.FINANCIAL_CLASSES)
    discharge_date = v.opt_dt(data, "discharge_date")
    # rank 30 - account_number uniqueness
    for existing in db.patient_accounts.values():
        if existing["account_number"] == account_number:
            raise ApiError("ERR_DUPLICATE_ACCOUNT_NUMBER")

    row = db.base_row()
    row.update({
        "account_number": account_number,
        "mrn": mrn,
        "patient_name": patient_name,
        "guarantor_state_code": guarantor_state_code,
        "primary_payer_id": primary_payer_id,
        "financial_class": financial_class,
        "discharge_date": discharge_date,
        "status": "OPEN",
    })
    db.patient_accounts[row["id"]] = row
    return response.ok(derive.patient_account(row), 201)


@bp.get("/patient-accounts")
@auth.require(*auth.ALL_ROLES)
def list_accounts():
    rows = db.ordered(list(db.patient_accounts.values()))
    primary_payer_id = request.args.get("primary_payer_id")
    if primary_payer_id:
        rows = [r for r in rows if r["primary_payer_id"] == primary_payer_id]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return response.page(rows, derive.patient_account)


@bp.get("/patient-accounts/<account_id>")
@auth.require(*auth.ALL_ROLES)
def read_account(account_id):
    return response.ok(derive.patient_account(v.must_exist("account", account_id)))


@bp.post("/patient-accounts/<account_id>/status")
@auth.require(auth.SYSTEM_ADMIN)
def set_account_status(account_id):
    account = v.must_exist("account", account_id)            # rank 3
    data = v.body()
    target = v.req_enum(data, "status", v.ACCOUNT_STATUSES)  # rank 6
    # rank 47 - an account being closed carries no open credit liability
    if target == "CLOSED" and derive.account_credit_balance_cents(account_id) != 0:
        raise ApiError("ERR_ACCOUNT_HAS_OPEN_CREDIT")

    current = account["status"]
    legal = {("OPEN", "BAD_DEBT"), ("OPEN", "CLOSED"), ("BAD_DEBT", "OPEN")}
    if (current, target) not in legal:
        raise ApiError("ERR_INVALID_REQUEST",
                       "An account cannot move from %s to %s." % (current, target))
    account["status"] = target
    db.touch(account)
    return response.ok(derive.patient_account(account))


@bp.post("/patient-accounts/<account_id>/transactions")
@auth.require(auth.CREDIT_ANALYST, auth.SYSTEM_ADMIN)
def post_transaction(account_id):
    account = v.must_exist("account", account_id)   # rank 3
    data = v.body()
    v.fk_exists("payer", data, "payer_id")          # rank 4
    # rank 6 - only CHARGE / PAYMENT / CONTRACTUAL_ADJUSTMENT may be posted here
    txn_type = v.req_enum(data, "txn_type", v.POSTABLE_TXN_TYPES)
    amount_cents = v.req_int(data, "amount_cents")
    source = v.req_enum(data, "source", v.TXN_SOURCES)
    payer_id = v.opt_str(data, "payer_id")
    effective_at = v.opt_dt(data, "effective_at")
    remark = v.opt_str(data, "remark")
    # rank 37 - payer_id present exactly when source == PAYER
    if source == "PAYER" and not payer_id:
        raise ApiError("ERR_TRANSACTION_PAYER_REQUIRED")
    if source != "PAYER" and payer_id:
        raise ApiError("ERR_TRANSACTION_PAYER_REQUIRED")

    row = cascade.post_transaction(
        account_id=account_id,
        txn_type=txn_type,
        amount_cents=amount_cents,
        source=source,
        payer_id=payer_id,
        remark=remark,
        effective_at=effective_at,
    )
    db.touch(account)
    return response.ok(derive.account_transaction(row), 201)


@bp.get("/account-transactions")
@auth.require(*auth.ALL_ROLES)
def list_transactions():
    rows = db.ordered(list(db.account_transactions.values()))
    account_id = request.args.get("account_id")
    if account_id:
        rows = [r for r in rows if r["account_id"] == account_id]
    payer_id = request.args.get("payer_id")
    if payer_id:
        rows = [r for r in rows if r["payer_id"] == payer_id]
    reversal_of = request.args.get("reversal_of_transaction_id")
    if reversal_of:
        rows = [r for r in rows if r["reversal_of_transaction_id"] == reversal_of]
    txn_type = request.args.get("txn_type")
    if txn_type:
        rows = [r for r in rows if r["txn_type"] == txn_type]
    return response.page(rows, derive.account_transaction)


@bp.get("/account-transactions/<transaction_id>")
@auth.require(*auth.ALL_ROLES)
def read_transaction(transaction_id):
    return response.ok(derive.account_transaction(v.must_exist("transaction", transaction_id)))


@bp.post("/account-transactions/<transaction_id>/reverse")
@auth.require(auth.CREDIT_ANALYST)
def reverse_transaction(transaction_id):
    target = v.must_exist("transaction", transaction_id)   # rank 3
    data = v.body()
    remark = v.opt_str(data, "remark")                     # rank 6
    # rank 16 - already reversed, or itself a REVERSAL row
    if derive.txn_is_reversed(target) or target["txn_type"] == "REVERSAL" \
            or target["reversal_of_transaction_id"] is not None:
        raise ApiError("ERR_TRANSACTION_ALREADY_REVERSED")

    row = cascade.reverse_transaction(target, remark=remark)
    return response.ok(derive.account_transaction(row), 201)

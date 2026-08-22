"""Credit balance identification, aging, attribution and write-off
(PRD 3.2, 3.4)."""
from flask import Blueprint, request

import auth
import calc
import cascade
import clock
import db
import derive
import response
import validation as v
from errors import ApiError

bp = Blueprint("credit_balances", __name__)


@bp.post("/credit-balances/identify-sweep")
@auth.require(auth.CREDIT_ANALYST)
def identify_sweep():
    data = v.body()
    account_ids = v.opt_str_array(data, "account_ids")   # rank 6

    now = clock.now()
    pool = db.ordered(list(db.patient_accounts.values()))
    if account_ids is not None:
        named = set(account_ids)
        pool = [a for a in pool if a["id"] in named]

    created = []
    for account in pool:
        if account["status"] not in ("OPEN", "BAD_DEBT"):
            continue
        if derive.account_balance_cents(account["id"]) > -calc.CREDIT_IDENTIFICATION_FLOOR_CENTS:
            continue
        blocked = any(cb["status"] in derive.SWEEP_BLOCKING_STATUSES
                      for cb in db.credit_balances_for_account(account["id"]))
        if blocked:
            continue
        row = db.base_row()
        row.update({
            "account_id": account["id"],
            "payer_id": account["primary_payer_id"],
            "credit_amount_cents": -derive.account_balance_cents(account["id"]),
            "identified_at": now,
            "attribution_method": None,
            "attribution": None,
            "patient_portion_cents": 0,
            "payer_portion_cents": 0,
            "status": "IDENTIFIED",
        })
        db.credit_balances[row["id"]] = row
        created.append(row)

    skipped_account_count = 0
    if account_ids is not None:
        created_accounts = set(c["account_id"] for c in created)
        skipped_account_count = len([a for a in account_ids if a not in created_accounts])

    return response.ok({
        "identified_count": len(created),
        "credit_balance_ids": [c["id"] for c in created],
        "skipped_account_count": skipped_account_count,
    })


@bp.get("/credit-balances")
@auth.require(*auth.ALL_ROLES)
def list_credit_balances():
    rows = db.ordered(list(db.credit_balances.values()))
    account_id = request.args.get("account_id")
    if account_id:
        rows = [r for r in rows if r["account_id"] == account_id]
    payer_id = request.args.get("payer_id")
    if payer_id:
        rows = [r for r in rows if r["payer_id"] == payer_id]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    bucket = request.args.get("aging_bucket")
    if bucket:
        rows = [r for r in rows if derive.aging_bucket(derive.cb_aging_days(r)) == bucket]
    return response.page(rows, derive.credit_balance)


@bp.get("/credit-balances/<credit_balance_id>")
@auth.require(*auth.ALL_ROLES)
def read_credit_balance(credit_balance_id):
    return response.ok(derive.credit_balance(v.must_exist("credit_balance", credit_balance_id)))


@bp.post("/credit-balances/<credit_balance_id>/start-review")
@auth.require(auth.CREDIT_ANALYST)
def start_review(credit_balance_id):
    cb = v.must_exist("credit_balance", credit_balance_id)   # rank 3
    if cb["status"] != "IDENTIFIED":                         # rank 8
        raise ApiError("ERR_CREDIT_BALANCE_INVALID_STATE")
    cb["status"] = "UNDER_REVIEW"
    db.touch(cb)
    return response.ok(derive.credit_balance(cb))


@bp.post("/credit-balances/<credit_balance_id>/attribute")
@auth.require(auth.CREDIT_ANALYST)
def attribute(credit_balance_id):
    cb = v.must_exist("credit_balance", credit_balance_id)                    # rank 3
    data = v.body()
    method = v.req_enum(data, "attribution_method", v.ATTRIBUTION_METHODS)    # rank 6
    if cb["status"] != "UNDER_REVIEW":                                        # rank 8
        raise ApiError("ERR_CREDIT_BALANCE_INVALID_STATE")

    patient_portion, payer_portion, attribution = calc.attribution_split(cb, method)
    cb["attribution_method"] = method
    cb["patient_portion_cents"] = patient_portion
    cb["payer_portion_cents"] = payer_portion
    cb["attribution"] = attribution
    cb["status"] = "ATTRIBUTED"
    db.touch(cb)

    payer = db.payers.get(cb["payer_id"])
    if payer is not None and payer["payer_type"] == "MEDICARE" and payer_portion > 0:
        ob = db.base_row()
        ob.update({
            "credit_balance_id": cb["id"],
            "payer_id": cb["payer_id"],
            "identified_at": cb["identified_at"],
            "due_at": clock.add_days(cb["identified_at"], calc.MEDICARE_REPAYMENT_WINDOW_DAYS),
            "reportable_amount_cents": payer_portion,
            "days_elapsed": 0,
            "days_late": 0,
            "penalty_cents": 0,
            "report_reference": None,
            "reported_at": None,
            "satisfied_at": None,
            "satisfaction_mode": None,
            "state": "OPEN",
        })
        derive.refresh_obligation(ob)
        db.medicare_obligations[ob["id"]] = ob

    return response.ok(derive.credit_balance(cb))


@bp.post("/credit-balances/<credit_balance_id>/write-off")
@auth.require(auth.COMPLIANCE_OFFICER)
def write_off(credit_balance_id):
    cb = v.must_exist("credit_balance", credit_balance_id)   # rank 3
    data = v.body()
    v.req_str(data, "reason_code")                           # rank 6
    if cb["status"] != "ATTRIBUTED":                         # rank 8
        raise ApiError("ERR_CREDIT_BALANCE_INVALID_STATE")
    # rank 20 - no Medicare obligation still OPEN or LATE
    for ob in db.obligations_for_credit_balance(cb["id"]):
        if ob["state"] in ("OPEN", "LATE"):
            raise ApiError("ERR_MEDICARE_OBLIGATION_OPEN")
    # rank 45 - de-minimis ceiling
    if derive.cb_outstanding_cents(cb) > calc.WRITE_OFF_MAX_CENTS:
        raise ApiError("ERR_WRITE_OFF_LIMIT_EXCEEDED")

    cb["status"] = "WRITTEN_OFF"
    db.touch(cb)
    cascade.settle_obligations_by_write_off(cb)
    return response.ok(derive.credit_balance(cb))

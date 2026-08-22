"""Unclaimed property: dormancy, due diligence and remittance (PRD 3.12)."""
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

bp = Blueprint("escheatment", __name__)


@bp.post("/escheatment-records")
@auth.require(auth.COMPLIANCE_OFFICER)
def create_record():
    data = v.body()
    v.fk_exists("check", data, "check_disbursement_id")                 # rank 4
    check_disbursement_id = v.req_str(data, "check_disbursement_id")    # rank 6
    basis = v.opt_enum(data, "basis", v.ESCHEAT_BASES, "ISSUE_DATE")
    chk = db.check_disbursements[check_disbursement_id]
    if chk["state"] != "STALE":                                         # rank 11
        raise ApiError("ERR_CHECK_INVALID_STATE")
    if db.escheatment_for_check(chk["id"]) is not None:                 # rank 33
        raise ApiError("ERR_ESCHEATMENT_ALREADY_EXISTS")

    state_code, dormancy_days, start_at, due_at, open_at = calc.dormancy_clock(chk, basis)
    row = db.base_row()
    row.update({
        "check_disbursement_id": check_disbursement_id,
        "basis": basis,
        "state_code": state_code,
        "dormancy_days": dormancy_days,
        "dormancy_start_at": start_at,
        "escheat_due_at": due_at,
        "due_diligence_open_at": open_at,
        "contact_method": None,
        "due_diligence_sent_at": None,
        "remitted_amount_cents": 0,
        "claimed_at": None,
        "state": "DORMANT",
    })
    db.escheatment_records[row["id"]] = row
    return response.ok(derive.escheatment_record(row), 201)


@bp.get("/escheatment-records")
@auth.require(*auth.ALL_ROLES)
def list_records():
    rows = db.ordered(list(db.escheatment_records.values()))
    for name in ("check_disbursement_id", "state"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r[name] == value]
    return response.page(rows, derive.escheatment_record)


@bp.get("/escheatment-records/<record_id>")
@auth.require(*auth.ALL_ROLES)
def read_record(record_id):
    return response.ok(derive.escheatment_record(v.must_exist("escheatment", record_id)))


@bp.post("/escheatment-records/<record_id>/due-diligence")
@auth.require(auth.COMPLIANCE_OFFICER)
def due_diligence(record_id):
    rec = v.must_exist("escheatment", record_id)                          # rank 3
    data = v.body()
    contact_method = v.req_enum(data, "contact_method", v.CONTACT_METHODS)  # rank 6
    if rec["state"] != "DORMANT":                                         # rank 14
        raise ApiError("ERR_ESCHEATMENT_INVALID_STATE")
    if clock.now() < rec["due_diligence_open_at"]:                        # rank 23
        raise ApiError("ERR_DUE_DILIGENCE_TOO_EARLY")

    rec["state"] = "DUE_DILIGENCE_SENT"
    rec["contact_method"] = contact_method
    rec["due_diligence_sent_at"] = clock.now()
    db.touch(rec)
    return response.ok(derive.escheatment_record(rec))


@bp.post("/escheatment-records/<record_id>/remit")
@auth.require(auth.COMPLIANCE_OFFICER)
def remit(record_id):
    rec = v.must_exist("escheatment", record_id)               # rank 3
    if rec["state"] in ("CLAIMED", "REMITTED", "EXEMPT"):      # rank 14
        raise ApiError("ERR_ESCHEATMENT_INVALID_STATE")
    if rec["due_diligence_sent_at"] is None:                   # rank 21
        raise ApiError("ERR_DUE_DILIGENCE_REQUIRED")
    if clock.now() < rec["escheat_due_at"]:                    # rank 22
        raise ApiError("ERR_DORMANCY_NOT_ELAPSED")

    chk = db.check_disbursements.get(rec["check_disbursement_id"])
    rec["state"] = "REMITTED"
    rec["remitted_amount_cents"] = int(chk["net_check_amount_cents"]) if chk else 0
    db.touch(rec)

    if chk is not None:
        # hop 1 - the check
        chk["state"] = "ESCHEATED"
        db.touch(chk)
        # hop 2 - the credit balance and its ledger posting
        req = db.refund_requests.get(chk["refund_request_id"])
        cb = db.credit_balances.get(req["credit_balance_id"]) if req else None
        if cb is not None:
            cascade.post_transaction(
                account_id=cb["account_id"],
                txn_type="ESCHEAT_REMITTANCE",
                amount_cents=int(chk["net_check_amount_cents"]),
                source="SYSTEM",
                remark="Escheat remittance for check %s" % (chk["check_number"] or chk["id"]),
            )
            if cb["status"] == "REFUNDED":
                cb["status"] = "ESCHEATED"
                db.touch(cb)
    return response.ok(derive.escheatment_record(rec))

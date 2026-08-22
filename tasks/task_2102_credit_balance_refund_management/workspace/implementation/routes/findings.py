"""Root-cause findings (PRD 3.3)."""
from flask import Blueprint, g, request

import auth
import db
import derive
import response
import validation as v

bp = Blueprint("findings", __name__)


@bp.post("/root-cause-findings")
@auth.require(auth.CREDIT_ANALYST)
def create_finding():
    data = v.body()
    cb = v.fk_exists("credit_balance", data, "credit_balance_id")   # rank 4
    # rank 6 - body shape
    credit_balance_id = v.req_str(data, "credit_balance_id")
    cause_code = v.req_enum(data, "cause_code", v.CAUSE_CODES)
    corrective_action = v.req_enum(data, "corrective_action", v.CORRECTIVE_ACTIONS)
    narrative = v.req_str(data, "narrative")
    evidence_transaction_ids = v.opt_str_array(data, "evidence_transaction_ids", default=[])
    confirmed = v.opt_bool(data, "confirmed", False)

    row = db.base_row()
    row.update({
        "credit_balance_id": credit_balance_id,
        "cause_code": cause_code,
        "corrective_action": corrective_action,
        "evidence_transaction_ids": evidence_transaction_ids,
        "narrative": narrative,
        "analyst_user_id": g.user_id,
        "confirmed": confirmed,
    })
    db.root_cause_findings[row["id"]] = row
    if cb is not None:
        db.touch(cb)
    return response.ok(derive.root_cause_finding(row), 201)


@bp.get("/root-cause-findings")
@auth.require(*auth.ALL_ROLES)
def list_findings():
    rows = db.ordered(list(db.root_cause_findings.values()))
    credit_balance_id = request.args.get("credit_balance_id")
    if credit_balance_id:
        rows = [r for r in rows if r["credit_balance_id"] == credit_balance_id]
    cause_code = request.args.get("cause_code")
    if cause_code:
        rows = [r for r in rows if r["cause_code"] == cause_code]
    confirmed = request.args.get("confirmed")
    if confirmed is not None and confirmed != "":
        want = confirmed.lower() == "true"
        rows = [r for r in rows if bool(r["confirmed"]) == want]
    return response.page(rows, derive.root_cause_finding)


@bp.get("/root-cause-findings/<finding_id>")
@auth.require(*auth.ALL_ROLES)
def read_finding(finding_id):
    return response.ok(derive.root_cause_finding(v.must_exist("finding", finding_id)))

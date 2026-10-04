"""Gross receipts reports and franchise fee statements."""
from decimal import Decimal

from flask import Blueprint, request

from db import store
from errors import err, not_found
from helpers import (new_entity, serialize, paginate, require_fields, req_int,
                     round_half_up, touch)
from middleware import require_role, require_read_role
from response import ok
from routes_contracts import get_contract, require_operational

bp = Blueprint("finance", __name__)


def get_report(cid, rid):
    r = store.receipts_reports.get(rid)
    if not r or r["contract_id"] != cid:
        raise not_found("report")
    return r


def get_statement(cid, sid):
    s = store.fee_statements.get(sid)
    if not s or s["contract_id"] != cid:
        raise not_found("statement")
    return s


def _valid_period(p):
    if not isinstance(p, str) or len(p) != 7 or p[4] != "-":
        return False
    try:
        y, m = int(p[:4]), int(p[5:7])
    except ValueError:
        return False
    return 2000 <= y and 1 <= m <= 12


# ----- Receipts reports -----

@bp.post("/contracts/<cid>/receipts-reports")
def create_report(cid):
    uid, role = require_role("ConcessionerAccountant")
    c = get_contract(cid)
    body = request.get_json(silent=True)
    require_fields(body, ["period_month", "service_line_id", "gross_receipts_cents",
                          "expected_contract_version"])
    sl = store.service_lines.get(body["service_line_id"])
    if not sl or sl["contract_id"] != cid:
        raise not_found("service_line")
    require_operational(c)
    if not _valid_period(body["period_month"]):
        raise err("ERR_INVALID_REQUEST", 400, "period_month must be YYYY-MM")
    req_int(body, "gross_receipts_cents", minimum=0)
    if sl["status"] != "AUTHORIZED":
        raise err("ERR_SERVICE_LINE_SUSPENDED", 409, "Service line not authorized")
    for r in store.receipts_reports.values():
        if (r["contract_id"] == cid and r["service_line_id"] == body["service_line_id"]
                and r["period_month"] == body["period_month"] and r["status"] == "ACCEPTED"):
            raise err("ERR_DUPLICATE_PERIOD_REPORT", 409, "An ACCEPTED report already exists for this line and period")
    ev = body["expected_contract_version"]
    if isinstance(ev, bool) or not isinstance(ev, int):
        raise err("ERR_INVALID_REQUEST", 400, "expected_contract_version must be an integer")
    if ev != c["version"]:
        raise err("ERR_STALE_CONTRACT_VERSION", 412, "Stale contract version")
    r = new_entity({
        "contract_id": cid,
        "period_month": body["period_month"],
        "service_line_id": body["service_line_id"],
        "gross_receipts_cents": body["gross_receipts_cents"],
        "submitted_by_role": None,
        "submitted_by_user_id": None,
        "status": "DRAFT",
    })
    store.receipts_reports[r["id"]] = r
    touch(c)
    return ok(serialize(r), 201)


@bp.get("/contracts/<cid>/receipts-reports")
def list_reports(cid):
    require_read_role()
    get_contract(cid)
    items = [r for r in store.receipts_reports.values() if r["contract_id"] == cid]
    for key in ("period_month", "service_line_id", "status"):
        v = request.args.get(key)
        if v:
            items = [r for r in items if str(r.get(key)) == v]
    page, limit, offset, total = paginate(items)
    return ok(page, 200, True, limit, offset, total)


@bp.post("/contracts/<cid>/receipts-reports/<rid>/submit")
def submit_report(cid, rid):
    uid, role = require_role("ConcessionerAccountant")
    get_contract(cid)
    r = get_report(cid, rid)
    if r["status"] == "RETURNED":
        body = request.get_json(silent=True) or {}
        if "gross_receipts_cents" not in body:
            raise err("ERR_INVALID_REQUEST", 400, "gross_receipts_cents must be re-supplied on resubmission")
        v = body["gross_receipts_cents"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise err("ERR_INVALID_REQUEST", 400, "gross_receipts_cents must be a non-negative integer")
        r["gross_receipts_cents"] = v
    elif r["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", 409, "Report must be DRAFT or RETURNED")
    r["status"] = "SUBMITTED"
    r["submitted_by_role"] = role
    r["submitted_by_user_id"] = uid
    touch(r)
    return ok(serialize(r))


@bp.post("/contracts/<cid>/receipts-reports/<rid>/accept")
def accept_report(cid, rid):
    uid, _ = require_role("AgencyFinancialAuditor")
    c = get_contract(cid)
    r = get_report(cid, rid)
    if r["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", 409, "Report must be SUBMITTED")
    if r["submitted_by_user_id"] == uid:
        raise err("ERR_SEGREGATION_OF_DUTIES", 403, "Acceptor must differ from submitter")
    r["status"] = "ACCEPTED"
    touch(r)
    # stale any ISSUED statement for the same period
    for st in store.fee_statements.values():
        if st["contract_id"] == cid and st["period_month"] == r["period_month"] and st["status"] == "ISSUED":
            st["_stale"] = True
            touch(st)
    return ok(serialize(r))


@bp.post("/contracts/<cid>/receipts-reports/<rid>/return")
def return_report(cid, rid):
    require_role("AgencyFinancialAuditor")
    get_contract(cid)
    r = get_report(cid, rid)
    if r["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", 409, "Report must be SUBMITTED")
    body = request.get_json(silent=True) or {}
    if not isinstance(body.get("reason"), str) or not body["reason"]:
        raise err("ERR_INVALID_REQUEST", 400, "reason required")
    r["status"] = "RETURNED"
    touch(r)
    return ok(serialize(r))


# ----- Fee statements -----

@bp.post("/contracts/<cid>/fee-statements")
def create_statement(cid):
    require_role("ConcessionerAccountant")
    c = get_contract(cid)
    require_operational(c)
    body = request.get_json(silent=True)
    require_fields(body, ["period_month"])
    if not _valid_period(body["period_month"]):
        raise err("ERR_INVALID_REQUEST", 400, "period_month must be YYYY-MM")
    for st in store.fee_statements.values():
        if st["contract_id"] == cid and st["period_month"] == body["period_month"]:
            raise err("ERR_INVALID_REQUEST", 400, "Statement month must be unique within the contract")
    accepted = [r for r in store.receipts_reports.values()
                if r["contract_id"] == cid and r["period_month"] == body["period_month"]
                and r["status"] == "ACCEPTED"]
    if not accepted:
        raise err("ERR_NO_ACCEPTED_REPORTS", 409, "Statement issuance requires >= 1 ACCEPTED report for the period")
    rate = Decimal(str(c["franchise_fee_rate"]))
    lines = []
    total_fee = 0
    total_gross = 0
    for r in sorted(accepted, key=lambda x: x["_seq"]):
        line_fee = round_half_up(Decimal(r["gross_receipts_cents"]) * rate)
        lines.append({
            "service_line_id": r["service_line_id"],
            "line_gross_cents": r["gross_receipts_cents"],
            "line_fee_cents": line_fee,
        })
        total_fee += line_fee
        total_gross += r["gross_receipts_cents"]
    agg = round_half_up(Decimal(total_gross) * rate)
    st = new_entity({
        "contract_id": cid,
        "period_month": body["period_month"],
        "lines": lines,
        "total_fee_cents": total_fee,
        "reporting_method": "PER_LINE_ROUNDED",
        "aggregate_diagnostic_cents": agg,
        "status": "ISSUED",
    })
    store.fee_statements[st["id"]] = st
    return ok(serialize(st), 201)


@bp.get("/contracts/<cid>/fee-statements")
def list_statements(cid):
    require_read_role()
    get_contract(cid)
    items = [s for s in store.fee_statements.values() if s["contract_id"] == cid]
    for key in ("period_month", "status"):
        v = request.args.get(key)
        if v:
            items = [s for s in items if str(s.get(key)) == v]
    page, limit, offset, total = paginate(items)
    return ok(page, 200, True, limit, offset, total)


@bp.post("/contracts/<cid>/fee-statements/<sid>/pay")
def pay_statement(cid, sid):
    require_role("ConcessionerAccountant")
    get_contract(cid)
    st = get_statement(cid, sid)
    if st["status"] != "ISSUED":
        raise err("ERR_INVALID_STATE", 409, "Statement must be ISSUED")
    st["status"] = "PAID"
    touch(st)
    return ok(serialize(st))

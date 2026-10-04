"""Sales reports and royalty statements."""
from datetime import date as date_type
from flask import request

import errors as E
import middleware as mw
from db import db
from response import success_list, success_object
from services import calculations as calc
from routes.agreements import bp, get_store


def pub_report(r):
    return {
        "id": r["id"], "store_id": r["store_id"],
        "period_start_date": r["period_start_date"], "period_end_date": r["period_end_date"],
        "gross_sales_cents": r["gross_sales_cents"], "returns_cents": r["returns_cents"],
        "loyalty_redemption_cents": r["loyalty_redemption_cents"],
        "net_sales_cents": r["net_sales_cents"], "status": r["status"],
        "finalized_at": r["finalized_at"],
        "created_at": r["created_at"], "updated_at": r["updated_at"], "version": r["version"],
    }


def pub_statement(st):
    return {
        "id": st["id"], "agreement_id": st["agreement_id"],
        "period_start_date": st["period_start_date"], "period_end_date": st["period_end_date"],
        "basis": st["basis"],
        "recognized_sales_cents": st["recognized_sales_cents"],
        "royalty_amount_cents": st["royalty_amount_cents"],
        "adjustment_delta_cents": st["adjustment_delta_cents"],
        "status": st["status"],
        "created_at": st["created_at"], "updated_at": st["updated_at"], "version": st["version"],
    }


def _report_licensee(r):
    return mw.licensee_of_store(db.stores[r["store_id"]])


def _report_scope(uid, role, r):
    if role == "LicenseeManager" and uid != _report_licensee(r):
        raise E.err_forbidden()


def _periods_overlap(s1, e1, s2, e2):
    return s1 <= e2 and s2 <= e1


# ---------------------------------------------------------------------------
# Sales reports
# ---------------------------------------------------------------------------

@bp.post("/licensing/stores/<sid>/sales-reports")
def create_sales_report(sid):
    uid, role = mw.auth()
    mw.require_role(role, ("LicenseeManager",))
    store = get_store(sid)
    if uid != mw.licensee_of_store(store):
        raise E.err_forbidden()
    if store["operating_status"] != "OPERATING":
        raise E.err_store_not_operating()
    b = mw.body()
    ps = mw.req_date(b, "period_start_date")
    pe = mw.req_date(b, "period_end_date")
    gross = mw.req_int(b, "gross_sales_cents", minimum=0)
    returns = mw.req_int(b, "returns_cents", minimum=0)
    loyalty = mw.req_int(b, "loyalty_redemption_cents", minimum=0)
    if pe < ps:
        raise E.err_invalid_request("period_end_date must be >= period_start_date")
    rec = mw.make_resource({
        "store_id": sid,
        "period_start_date": ps.isoformat(), "period_end_date": pe.isoformat(),
        "gross_sales_cents": gross, "returns_cents": returns,
        "loyalty_redemption_cents": loyalty,
        "net_sales_cents": None, "status": "DRAFT", "finalized_at": None,
    })
    db.sales_reports[rec["id"]] = rec
    return success_object(pub_report(rec), 201)


@bp.get("/licensing/sales-reports/<rid>")
def get_sales_report(rid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin", "LicenseeManager"))
    r = db.sales_reports.get(rid)
    if r is None:
        raise E.err_not_found("sales report not found")
    _report_scope(uid, role, r)
    return success_object(pub_report(r))


@bp.get("/licensing/sales-reports")
def list_sales_reports():
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin", "LicenseeManager"))
    items = list(db.sales_reports.values())
    if role == "LicenseeManager":
        items = [r for r in items if _report_licensee(r) == uid]
    sid = request.args.get("store_id")
    if sid is not None:
        items = [r for r in items if r["store_id"] == sid]
    st = request.args.get("status")
    if st is not None:
        items = [r for r in items if r["status"] == st]
    page, limit, offset, total = mw.paginate(items)
    return success_list([pub_report(x) for x in page], limit, offset, total)


@bp.post("/licensing/sales-reports/<rid>/finalize")
def finalize_sales_report(rid):
    uid, role = mw.auth()
    mw.require_role(role, ("LicenseeManager",))
    r = db.sales_reports.get(rid)
    if r is None:
        raise E.err_not_found("sales report not found")
    _report_scope(uid, role, r)
    if r["status"] != "DRAFT":
        raise E.err_sales_report_not_draft()
    ps = date_type.fromisoformat(r["period_start_date"])
    pe = date_type.fromisoformat(r["period_end_date"])
    for other in db.sales_reports.values():
        if other["id"] == r["id"] or other["store_id"] != r["store_id"]:
            continue
        if other["status"] != "FINALIZED":
            continue
        os_ = date_type.fromisoformat(other["period_start_date"])
        oe = date_type.fromisoformat(other["period_end_date"])
        if _periods_overlap(ps, pe, os_, oe):
            raise E.err_sales_overlap()
    net = r["gross_sales_cents"] - r["returns_cents"] - r["loyalty_redemption_cents"]
    if net < 0:
        raise E.err_invalid_request("net_sales_cents would be negative")
    r["net_sales_cents"] = net
    r["status"] = "FINALIZED"
    r["finalized_at"] = mw.fmt_clock(db.clock)
    mw.touch(r)
    return success_object(pub_report(r))


# ---------------------------------------------------------------------------
# Royalty statements
# ---------------------------------------------------------------------------

@bp.post("/licensing/license-agreements/<aid>/royalty-statements")
def generate_statement(aid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin",))
    agreement = db.license_agreements.get(aid)
    if agreement is None:
        raise E.err_not_found("license agreement not found")
    b = mw.body()
    ps = mw.req_date(b, "period_start_date")
    pe = mw.req_date(b, "period_end_date")
    if pe < ps:
        raise E.err_invalid_request("period_end_date must be >= period_start_date")
    expected = b.get("expected_agreement_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise E.err_invalid_request("expected_agreement_version is required and must be an integer")
    if expected != agreement["version"]:
        raise E.err_stale_version()
    recognized = calc.recognized_sales_for_statement(agreement, ps, pe, db.clock)
    royalty = calc.tiered_royalty_amount(agreement["royalty_tiers"], recognized)
    # supersede overlapping DRAFT statements of this agreement
    for st in db.royalty_statements.values():
        if st["agreement_id"] != aid or st["status"] != "DRAFT":
            continue
        os_ = date_type.fromisoformat(st["period_start_date"])
        oe = date_type.fromisoformat(st["period_end_date"])
        if _periods_overlap(ps, pe, os_, oe):
            st["status"] = "SUPERSEDED"
            mw.touch(st)
    rec = mw.make_resource({
        "agreement_id": aid,
        "period_start_date": ps.isoformat(), "period_end_date": pe.isoformat(),
        "basis": agreement["royalty_basis"],
        "recognized_sales_cents": recognized,
        "royalty_amount_cents": royalty,
        "adjustment_delta_cents": 0,
        "status": "DRAFT",
    })
    db.royalty_statements[rec["id"]] = rec
    mw.touch(agreement)
    return success_object(pub_statement(rec), 201)


@bp.get("/licensing/royalty-statements/<sid>")
def get_statement(sid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin", "LicenseeManager"))
    st = db.royalty_statements.get(sid)
    if st is None:
        raise E.err_not_found("royalty statement not found")
    if role == "LicenseeManager" and uid != db.license_agreements[st["agreement_id"]]["licensee_id"]:
        raise E.err_forbidden()
    return success_object(pub_statement(st))


@bp.get("/licensing/royalty-statements")
def list_statements():
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin", "LicenseeManager"))
    items = list(db.royalty_statements.values())
    if role == "LicenseeManager":
        items = [
            st for st in items
            if db.license_agreements[st["agreement_id"]]["licensee_id"] == uid
        ]
    aid = request.args.get("agreement_id")
    if aid is not None:
        items = [st for st in items if st["agreement_id"] == aid]
    stf = request.args.get("status")
    if stf is not None:
        items = [st for st in items if st["status"] == stf]
    page, limit, offset, total = mw.paginate(items)
    return success_list([pub_statement(x) for x in page], limit, offset, total)


@bp.post("/licensing/royalty-statements/<sid>/issue")
def issue_statement(sid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin",))
    st = db.royalty_statements.get(sid)
    if st is None:
        raise E.err_not_found("royalty statement not found")
    if st["status"] != "DRAFT":
        raise E.err_invalid_statement_state()
    st["status"] = "ISSUED"
    mw.touch(st)
    return success_object(pub_statement(st))


@bp.post("/licensing/royalty-statements/<sid>/dispute")
def dispute_statement(sid):
    uid, role = mw.auth()
    mw.require_role(role, ("LicenseeManager",))
    st = db.royalty_statements.get(sid)
    if st is None:
        raise E.err_not_found("royalty statement not found")
    if uid != db.license_agreements[st["agreement_id"]]["licensee_id"]:
        raise E.err_forbidden()
    if st["status"] != "ISSUED":
        raise E.err_invalid_statement_state()
    b = mw.body()
    st["dispute_reason"] = mw.opt_str(b, "reason")
    st["status"] = "DISPUTED"
    mw.touch(st)
    return success_object(pub_statement(st))


@bp.post("/licensing/royalty-statements/<sid>/adjust")
def adjust_statement(sid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin",))
    st = db.royalty_statements.get(sid)
    if st is None:
        raise E.err_not_found("royalty statement not found")
    if st["status"] != "DISPUTED":
        raise E.err_invalid_statement_state()
    b = mw.body()
    delta = mw.req_int(b, "adjustment_delta_cents")
    if st["recognized_sales_cents"] + delta < 0:
        raise E.err_invalid_request("recognized sales plus the delta must stay non-negative")
    agreement = db.license_agreements[st["agreement_id"]]
    st["adjustment_delta_cents"] = delta
    st["royalty_amount_cents"] = calc.tiered_royalty_amount(
        agreement["royalty_tiers"], st["recognized_sales_cents"] + delta
    )
    st["status"] = "ADJUSTED"
    mw.touch(st)
    return success_object(pub_statement(st))


@bp.post("/licensing/royalty-statements/<sid>/finalize")
def finalize_statement(sid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin",))
    st = db.royalty_statements.get(sid)
    if st is None:
        raise E.err_not_found("royalty statement not found")
    if st["status"] not in ("ISSUED", "ADJUSTED"):
        raise E.err_invalid_statement_state()
    st["status"] = "FINAL"
    mw.touch(st)
    return success_object(pub_statement(st))

"""Community benefit reports and the expense postings that feed their totals."""

from decimal import Decimal

from flask import Blueprint

import consts as K
import derive as D
from core import (authenticate, body_or_empty, db, fail, filter_eq, new_record,
                  now_iso, ok, ok_list, paginate, public, q2, sorted_asc, touch,
                  v_enum, v_id, v_int, v_num, v_str)

bp = Blueprint("reports", __name__)


@bp.post("/community-benefit-reports")
def create_report():
    user_id, _role = authenticate([K.CBO])
    body = body_or_empty()
    cycle_id = v_str(body, "cycle_id", 1, None)
    fiscal_year = v_int(body, "fiscal_year", 2000, 2100)

    cycle = D.cycle_or_404(cycle_id)
    D.gate_frozen(cycle)
    for existing in db.reports.values():
        if existing["cycle_id"] == cycle["id"] and existing["fiscal_year"] == fiscal_year:
            fail("ERR_DUPLICATE_REPORT")

    rec = new_record()
    rec.update({
        "cycle_id": cycle["id"],
        "fiscal_year": fiscal_year,
        "valuation_basis": "PROVISIONAL",
        "cost_to_charge_ratio": cycle["prior_year_cost_to_charge_ratio"],
        "audited_cost_to_charge_ratio": None,
        "status": "OPEN",
        "financial_assistance_cents": 0,
        "subsidized_services_cents": 0,
        "community_health_improvement_cents": 0,
        "cash_and_inkind_cents": 0,
        "community_building_cents": 0,
        "total_valued_cents": 0,
        "overhead_rate": Decimal(K.TIER_1_RATE),
        "indirect_allocation_cents": 0,
        "grand_total_cents": 0,
        "benefit_pct_of_expense": q2(Decimal(0)),
        "created_by_user_id": user_id,
        "finalized_by_user_id": None,
        "locked_at": None,
        "filed_at": None,
    })
    db.reports[rec["id"]] = rec
    return ok(public(rec), 201)


@bp.get("/community-benefit-reports")
def list_reports():
    authenticate([K.CBO, K.CO])
    rows = list(db.reports.values())
    rows = filter_eq(rows, "cycle_id")
    rows = filter_eq(rows, "status")
    data, page = paginate(sorted_asc(rows))
    return ok_list(data, page)


@bp.get("/community-benefit-reports/<report_id>")
def get_report(report_id):
    authenticate([K.CBO, K.CO])
    return ok(public(D.report_or_404(report_id)))


@bp.post("/community-benefit-reports/<report_id>/finalize")
def finalize_report(report_id):
    user_id, _role = authenticate([K.CO])
    rep = D.report_or_404(report_id)
    body = body_or_empty()
    audited = v_num(body, "audited_cost_to_charge_ratio", 0, 1,
                    exact_places=4, exclusive_lo=True)

    if user_id == rep["created_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")
    cycle = D.cycle_of_report(rep)
    D.gate_frozen(cycle)
    if rep["status"] != "OPEN":
        fail("ERR_INVALID_STATE")
    posted = [p for p in D.postings_of_report(rep) if p["status"] == "POSTED"]
    if not posted:
        fail("ERR_REPORT_EMPTY")

    rep["audited_cost_to_charge_ratio"] = audited
    rep["cost_to_charge_ratio"] = audited
    rep["valuation_basis"] = "FINAL"
    for post in sorted(posted, key=lambda p: p["_seq"]):
        D.value_posting(post, rep)
        touch(post)
    D.recompute_report(rep, force=True)
    rep["locked_at"] = now_iso()
    rep["finalized_by_user_id"] = user_id
    rep["status"] = "LOCKED"
    touch(rep)
    return ok(public(rep))


@bp.post("/expense-postings")
def create_posting():
    user_id, _role = authenticate([K.CBO])
    body = body_or_empty()
    report_id = v_str(body, "report_id", 1, None)
    category = v_enum(body, "category", K.EXPENSE_CATEGORIES)
    charges = v_int(body, "charges_cents", 0)
    direct_cost = v_int(body, "direct_cost_cents", 0)
    strategy_id = v_id(body, "strategy_id", required=False)
    expected = v_int(body, "expected_report_version", 0)

    rep = D.report_or_404(report_id)
    strat = D.strategy_or_404(strategy_id) if strategy_id else None

    if expected != rep["version"]:
        fail("ERR_STALE_REPORT_VERSION")

    cycle = D.cycle_of_report(rep)
    D.gate_frozen(cycle)
    if rep["status"] != "OPEN":
        fail("ERR_INVALID_STATE")
    if strat is not None and strat["approval_state"] != "APPROVED":
        fail("ERR_STRATEGY_NOT_APPROVED")

    if category in K.CHARGE_BASED_CATEGORIES:
        if not (charges >= 1 and direct_cost == 0):
            fail("ERR_POSTING_BASIS_MISMATCH")
    else:
        if not (direct_cost >= 1 and charges == 0):
            fail("ERR_POSTING_BASIS_MISMATCH")

    rec = new_record()
    rec.update({
        "report_id": rep["id"],
        "strategy_id": strat["id"] if strat else None,
        "category": category,
        "charges_cents": charges,
        "direct_cost_cents": direct_cost,
        "valued_cents": 0,
        "valuation_basis_at_posting": rep["valuation_basis"],
        "ratio_applied": None,
        "status": "POSTED",
        "posted_by_user_id": user_id,
        "void_reason": None,
        "voided_by_user_id": None,
    })
    D.value_posting(rec, rep)
    db.postings[rec["id"]] = rec
    D.recompute_report(rep, force=True)
    return ok(public(rec), 201)


@bp.get("/expense-postings")
def list_postings():
    authenticate([K.CBO, K.CO])
    rows = list(db.postings.values())
    rows = filter_eq(rows, "report_id")
    rows = filter_eq(rows, "strategy_id")
    rows = filter_eq(rows, "category")
    rows = filter_eq(rows, "status")
    data, page = paginate(sorted_asc(rows))
    return ok_list(data, page)


@bp.get("/expense-postings/<posting_id>")
def get_posting(posting_id):
    authenticate([K.CBO, K.CO])
    return ok(public(D.posting_or_404(posting_id)))


@bp.post("/expense-postings/<posting_id>/void")
def void_posting(posting_id):
    user_id, _role = authenticate([K.CBO, K.CO])
    post = D.posting_or_404(posting_id)
    body = body_or_empty()
    reason = v_str(body, "reason", 1, None)

    if user_id == post["posted_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")
    rep = db.reports.get(post["report_id"])
    cycle = D.cycle_of_posting(post)
    D.gate_frozen(cycle)
    if post["status"] != "POSTED":
        fail("ERR_INVALID_STATE")
    if rep is None or rep["status"] != "OPEN":
        fail("ERR_INVALID_STATE")

    post["void_reason"] = reason
    post["voided_by_user_id"] = user_id
    post["status"] = "VOID"
    touch(post)
    D.recompute_report(rep, force=True)
    return ok(public(post))

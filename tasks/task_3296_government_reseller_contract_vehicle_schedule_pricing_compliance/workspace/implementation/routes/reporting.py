"""SalesReport + ComplianceAudit surface."""
from flask import request

import db
from server_core import app
from errors import (
    err, not_found, invalid_state, fk_not_found,
    ERR_AUDIT_NOT_MATERIAL, ERR_PERIOD_NOT_CLOSED, ERR_UNIQUENESS_VIOLATION,
)
from util import (
    envelope, respond_list, body_arg, new_entity, bump, now_logical,
    period_bounds, require_period_label,
)
from rules import (
    AUDIT_MATERIALITY_CENTS, recompute_sb_goal, cascade_suspend_agreement,
)


def sales_report_view(r):
    return {k: r[k] for k in ("id", "agreement_id", "period_label", "total_sales_cents",
                              "total_sb_subcontract_cents", "sb_goal_met", "status",
                              "created_at", "updated_at", "version")}


def audit_view(a):
    return {k: a[k] for k in ("id", "agreement_id", "scope", "mfc_attestation_cents",
                              "mfc_variance_cents", "disclosed_total_cents", "status",
                              "created_at", "updated_at", "version")}


@app.post("/sales-reports")
def sales_reports_create():
    agreement_id = body_arg("agreement_id")
    if agreement_id not in db.agreements:
        raise fk_not_found("agreement_id not found")
    period_label = require_period_label(body_arg("period_label"))
    for r in db.sales_reports.values():
        if r["agreement_id"] == agreement_id and r["period_label"] == period_label:
            raise err(ERR_UNIQUENESS_VIOLATION,
                      "a sales report already exists for this (agreement, period)", 409)
    r = new_entity(db, db.sales_reports, {},
                   agreement_id=agreement_id, period_label=period_label,
                   total_sales_cents=0, total_sb_subcontract_cents=0,
                   sb_goal_met=True, status="DRAFT")
    r["_period_bounds"] = period_bounds(period_label)
    return envelope(sales_report_view(r), 201)


@app.get("/sales-reports")
def sales_reports_list():
    items = list(db.sales_reports.values())
    aid = request.args.get("agreement_id")
    if aid is not None:
        items = [r for r in items if r["agreement_id"] == aid]
    period = request.args.get("period_label")
    if period is not None:
        items = [r for r in items if r["period_label"] == period]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return respond_list([sales_report_view(r) for r in items])


@app.get("/sales-reports/<rid>")
def sales_reports_get(rid):
    r = db.sales_reports.get(rid)
    if r is None:
        raise not_found("sales report not found")
    return envelope(sales_report_view(r), 200)


@app.post("/sales-reports/<rid>/finalize")
def sales_reports_finalize(rid):
    r = db.sales_reports.get(rid)
    if r is None:
        raise not_found("sales report not found")
    if r["status"] != "DRAFT":
        raise invalid_state("sales report is not DRAFT")
    _, end = r["_period_bounds"]
    if now_logical(db) < end:
        raise err(ERR_PERIOD_NOT_CLOSED, "the reporting period has not closed", 422)
    recompute_sb_goal(db, r)
    r["status"] = "FINALIZED"
    bump(r)
    return envelope(sales_report_view(r), 200)


@app.post("/audits")
def audits_create():
    agreement_id = body_arg("agreement_id")
    if agreement_id not in db.agreements:
        raise fk_not_found("agreement_id not found")
    disclosed = sum(int(r["total_sales_cents"]) for r in db.sales_reports.values()
                    if r["agreement_id"] == agreement_id and r["status"] == "FINALIZED")
    attestation = body_arg("mfc_attestation_cents")
    variance = abs(disclosed - int(attestation))
    a = new_entity(db, db.audits, {},
                   agreement_id=agreement_id, scope=body_arg("scope"),
                   mfc_attestation_cents=attestation,
                   mfc_variance_cents=variance, disclosed_total_cents=disclosed,
                   status="OPEN")
    return envelope(audit_view(a), 201)


@app.get("/audits")
def audits_list():
    items = list(db.audits.values())
    aid = request.args.get("agreement_id")
    if aid is not None:
        items = [a for a in items if a["agreement_id"] == aid]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return respond_list([audit_view(a) for a in items])


@app.get("/audits/<aid>")
def audits_get(aid):
    a = db.audits.get(aid)
    if a is None:
        raise not_found("audit not found")
    return envelope(audit_view(a), 200)


@app.post("/audits/<aid>/issue-finding")
def audits_issue_finding(aid):
    a = db.audits.get(aid)
    if a is None:
        raise not_found("audit not found")
    if a["status"] != "OPEN":
        raise invalid_state("audit is not OPEN")
    if int(a["mfc_variance_cents"]) <= AUDIT_MATERIALITY_CENTS:
        raise err(ERR_AUDIT_NOT_MATERIAL, "mfc variance does not exceed the materiality threshold", 422)
    a["status"] = "FINDING_ISSUED"
    bump(a)
    agreement = db.agreements[a["agreement_id"]]
    if agreement["status"] == "ACTIVE":
        agreement["status"] = "SUSPENDED"
        cascade_suspend_agreement(db, agreement)
        from rules import recompute_posture
        recompute_posture(agreement)
        bump(agreement)
    return envelope(audit_view(a), 200)


@app.post("/audits/<aid>/close")
def audits_close(aid):
    a = db.audits.get(aid)
    if a is None:
        raise not_found("audit not found")
    if a["status"] == "FINDING_ISSUED":
        agreement = db.agreements[a["agreement_id"]]
        if agreement["status"] != "ACTIVE":
            raise invalid_state("agreement must be ACTIVE (finding remediated) to close")
    elif a["status"] != "OPEN":
        raise invalid_state("audit is not OPEN or FINDING_ISSUED")
    a["status"] = "CLOSED"
    bump(a)
    return envelope(audit_view(a), 200)

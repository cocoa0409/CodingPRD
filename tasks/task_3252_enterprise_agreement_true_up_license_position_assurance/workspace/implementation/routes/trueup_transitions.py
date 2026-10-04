"""True-up report state transitions (submit/accept/reject/revise/invoice/settle).

Appended routes for the same blueprint object lives in trueup.py; this module
holds the transition handlers on their own blueprint for file-size reasons.
"""
import flask

import db
from helpers import err, success, touch
from middleware import authenticate, require_role, check_ownership
from services import trueup_line_total, recompute_report_total, current_unit_price_for, accrue_benefits

bp = flask.Blueprint("trueup_transitions", __name__)


def _report_org_id(r):
    ag = db.agreements.get(r["agreement_id"])
    return ag["organization_id"] if ag else None


def _get_report(rid):
    r = db.trueup_reports.get(rid)
    if r is None:
        err("ERR_NOT_FOUND", "True-up report not found.", 404)
    return r


def _transition(rid, allowed_roles, expected_status, customer=False):
    user_id, role = authenticate()
    require_role(role, allowed_roles)
    report = _get_report(rid)
    if customer:
        check_ownership(user_id, role, _report_org_id(report))
    if report["status"] != expected_status:
        err("ERR_INVALID_STATE", "Report is not in %s." % expected_status, 409)
    return report


@bp.post("/licensing/true-up-reports/<rid>/submit")
def submit(rid):
    report = _transition(rid, ("CustomerAdmin",), "DRAFT", customer=True)
    ag = db.agreements.get(report["agreement_id"])
    if ag["status"] != "ACTIVE":
        err("ERR_AGREEMENT_NOT_ACTIVE", "Agreement must be ACTIVE.", 409)
    lines = [l for l in db.trueup_lines.values() if l["report_id"] == rid]
    if len(lines) == 0:
        err("ERR_REPORT_EMPTY", "A report with zero lines cannot be submitted.", 422)
    for line in lines:
        product = db.products.get(line["product_id"])
        line["unit_price_cents"] = current_unit_price_for(ag, product)
        line["total_amount_cents"] = trueup_line_total(
            line["growth_quantity"], line["unit_price_cents"],
            line["months_growth"], line["pricing_variant"])
        touch(line)
    recompute_report_total(report)
    report["status"] = "SUBMITTED"
    touch(report)
    return success(report, status=200, response_type="object")


@bp.post("/licensing/true-up-reports/<rid>/accept")
def accept(rid):
    report = _transition(rid, ("LicensingSpecialist",), "SUBMITTED")
    report["status"] = "ACCEPTED"
    touch(report)
    return success(report, status=200, response_type="object")


@bp.post("/licensing/true-up-reports/<rid>/reject")
def reject(rid):
    report = _transition(rid, ("LicensingSpecialist",), "SUBMITTED")
    report["status"] = "REJECTED"
    touch(report)
    return success(report, status=200, response_type="object")


@bp.post("/licensing/true-up-reports/<rid>/revise")
def revise(rid):
    report = _transition(rid, ("CustomerAdmin",), "REJECTED", customer=True)
    ag = db.agreements.get(report["agreement_id"])
    if ag["status"] != "ACTIVE":
        err("ERR_AGREEMENT_NOT_ACTIVE", "Agreement must be ACTIVE.", 409)
    report["status"] = "DRAFT"
    report["revision_count"] += 1
    touch(report)
    return success(report, status=200, response_type="object")


@bp.post("/licensing/true-up-reports/<rid>/invoice")
def invoice(rid):
    report = _transition(rid, ("LicensingSpecialist",), "ACCEPTED")
    report["status"] = "INVOICED"
    touch(report)
    return success(report, status=200, response_type="object")


@bp.post("/licensing/true-up-reports/<rid>/settle")
def settle(rid):
    report = _transition(rid, ("LicensingSpecialist",), "INVOICED")
    lines = [l for l in db.trueup_lines.values() if l["report_id"] == rid]
    for line in lines:
        for e in db.entitlements.values():
            if e["agreement_id"] == report["agreement_id"] and e["product_id"] == line["product_id"]:
                e["quantity"] += line["growth_quantity"]
                e["locked_baseline_quantity"] = e["quantity"]
                touch(e)
                break
    ann = db.anniversaries.get(report["anniversary_id"])
    if ann is not None and not ann["true_up_closed"]:
        ann["true_up_closed"] = True
        touch(ann)
    report["status"] = "SETTLED"
    touch(report)
    accrue_benefits(report["agreement_id"], report["total_amount_cents"])
    return success(report, status=200, response_type="object")

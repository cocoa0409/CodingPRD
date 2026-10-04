"""Install report routes and review pipeline."""
from flask import Blueprint, request
from datetime import timedelta

from db import db
from errors import (
    raise_err, ERR_VALIDATION, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_DUPLICATE_PERIOD, ERR_PROJECT_FROZEN, ERR_STALE_VERSION,
    ERR_AUDIT_IN_PROGRESS, ERR_ORG_SUSPENDED,
)
from helpers import (
    ok, ok_list, body, new_common, touch, current_date, iso_date_str,
    parse_period, require_non_neg_int,
)
from middleware import (
    authenticate, authorize, ERR_FORBIDDEN_ORG, get_org_or_404,
)
from services_calc import (
    compute_runtime_fee, compute_risk_score, compute_standing,
    sync_org_balance,
)
from routes_orgs import _is_migrated

bp = Blueprint("install_reports", __name__)

READ_ROLES = {"PlatformAdmin", "OrgOwner", "FinanceOps", "Auditor", "ReviewBoard"}


def _check_report_owner(role, uid, report):
    project = db.projects.get(report["project_id"])
    if role == "OrgOwner" and (project is None or uid != project["org_id"]):
        raise_err(ERR_FORBIDDEN_ORG, "Not your report")


@bp.route("/projects/<pid>/install-reports", methods=["POST"])
def create_report(pid):
    uid, role = authenticate()
    authorize(role, {"OrgOwner"})
    p = db.projects.get(pid)
    if p is None:
        raise_err(ERR_NOT_FOUND, "Project not found")
    if uid != p["org_id"]:
        raise_err(ERR_FORBIDDEN_ORG, "Not your project")
    if p["project_status"] in ("FROZEN", "ARCHIVED"):
        raise_err(ERR_PROJECT_FROZEN, "Project frozen or archived")
    org = get_org_or_404(p["org_id"])
    if _is_migrated(org["id"]) or org["org_standing"] == "SUSPENDED":
        raise_err(ERR_ORG_SUSPENDED, "Org suspended or migrated")
    b = body()
    period = b.get("period_month")
    if not parse_period(period):
        raise_err(ERR_VALIDATION, "period_month must be YYYY-MM")
    ndi = require_non_neg_int(b.get("new_device_installs"), "new_device_installs")
    rei = require_non_neg_int(b.get("reinstalls"), "reinstalls")
    bun = require_non_neg_int(b.get("bundle_installs"), "bundle_installs")
    if "expected_project_version" not in b:
        raise_err(ERR_VALIDATION, "expected_project_version is required")
    if b["expected_project_version"] != p["version"]:
        raise_err(ERR_STALE_VERSION, "Project version mismatch")
    # Supersede existing DRAFT for same period; reject if non-DRAFT live report exists
    superseded = None
    for r in db.install_reports.values():
        if r["project_id"] == pid and r["period_month"] == period and r["report_status"] != "ARCHIVED":
            if r["report_status"] == "DRAFT":
                superseded = r
            else:
                raise_err(ERR_DUPLICATE_PERIOD, "A live report already exists for this period")
    if superseded is not None:
        superseded["report_status"] = "ARCHIVED"
        touch(superseded)
        # Void its PROVISIONAL invoice
        for inv in db.invoices.values():
            if inv["report_id"] == superseded["id"] and inv["assessment_status"] == "PROVISIONAL":
                inv["assessment_status"] = "VOIDED"
                touch(inv)
    ent = new_common()
    ent.update({
        "project_id": pid,
        "period_month": period,
        "new_device_installs": ndi,
        "reinstalls": rei,
        "bundle_installs": bun,
        "report_status": "DRAFT",
        "billable_installs": ndi,
        "supersedes_report_id": superseded["id"] if superseded else None,
        "review_note": None,
    })
    db.install_reports[ent["id"]] = ent
    touch(p)
    return ok(ent, 201)


@bp.route("/projects/<pid>/install-reports", methods=["GET"])
def list_project_reports(pid):
    uid, role = authenticate()
    authorize(role, READ_ROLES)
    p = db.projects.get(pid)
    if p is None:
        raise_err(ERR_NOT_FOUND, "Project not found")
    if role == "OrgOwner" and uid != p["org_id"]:
        raise_err(ERR_FORBIDDEN_ORG, "Not your project")
    items = [r for r in db.install_reports.values() if r["project_id"] == pid]
    items.sort(key=lambda r: r["created_at"])
    rs = request.args.get("report_status")
    if rs:
        items = [r for r in items if r["report_status"] == rs]
    return ok_list(items)


@bp.route("/install-reports/<rid>", methods=["GET"])
def get_report(rid):
    uid, role = authenticate()
    authorize(role, READ_ROLES)
    r = db.install_reports.get(rid)
    if r is None:
        raise_err(ERR_NOT_FOUND, "Install report not found")
    _check_report_owner(role, uid, r)
    return ok(r)


@bp.route("/install-reports", methods=["GET"])
def list_reports():
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "FinanceOps", "Auditor", "ReviewBoard"})
    items = sorted(db.install_reports.values(), key=lambda r: r["created_at"])
    pj = request.args.get("project_id")
    sr = request.args.get("supersedes_report_id")
    rs = request.args.get("report_status")
    if pj:
        items = [r for r in items if r["project_id"] == pj]
    if sr:
        items = [r for r in items if r.get("supersedes_report_id") == sr]
    if rs:
        items = [r for r in items if r["report_status"] == rs]
    return ok_list(items)


@bp.route("/install-reports/<rid>/submit", methods=["POST"])
def submit_report(rid):
    uid, role = authenticate()
    authorize(role, {"OrgOwner"})
    r = db.install_reports.get(rid)
    if r is None:
        raise_err(ERR_NOT_FOUND, "Install report not found")
    _check_report_owner(role, uid, r)
    if r["report_status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Only DRAFT reports may be submitted")
    project = db.projects.get(r["project_id"])
    if project["project_status"] != "SHIPPED":
        raise_err(ERR_INVALID_STATE, "Project must be SHIPPED")
    org = get_org_or_404(project["org_id"])
    from services_calc import open_audit_cases
    if any(c["case_status"] in ("OPENED", "EVIDENCE_REQUESTED") for c in open_audit_cases(org["id"])):
        raise_err(ERR_AUDIT_IN_PROGRESS, "Audit case open on org")
    r["report_status"] = "SUBMITTED"
    touch(r)
    # The report's RuntimeFeeInvoice in PROVISIONAL status (PRD §3.4). A report that
    # went DISPUTED -> DRAFT (revise) already carries an ADJUSTED invoice; resubmission
    # re-rates that same invoice back to PROVISIONAL rather than spawning a second one
    # ("The revision cycle DISPUTED back through DRAFT and SUBMITTED may repeat").
    existing = None
    for inv in db.invoices.values():
        if inv["report_id"] == r["id"] and inv["assessment_status"] != "VOIDED":
            existing = inv
            break
    amount, label = compute_runtime_fee(project, org, r["billable_installs"], "provisional")
    if existing is not None:
        existing["assessment_status"] = "PROVISIONAL"
        existing["provisional_amount_cents"] = amount
        existing["fee_schedule_label"] = label
        touch(existing)
        return ok(r)
    inv = new_common()
    inv.update({
        "project_id": project["id"],
        "report_id": r["id"],
        "assessment_status": "PROVISIONAL",
        "payment_status": "UNPAID",
        "provisional_amount_cents": amount,
        "final_amount_cents": 0,
        "paid_cents": 0,
        "waived_cents": 0,
        "due_date": None,
        "fee_schedule_label": label,
    })
    db.invoices[inv["id"]] = inv
    return ok(r)


@bp.route("/install-reports/<rid>/review", methods=["POST"])
def review_report(rid):
    uid, role = authenticate()
    authorize(role, {"ReviewBoard"})
    r = db.install_reports.get(rid)
    if r is None:
        raise_err(ERR_NOT_FOUND, "Install report not found")
    b = body()
    action = b.get("action")
    if action not in ("REVIEW", "ACCEPT", "DISPUTE"):
        raise_err(ERR_VALIDATION, "action must be REVIEW, ACCEPT or DISPUTE")
    project = db.projects.get(r["project_id"])
    org = get_org_or_404(project["org_id"])
    inv = None
    for i in db.invoices.values():
        if i["report_id"] == r["id"] and i["assessment_status"] != "VOIDED":
            inv = i
            break

    if action == "REVIEW":
        if r["report_status"] != "SUBMITTED":
            raise_err(ERR_INVALID_STATE, "Report must be SUBMITTED")
        r["report_status"] = "UNDER_REVIEW"
        touch(r)
        return ok(r)

    if action == "ACCEPT":
        if r["report_status"] != "UNDER_REVIEW":
            raise_err(ERR_INVALID_STATE, "Report must be UNDER_REVIEW")
        r["report_status"] = "ACCEPTED"
        touch(r)
        # Finalize invoice FIRST (gate uses lifetime_installs BEFORE this report applies)
        if inv is not None and inv["assessment_status"] in ("PROVISIONAL", "DISPUTED", "ADJUSTED"):
            amount, label = compute_runtime_fee(project, org, r["billable_installs"], "final")
            inv["assessment_status"] = "FINALIZED"
            inv["final_amount_cents"] = amount
            inv["fee_schedule_label"] = label
            inv["due_date"] = iso_date_str(current_date() + timedelta(days=30))
            touch(inv)
        # lifetime installs consumed (the one and only consumption point)
        project["lifetime_installs"] = project.get("lifetime_installs", 0) + r["billable_installs"]
        project["upgrade_risk_score"] = compute_risk_score(project)
        touch(project)
        if inv is not None and inv["assessment_status"] == "FINALIZED":
            sync_org_balance(org)
            touch(org)
        compute_standing(org)
        return ok(r)

    # DISPUTE
    if r["report_status"] != "UNDER_REVIEW":
        raise_err(ERR_INVALID_STATE, "Report must be UNDER_REVIEW")
    note = b.get("review_note")
    if not isinstance(note, str) or not note:
        raise_err(ERR_VALIDATION, "review_note required for DISPUTE")
    r["report_status"] = "DISPUTED"
    r["review_note"] = note
    touch(r)
    if inv is not None:
        inv["assessment_status"] = "DISPUTED"
        touch(inv)
    return ok(r)


@bp.route("/install-reports/<rid>/revise", methods=["POST"])
def revise_report(rid):
    uid, role = authenticate()
    authorize(role, {"OrgOwner"})
    r = db.install_reports.get(rid)
    if r is None:
        raise_err(ERR_NOT_FOUND, "Install report not found")
    _check_report_owner(role, uid, r)
    if r["report_status"] != "DISPUTED":
        raise_err(ERR_INVALID_STATE, "Only DISPUTED reports may be revised")
    b = body()
    ndi = require_non_neg_int(b.get("new_device_installs"), "new_device_installs")
    rei = require_non_neg_int(b.get("reinstalls"), "reinstalls")
    bun = require_non_neg_int(b.get("bundle_installs"), "bundle_installs")
    r["new_device_installs"] = ndi
    r["reinstalls"] = rei
    r["bundle_installs"] = bun
    r["billable_installs"] = ndi
    r["report_status"] = "DRAFT"
    touch(r)
    project = db.projects.get(r["project_id"])
    org = get_org_or_404(project["org_id"])
    for inv in db.invoices.values():
        if inv["report_id"] == r["id"] and inv["assessment_status"] == "DISPUTED":
            amount, label = compute_runtime_fee(project, org, ndi, "provisional")
            inv["assessment_status"] = "ADJUSTED"
            inv["provisional_amount_cents"] = amount
            inv["fee_schedule_label"] = label
            touch(inv)
            break
    return ok(r)

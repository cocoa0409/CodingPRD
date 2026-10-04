"""Invoice routes: list/get/finalize/pay/waive."""
from flask import Blueprint, request
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db
from errors import (
    raise_err, ERR_VALIDATION, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_PAYMENT_EXCEEDS_BALANCE, ERR_WAIVER_NOT_ALLOWED,
)
from helpers import ok, ok_list, body, touch, current_date, iso_date_str
from middleware import authenticate, authorize, ERR_FORBIDDEN_ORG, get_org_or_404
from services_calc import (
    compute_runtime_fee, compute_standing, sync_org_balance,
    WAIVER_CAP_PCT, active_tier_config,
)

bp = Blueprint("invoices", __name__)

READ_ROLES = {"PlatformAdmin", "OrgOwner", "FinanceOps", "Auditor"}


def _check_inv_owner(role, uid, inv):
    project = db.projects.get(inv["project_id"])
    if role == "OrgOwner" and (project is None or uid != project["org_id"]):
        raise_err(ERR_FORBIDDEN_ORG, "Not your invoice")


def _get_invoice_or_404(iid):
    inv = db.invoices.get(iid)
    if inv is None:
        raise_err(ERR_NOT_FOUND, "Invoice not found")
    return inv


@bp.route("/projects/<pid>/invoices", methods=["GET"])
def list_project_invoices(pid):
    uid, role = authenticate()
    authorize(role, READ_ROLES)
    p = db.projects.get(pid)
    if p is None:
        raise_err(ERR_NOT_FOUND, "Project not found")
    if role == "OrgOwner" and uid != p["org_id"]:
        raise_err(ERR_FORBIDDEN_ORG, "Not your project")
    items = [i for i in db.invoices.values() if i["project_id"] == pid]
    items.sort(key=lambda i: i["created_at"])
    a = request.args.get("assessment_status")
    ps = request.args.get("payment_status")
    if a:
        items = [i for i in items if i["assessment_status"] == a]
    if ps:
        items = [i for i in items if i["payment_status"] == ps]
    return ok_list(items)


@bp.route("/invoices", methods=["GET"])
def list_invoices():
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "FinanceOps", "Auditor"})
    items = sorted(db.invoices.values(), key=lambda i: i["created_at"])
    pj = request.args.get("project_id")
    ri = request.args.get("report_id")
    a = request.args.get("assessment_status")
    ps = request.args.get("payment_status")
    if pj:
        items = [i for i in items if i["project_id"] == pj]
    if ri:
        items = [i for i in items if i["report_id"] == ri]
    if a:
        items = [i for i in items if i["assessment_status"] == a]
    if ps:
        items = [i for i in items if i["payment_status"] == ps]
    return ok_list(items)


@bp.route("/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    uid, role = authenticate()
    authorize(role, READ_ROLES)
    inv = _get_invoice_or_404(iid)
    _check_inv_owner(role, uid, inv)
    return ok(inv)


@bp.route("/invoices/<iid>/finalize", methods=["POST"])
def finalize_invoice(iid):
    uid, role = authenticate()
    authorize(role, {"FinanceOps"})
    inv = _get_invoice_or_404(iid)
    if inv["assessment_status"] != "PROVISIONAL":
        raise_err(ERR_INVALID_STATE, "Only PROVISIONAL invoices may be finalized")
    report = db.install_reports.get(inv["report_id"])
    if report is None or report["report_status"] != "ACCEPTED":
        raise_err(ERR_INVALID_STATE, "Source report must be ACCEPTED")
    project = db.projects.get(inv["project_id"])
    org = get_org_or_404(project["org_id"])
    # lifetime BEFORE this report was applied (acceptance already consumed billable)
    lifetime_before = project.get("lifetime_installs", 0) - report["billable_installs"]
    amount, label = compute_runtime_fee(
        project, org, report["billable_installs"], "final",
        lifetime_before_override=max(0, lifetime_before),
    )
    inv["assessment_status"] = "FINALIZED"
    inv["final_amount_cents"] = amount
    inv["fee_schedule_label"] = label
    inv["due_date"] = iso_date_str(current_date() + timedelta(days=30))
    touch(inv)
    sync_org_balance(org)
    touch(org)
    compute_standing(org)
    return ok(inv)


@bp.route("/invoices/<iid>/pay", methods=["POST"])
def pay_invoice(iid):
    uid, role = authenticate()
    authorize(role, {"FinanceOps"})
    inv = _get_invoice_or_404(iid)
    if inv["assessment_status"] != "FINALIZED":
        raise_err(ERR_INVALID_STATE, "Invoice must be FINALIZED")
    if inv["payment_status"] not in ("UNPAID", "OVERDUE"):
        raise_err(ERR_INVALID_STATE, "Invoice not payable")
    b = body()
    amount = b.get("amount_cents")
    if not isinstance(amount, int) or isinstance(amount, bool):
        raise_err(ERR_VALIDATION, "amount_cents must be an integer")
    outstanding = inv["final_amount_cents"] - inv["paid_cents"] - inv["waived_cents"]
    if outstanding <= 0 or amount != outstanding:
        raise_err(ERR_PAYMENT_EXCEEDS_BALANCE, "Payment must equal outstanding balance exactly")
    inv["paid_cents"] += amount
    inv["payment_status"] = "PAID"
    touch(inv)
    project = db.projects.get(inv["project_id"])
    org = get_org_or_404(project["org_id"])
    sync_org_balance(org)
    touch(org)
    compute_standing(org)
    return ok(inv)


@bp.route("/invoices/<iid>/waive", methods=["POST"])
def waive_invoice(iid):
    uid, role = authenticate()
    authorize(role, {"FinanceOps"})
    inv = _get_invoice_or_404(iid)
    if inv["assessment_status"] != "FINALIZED":
        raise_err(ERR_INVALID_STATE, "Invoice must be FINALIZED")
    if inv["payment_status"] not in ("UNPAID", "OVERDUE"):
        raise_err(ERR_INVALID_STATE, "Invoice not waivable")
    b = body()
    amount = b.get("amount_cents")
    reason = b.get("reason")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
        raise_err(ERR_VALIDATION, "amount_cents must be a non-negative integer")
    if not isinstance(reason, str):
        raise_err(ERR_VALIDATION, "reason is required")
    project = db.projects.get(inv["project_id"])
    org = get_org_or_404(project["org_id"])
    # Eligibility: charity flag OR exempt effective tier OR grandfathered (BASE label)
    cfg = active_tier_config(org["effective_tier_code"])
    exempt_tier = cfg is not None and cfg.get("runtime_fee_exempt")
    eligible = bool(project.get("charity_flag")) or exempt_tier or inv.get("fee_schedule_label") == "BASE"
    full_waiver = bool(project.get("charity_flag")) or exempt_tier
    if not eligible:
        raise_err(ERR_WAIVER_NOT_ALLOWED, "Invoice not eligible for waiver")
    if not full_waiver:
        cap = int((Decimal(inv["final_amount_cents"]) * WAIVER_CAP_PCT).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if inv["waived_cents"] + amount > cap:
            raise_err(ERR_WAIVER_NOT_ALLOWED, "Waiver exceeds cap")
    outstanding = inv["final_amount_cents"] - inv["paid_cents"] - inv["waived_cents"]
    if amount > outstanding:
        raise_err(ERR_WAIVER_NOT_ALLOWED, "Waiver exceeds outstanding balance")
    inv["waived_cents"] += amount
    if inv["final_amount_cents"] - inv["paid_cents"] - inv["waived_cents"] == 0:
        inv["payment_status"] = "WAIVED"
    touch(inv)
    sync_org_balance(org)
    touch(org)
    compute_standing(org)
    return ok(inv)

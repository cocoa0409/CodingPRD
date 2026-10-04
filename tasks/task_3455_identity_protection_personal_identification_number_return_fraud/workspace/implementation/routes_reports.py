"""Identity-theft report lifecycle: confirm (with cascade), reject, reopen."""
from flask import Blueprint

from auth import require_roles
from domain import create_pin, get_report, get_taxpayer, pub, touch
from envelope import ok
from errors import err
from validate import body, req_int

bp = Blueprint("reports", __name__)


@bp.post("/identity-protection/identity-theft-reports/<string:report_id>/confirm")
def confirm_report(report_id):
    uid, role = require_roles(["FraudAnalyst"])
    report = get_report(report_id)
    # Priority 3: segregation of duties — creator may not confirm.
    if report["created_by_user_id"] == uid:
        err("ERR_DUTY_SEGREGATION_VIOLATION")
    # Priority 6: only SUBMITTED can be confirmed (CONFIRMED is sticky but
    # not terminal per PRD §2.10, so a repeat confirm is ERR_INVALID_STATE).
    if report["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", "Only a SUBMITTED report can be confirmed.")
    # Priority 14: payload shape.
    tax_year = req_int(body(), "tax_year")
    # Cascade link 1: victim flag + enrollment (bumps Taxpayer.version).
    taxpayer = get_taxpayer(report["taxpayer_id"])
    taxpayer["status"] = "VICTIM_FLAGGED"
    taxpayer["ip_pin_enrollment"] = "ENROLLED"
    touch(taxpayer)
    # Cascade links 2+3: mint the ACTIVE pin, superseding the prior one.
    create_pin(taxpayer, tax_year, taxpayer["pin_delivery_channel"])
    report["status"] = "CONFIRMED"
    report["confirmed_tax_year"] = tax_year
    touch(report)
    return ok(pub(report))


@bp.post("/identity-protection/identity-theft-reports/<string:report_id>/reject")
def reject_report(report_id):
    uid, role = require_roles(["FraudAnalyst"])
    report = get_report(report_id)
    if report["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", "Only a SUBMITTED report can be rejected.")
    report["status"] = "REJECTED"
    touch(report)
    return ok(pub(report))


@bp.post("/identity-protection/identity-theft-reports/<string:report_id>/reopen")
def reopen_report(report_id):
    uid, role = require_roles(["Taxpayer", "TaxpayerAdvocate"])
    report = get_report(report_id)
    # Priority 3 ownership: a Taxpayer caller reopens only their own report.
    if role == "Taxpayer" and report["taxpayer_id"] != uid:
        err("ERR_UNAUTHORIZED")
    if report["status"] != "REJECTED":
        err("ERR_INVALID_STATE", "Only a REJECTED report can be reopened.")
    report["status"] = "SUBMITTED"
    touch(report)
    return ok(pub(report))

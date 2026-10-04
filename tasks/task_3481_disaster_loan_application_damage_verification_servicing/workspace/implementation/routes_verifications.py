"""Damage verifications (PRD 3.4): open, list, complete, dispute."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g, request

import calc
import clock
from auth import check_owner, require_roles
from body import json_body, req_enum, req_int, req_number
from domain import bump, get_or_404, new_common
from envelope import page, parse_pagination, success, success_list
from errors import raise_err
from store import all_rows, get, put
from serializers import serialize, serialize_all

bp = Blueprint("verifications", __name__)

METHODS = {"INSPECTION", "ESTIMATION"}
BASES = {"REPLACEMENT_COST", "ACTUAL_CASH_VALUE"}
MAX_DEPRECIATION = Decimal("0.90")


@bp.post("/disaster-relief/loan-applications/<app_id>/damage-verifications")
@require_roles("LossVerifier")
def create_verification(app_id):
    app = get_or_404("applications", app_id)
    data = json_body()
    method = req_enum(data, "method", METHODS)
    basis = req_enum(data, "valuation_basis", BASES)
    # depreciation_pct is required exactly when the basis is ACTUAL_CASH_VALUE.
    depreciation = None
    if basis == "ACTUAL_CASH_VALUE":
        depreciation = req_number(data, "depreciation_pct")
        if depreciation <= 0 or depreciation > MAX_DEPRECIATION:
            raise_err("ERR_INVALID_REQUEST", "depreciation_pct must be > 0 and <= 0.90")
    elif data.get("depreciation_pct") is not None:
        raise_err("ERR_INVALID_REQUEST", "depreciation_pct must be omitted for REPLACEMENT_COST")
    # Purpose gate (priority 7) precedes the state gate (priority 8).
    if app["loan_purpose"] != "PHYSICAL_DAMAGE":
        raise_err("ERR_VERIFICATION_NOT_APPLICABLE")
    if app["status"] != "VERIFICATION":
        raise_err("ERR_APPLICATION_NOT_IN_VERIFICATION")
    if method == "ESTIMATION" and app["requested_amount_cents"] > calc.ESTIMATION_MAX_CENTS:
        raise_err("ERR_ESTIMATION_NOT_ALLOWED")
    row = new_common()
    row.update({
        "application_id": app["id"],
        "method": method,
        "valuation_basis": basis,
        "depreciation_pct": float(depreciation) if depreciation is not None else None,
        "assessed_loss_cents": None,
        "insurance_proceeds_cents": None,
        "verified_loss_cents": None,
        "net_verified_loss_cents": None,
        "status": "REQUESTED",
        "verifier_user_id": None,
        "completed_at": None,
    })
    put("verifications", row)
    return success(serialize(row), 201)


@bp.get("/disaster-relief/loan-applications/<app_id>/damage-verifications")
@require_roles("LossVerifier", "LoanApprover", "LoanOfficer", "Applicant")
def list_verifications(app_id):
    app = get_or_404("applications", app_id)
    check_owner(app["applicant_id"])
    rows = [v for v in all_rows("verifications") if v["application_id"] == app_id]
    limit, offset = parse_pagination(request.args)
    items, total = page(rows, limit, offset)
    return success_list(serialize_all(items), limit, offset, total)


@bp.post("/disaster-relief/damage-verifications/<verif_id>/complete")
@require_roles("LossVerifier")
def complete_verification(verif_id):
    v = get_or_404("verifications", verif_id)
    data = json_body()
    assessed = req_int(data, "assessed_loss_cents", min_value=0)
    insurance = req_int(data, "insurance_proceeds_cents", min_value=0)
    if v["status"] not in ("REQUESTED", "DISPUTED"):
        raise_err("ERR_VERIFICATION_NOT_OPEN")
    was_first = v["status"] == "REQUESTED"
    depreciation = Decimal(str(v["depreciation_pct"])) if v["depreciation_pct"] is not None else None
    verified = calc.verified_loss_cents(assessed, v["valuation_basis"], depreciation)
    v["assessed_loss_cents"] = assessed
    v["insurance_proceeds_cents"] = insurance
    v["verified_loss_cents"] = verified
    v["net_verified_loss_cents"] = calc.net_verified_loss_cents(verified, insurance)
    v["verifier_user_id"] = g.user_id
    v["completed_at"] = clock.get_current()
    v["status"] = "COMPLETED"
    bump(v)
    if was_first:
        # First completion cascades: the linked application advances.
        app = get("applications", v["application_id"])
        if app is not None and app["status"] == "VERIFICATION":
            app["status"] = "DECISION_PENDING"
            bump(app)
    return success(serialize(v))


@bp.post("/disaster-relief/damage-verifications/<verif_id>/dispute")
@require_roles("Applicant")
def dispute_verification(verif_id):
    v = get_or_404("verifications", verif_id)
    app = get_or_404("applications", v["application_id"])
    check_owner(app["applicant_id"])
    if v["status"] != "COMPLETED":
        raise_err("ERR_VERIFICATION_NOT_DISPUTABLE")
    if app["status"] == "APPROVED":
        raise_err("ERR_VERIFICATION_NOT_DISPUTABLE")
    now = clock.get_current()
    if now > v["completed_at"] + timedelta(days=calc.DISPUTE_WINDOW_DAYS):
        raise_err("ERR_DISPUTE_WINDOW_CLOSED")
    v["status"] = "DISPUTED"
    bump(v)
    return success(serialize(v))

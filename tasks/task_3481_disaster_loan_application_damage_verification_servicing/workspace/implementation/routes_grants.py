"""Grant awards and the duplication-of-benefits ceiling (PRD 3.5, dob_check)."""

from flask import Blueprint, request

import clock
from auth import require_roles
from body import json_body, req_enum, req_int, req_str
from domain import app_grants, get_or_404, latest_verification, loan_settlements
from envelope import page, parse_pagination, success, success_list
from errors import raise_err
from store import all_rows, get, new_id, put
from serializers import serialize, serialize_all

bp = Blueprint("grants", __name__)

PURPOSES = {"PHYSICAL_DAMAGE", "ECONOMIC_INJURY"}


@bp.post("/disaster-relief/loan-applications/<app_id>/grant-awards")
@require_roles("GrantCoordinator")
def create_grant(app_id):
    app = get_or_404("applications", app_id)
    data = json_body()
    program_name = req_str(data, "program_name")
    award = req_int(data, "award_amount_cents", min_value=1)
    purpose = req_enum(data, "purpose_category", PURPOSES)
    if purpose != app["loan_purpose"]:
        raise_err("ERR_INVALID_REQUEST", "purpose_category must equal the application's loan_purpose")
    if purpose == "PHYSICAL_DAMAGE":
        latest = latest_verification(app["id"], completed_only=True)
        insurance = latest["insurance_proceeds_cents"] if latest else 0
        verified_loss = latest["verified_loss_cents"] if latest else 0
        settlements = 0
        commitment = 0
        if app.get("loan_id"):
            loan = get("loans", app["loan_id"])
            if loan is not None:
                settlements = sum(s["settlement_amount_cents"] for s in loan_settlements(loan["id"])
                                  if s["status"] == "APPLIED")
                if app["status"] == "APPROVED":
                    commitment = loan["commitment_amount_cents"]
        grant_sum = sum(g["award_amount_cents"] for g in app_grants(app["id"])
                        if g["purpose_category"] == "PHYSICAL_DAMAGE") + award
        assistance_total = insurance + settlements + grant_sum + commitment
        if assistance_total > verified_loss:
            raise_err("ERR_DUPLICATION_OF_BENEFITS")
    # ECONOMIC_INJURY grants are always accepted (no verified-loss ceiling).
    row = {
        "id": new_id(),
        "created_at": clock.get_current(),
        "application_id": app["id"],
        "program_name": program_name,
        "award_amount_cents": award,
        "purpose_category": purpose,
    }
    put("grants", row)
    return success(serialize(row), 201)


@bp.get("/disaster-relief/loan-applications/<app_id>/grant-awards")
@require_roles("GrantCoordinator", "LoanApprover", "LoanOfficer", "ServicingAgent")
def list_grants(app_id):
    get_or_404("applications", app_id)
    rows = [g for g in all_rows("grants") if g["application_id"] == app_id]
    limit, offset = parse_pagination(request.args)
    items, total = page(rows, limit, offset)
    return success_list(serialize_all(items), limit, offset, total)

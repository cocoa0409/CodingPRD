"""POST /disaster-relief/applicants (PRD 3.2)."""

from flask import Blueprint

from auth import require_roles
from body import json_body, req_enum, req_int, req_str
from domain import new_common
from envelope import success
from errors import raise_err
from store import all_rows, put
from serializers import serialize

bp = Blueprint("applicants", __name__)

APPLICANT_TYPES = {"HOMEOWNER", "RENTER", "BUSINESS"}


@bp.post("/disaster-relief/applicants")
@require_roles("Anonymous")
def create_applicant():
    data = json_body()
    full_name = req_str(data, "full_name")
    email = req_str(data, "email")
    applicant_type = req_enum(data, "applicant_type", APPLICANT_TYPES)
    annual_income_cents = req_int(data, "annual_income_cents", min_value=1)
    monthly_debt_cents = req_int(data, "monthly_debt_cents", min_value=0)
    for a in all_rows("applicants"):
        if a["email"] == email:
            raise_err("ERR_INVALID_REQUEST", "email must be unique across applicants")
    row = new_common()
    row.update({
        "full_name": full_name,
        "email": email,
        "applicant_type": applicant_type,
        "annual_income_cents": annual_income_cents,
        "monthly_debt_cents": monthly_debt_cents,
    })
    put("applicants", row)
    return success(serialize(row), 201)

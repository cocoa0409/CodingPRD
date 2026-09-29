"""Administrator registration and read (PRD 3.1)."""

from decimal import Decimal

from flask import Blueprint

import serialize
import shape
from auth import guard
from enums import ALL_ROLES
from envelope import success
from errors import ApiError
from store import db, lookup_path, new_row

bp = Blueprint("administrators", __name__)

DEFAULT_PRODUCTION_DAYS = 45


@bp.route("/administrators", methods=["POST"])
@guard("PlanSponsor")
def create_administrator():
    payload = shape.body()
    legal_name = shape.req_string(payload, "legal_name", 1, 120)
    contact_email = shape.req_string(payload, "contact_email", 1, None)
    if "@" not in contact_email:
        raise ApiError("ERR_VALIDATION", "contact_email must contain an @ character.")
    production_days = shape.opt_int(payload, "contractual_production_days", 1, 120,
                                    DEFAULT_PRODUCTION_DAYS)
    row = new_row({
        "legal_name": legal_name,
        "contact_email": contact_email,
        "contractual_production_days": production_days,
        "outstanding_request_count": 0,
        "late_request_count": 0,
        "breach_count": 0,
        "regulator_reportable_late_count": 0,
        "cooperation_score": Decimal("100.00"),
        "regulatory_basis_cooperation_score": Decimal("100.00"),
        "cooperation_status": "COOPERATIVE",
    })
    db.administrators[row["id"]] = row
    return success(serialize.administrator(row), 201)


@bp.route("/administrators/<admin_id>", methods=["GET"])
@guard(*ALL_ROLES)
def read_administrator(admin_id):
    row = lookup_path(db.administrators, admin_id, "ERR_ADMINISTRATOR_NOT_FOUND")
    return success(serialize.administrator(row))

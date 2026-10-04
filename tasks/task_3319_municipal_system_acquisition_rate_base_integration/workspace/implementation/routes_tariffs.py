"""TariffCase endpoints: create, list, get, adopt."""
from flask import Blueprint

import db
from calculations import phase_in_schedule
from errors import ApiError
from middleware import (
    current_user, require_roles, require_fields, require_int, require_enum,
)
from models import new_tariff_case, touch
from response import success_obj, success_list, json_body, parse_pagination, paginate
from routes_targets import get_target_or_404
from util import ALL_ROLES, TARIFF_MODES

bp = Blueprint("tariff_cases", __name__)


def get_tariff_case_or_404(case_id):
    case = db.tariff_cases.get(case_id)
    if case is None:
        raise ApiError("ERR_NOT_FOUND", 404, "TariffCase not found")
    return case


@bp.route("/acquisitions/targets/<target_id>/tariff-cases", methods=["POST"])
def create_tariff_case(target_id):
    _, role = current_user()
    require_roles(role, ["RegulatoryOfficer"])
    target = get_target_or_404(target_id)
    body = json_body()
    require_fields(body, ["mode", "representative_old_bill_cents",
                          "consolidated_monthly_bill_cents"])
    require_enum(body, "mode", TARIFF_MODES)
    require_int(body, "representative_old_bill_cents", gt_zero=True)
    require_int(body, "consolidated_monthly_bill_cents", gt_zero=True)
    case = new_tariff_case(target["id"], body)
    return success_obj(case, status=201)


@bp.route("/acquisitions/targets/<target_id>/tariff-cases", methods=["GET"])
def list_tariff_cases(target_id):
    _, role = current_user()
    require_roles(role, ALL_ROLES)
    get_target_or_404(target_id)
    limit, offset = parse_pagination()
    records = sorted(db.tariff_cases_of_target(target_id),
                     key=lambda t: (t["created_at"], t["id"]))
    page, total = paginate(records, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/acquisitions/tariff-cases/<case_id>", methods=["GET"])
def get_tariff_case(case_id):
    _, role = current_user()
    require_roles(role, ALL_ROLES)
    return success_obj(get_tariff_case_or_404(case_id))


@bp.route("/acquisitions/tariff-cases/<case_id>/adopt", methods=["POST"])
def adopt_tariff_case(case_id):
    _, role = current_user()
    require_roles(role, ["RegulatoryOfficer"])
    case = get_tariff_case_or_404(case_id)
    target = db.targets[case["target_id"]]
    if case["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "TariffCase is not in DRAFT")
    if target["status"] not in ("REGULATORY_REVIEW", "CLOSING"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Target is not in REGULATORY_REVIEW or CLOSING")
    # Priority 12: SINGLE_TARIFF requires an APPROVED regulatory application.
    if case["mode"] == "SINGLE_TARIFF":
        if not any(a["status"] == "APPROVED"
                   for a in db.regulatory_applications_of_target(case["target_id"])):
            raise ApiError("ERR_APPROVAL_PREREQ", 409,
                           "SINGLE_TARIFF adoption requires an APPROVED regulatory application")
    # Priority 16: exactly one ADOPTED TariffCase per target.
    if any(t["status"] == "ADOPTED"
           for t in db.tariff_cases_of_target(case["target_id"])):
        raise ApiError("ERR_DUPLICATE", 409,
                       "An ADOPTED TariffCase already exists for the target")
    case["phase_in_years"] = phase_in_schedule(case)
    case["status"] = "ADOPTED"
    touch(case)
    return success_obj(case)

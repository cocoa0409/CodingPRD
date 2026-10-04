"""ValuationCase + ValuationEntry endpoints."""
from flask import Blueprint

import db
from errors import ApiError
from middleware import (
    current_user, require_roles, require_fields, require_int, require_enum,
    require_str,
)
from models import new_valuation_case, new_valuation_entry, touch
from response import success_obj, success_list, json_body, parse_pagination, paginate
from routes_targets import get_target_or_404
from statemachines import supersede_open_cases
from util import ALL_ROLES, VALUATION_METHODS

bp = Blueprint("valuation_cases", __name__)


def get_valuation_case_or_404(case_id):
    case = db.valuation_cases.get(case_id)
    if case is None:
        raise ApiError("ERR_NOT_FOUND", 404, "ValuationCase not found")
    return case


@bp.route("/acquisitions/targets/<target_id>/valuation-cases", methods=["POST"])
def create_valuation_case(target_id):
    _, role = current_user()
    require_roles(role, ["AcquisitionAnalyst"])
    target = get_target_or_404(target_id)
    if target["status"] != "VALUATION":
        raise ApiError("ERR_INVALID_STATE", 409, "Target is not in VALUATION")
    body = json_body()
    require_fields(body, ["expected_target_version"])
    expected = body.get("expected_target_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError("ERR_INVALID_REQUEST", 422,
                       "expected_target_version must be an integer")
    if expected != target["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_target_version does not match the target version")
    supersede_open_cases(target)
    case = new_valuation_case(target["id"])
    touch(target)
    return success_obj(case, status=201)


@bp.route("/acquisitions/targets/<target_id>/valuation-cases", methods=["GET"])
def list_valuation_cases(target_id):
    _, role = current_user()
    require_roles(role, ALL_ROLES)
    get_target_or_404(target_id)
    limit, offset = parse_pagination()
    records = sorted(db.valuation_cases_of_target(target_id),
                     key=lambda c: (c["created_at"], c["id"]))
    page, total = paginate(records, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/acquisitions/valuation-cases/<case_id>", methods=["GET"])
def get_valuation_case(case_id):
    _, role = current_user()
    require_roles(role, ALL_ROLES)
    return success_obj(get_valuation_case_or_404(case_id))


@bp.route("/acquisitions/valuation-cases/<case_id>/entries", methods=["POST"])
def create_valuation_entry(case_id):
    user_id, role = current_user()
    require_roles(role, ["Appraiser"])
    case = get_valuation_case_or_404(case_id)
    if case["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "ValuationCase is not OPEN")
    body = json_body()
    require_fields(body, ["method", "value_cents", "law_citation"])
    method = require_enum(body, "method", VALUATION_METHODS)
    require_int(body, "value_cents", gt_zero=True)
    require_str(body, "law_citation")
    # Priority 10: statutory method permission.
    target = db.targets[case["target_id"]]
    if method not in target["permitted_valuation_methods"]:
        raise ApiError("ERR_METHOD_NOT_PERMITTED", 422,
                       "Method not permitted by the target state's statute")
    entry = new_valuation_entry(case["id"], method, body["value_cents"],
                                body["law_citation"], user_id)
    return success_obj(entry, status=201)


@bp.route("/acquisitions/valuation-cases/<case_id>/entries", methods=["GET"])
def list_valuation_entries(case_id):
    _, role = current_user()
    require_roles(role, ALL_ROLES)
    get_valuation_case_or_404(case_id)
    limit, offset = parse_pagination()
    records = sorted(db.valuation_entries_of_case(case_id),
                     key=lambda e: (e["created_at"], e["id"]))
    page, total = paginate(records, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/acquisitions/valuation-cases/<case_id>/finalize", methods=["POST"])
def finalize_valuation_case(case_id):
    user_id, role = current_user()
    require_roles(role, ["AcquisitionAnalyst"])
    case = get_valuation_case_or_404(case_id)
    # Priority 4: segregation of duties before state checks.
    submitted = [e for e in db.valuation_entries_of_case(case_id)
                 if e["status"] == "SUBMITTED"]
    if any(e["appraiser_user_id"] == user_id for e in submitted):
        raise ApiError("ERR_SEGREGATION_OF_DUTY", 403,
                       "Finalizer must not be the appraiser of any SUBMITTED entry")
    if case["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "ValuationCase is not OPEN")
    body = json_body()
    require_fields(body, ["select_entry_id"])
    select_id = body.get("select_entry_id")
    if not isinstance(select_id, str):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "select_entry_id must identify a SUBMITTED entry of this case")
    selected = next((e for e in submitted if e["id"] == select_id), None)
    if selected is None:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "select_entry_id must identify a SUBMITTED entry of this case")
    for entry in submitted:
        entry["status"] = "SELECTED" if entry["id"] == select_id else "NOT_SELECTED"
        touch(entry)
    case["status"] = "FINALIZED"
    case["selected_entry_id"] = select_id
    case["selected_value_cents"] = selected["value_cents"]
    case["finalized_by_user_id"] = user_id
    touch(case)
    # Trigger target VALUATION -> MUNICIPAL_REVIEW.
    target = db.targets[case["target_id"]]
    if target["status"] == "VALUATION":
        target["status"] = "MUNICIPAL_REVIEW"
        target["selected_value_cents"] = case["selected_value_cents"]
        touch(target)
    return success_obj(case)

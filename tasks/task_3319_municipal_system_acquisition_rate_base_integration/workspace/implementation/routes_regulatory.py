"""RegulatoryApplication endpoints: create+file, list, get, decide, refile."""
from flask import Blueprint

import db
from calculations import rate_base_admission
from errors import ApiError
from middleware import (
    current_user, require_roles, require_fields, require_int, require_enum,
)
from models import new_regulatory_application, touch
from response import success_obj, success_list, json_body, parse_pagination, paginate
from routes_targets import get_target_or_404
from statemachines import reject_target_cascade
from util import ALL_ROLES, RATE_BASE_METHODS

bp = Blueprint("regulatory_applications", __name__)


def get_regulatory_application_or_404(app_id):
    app = db.regulatory_applications.get(app_id)
    if app is None:
        raise ApiError("ERR_NOT_FOUND", 404, "RegulatoryApplication not found")
    return app


def _validate_application_payload(body, partial=False):
    require_fields(body, ["purchase_price_cents", "rate_base_method"])
    require_int(body, "purchase_price_cents", gt_zero=True)
    method = require_enum(body, "rate_base_method", RATE_BASE_METHODS)
    ocld = body.get("original_cost_less_depreciation_cents")
    if method == "DEPRECIATED_ORIGINAL_COST":
        if ocld is None:
            raise ApiError("ERR_INVALID_REQUEST", 422,
                           "original_cost_less_depreciation_cents is required "
                           "for DEPRECIATED_ORIGINAL_COST")
        require_int(body, "original_cost_less_depreciation_cents", minimum=0)
    elif ocld is not None:
        require_int(body, "original_cost_less_depreciation_cents", minimum=0)
    return body["purchase_price_cents"], method, ocld


@bp.route("/acquisitions/targets/<target_id>/regulatory-applications", methods=["POST"])
def create_regulatory_application(target_id):
    _, role = current_user()
    require_roles(role, ["RegulatoryOfficer"])
    target = get_target_or_404(target_id)
    if target["status"] != "MUNICIPAL_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Target is not in MUNICIPAL_REVIEW")
    # Priority 12: council approval gate.
    if not target["council_approved"]:
        raise ApiError("ERR_APPROVAL_PREREQ", 409, "Council approval is required")
    body = json_body()
    price, method, ocld = _validate_application_payload(body)
    app = new_regulatory_application(target["id"], price, method, ocld)
    target["status"] = "REGULATORY_REVIEW"
    touch(target)
    return success_obj(app, status=201)


@bp.route("/acquisitions/targets/<target_id>/regulatory-applications", methods=["GET"])
def list_regulatory_applications(target_id):
    _, role = current_user()
    require_roles(role, ALL_ROLES)
    get_target_or_404(target_id)
    limit, offset = parse_pagination()
    records = sorted(db.regulatory_applications_of_target(target_id),
                     key=lambda a: (a["created_at"], a["id"]))
    page, total = paginate(records, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/acquisitions/regulatory-applications/<app_id>", methods=["GET"])
def get_regulatory_application(app_id):
    _, role = current_user()
    require_roles(role, ALL_ROLES)
    return success_obj(get_regulatory_application_or_404(app_id))


@bp.route("/acquisitions/regulatory-applications/<app_id>/decide", methods=["POST"])
def decide_regulatory_application(app_id):
    _, role = current_user()
    require_roles(role, ["Commissioner"])
    app = get_regulatory_application_or_404(app_id)
    if app["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", 409, "Application is not in FILED")
    body = json_body()
    require_fields(body, ["outcome"])
    outcome = require_enum(body, "outcome", ["APPROVED", "DENIED", "REMANDED"])
    target = db.targets[app["target_id"]]
    if outcome == "APPROVED":
        admitted, disallowed = rate_base_admission(app, target)
        app["admitted_rate_base_cents"] = admitted
        app["disallowed_premium_cents"] = disallowed
        app["status"] = "APPROVED"
        touch(app)
        target["status"] = "CLOSING"
        target["admitted_rate_base_cents"] = admitted
        target["disallowed_premium_cents"] = disallowed
        touch(target)
    elif outcome == "DENIED":
        app["status"] = "DENIED"
        touch(app)
        reject_target_cascade(target)
    else:
        app["status"] = "REMANDED"
        touch(app)
    return success_obj(app)


@bp.route("/acquisitions/regulatory-applications/<app_id>/refile", methods=["POST"])
def refile_regulatory_application(app_id):
    _, role = current_user()
    require_roles(role, ["RegulatoryOfficer"])
    app = get_regulatory_application_or_404(app_id)
    if app["status"] != "REMANDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Application is not in REMANDED")
    body = json_body()
    require_fields(body, ["expected_target_version"])
    expected = body.get("expected_target_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError("ERR_INVALID_REQUEST", 422,
                       "expected_target_version must be an integer")
    target = db.targets[app["target_id"]]
    if expected != target["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_target_version does not match the target version")
    price, method, ocld = _validate_application_payload(body)
    app["purchase_price_cents"] = price
    app["rate_base_method"] = method
    app["original_cost_less_depreciation_cents"] = ocld
    app["status"] = "FILED"
    app["filing_round"] += 1
    touch(app)
    touch(target)
    return success_obj(app)

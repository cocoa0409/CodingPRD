"""JurisdictionRule endpoints."""

from flask import Blueprint, request

from db import db
from middleware import require_role, get_pagination, ALL_ROLES
from response import success_object, success_array
from services.common import body_json, require_fields, check_str, check_bool, check_date, check_date_opt, mint

bp = Blueprint("jurisdiction_rules", __name__)


@bp.route("/jurisdiction-rules", methods=["POST"])
def create_rule():
    require_role(["PrivacyOfficer"])
    data = body_json()
    require_fields(data, ["state_code", "restrict_prescriber_identifiable", "effective_from"])
    rule = mint(db.jurisdiction_rules, {
        "state_code": check_str(data, "state_code"),
        "restrict_prescriber_identifiable": check_bool(data, "restrict_prescriber_identifiable"),
        "effective_from": check_date(data, "effective_from"),
        "effective_to": check_date_opt(data, "effective_to"),
    }, common=False)
    return success_object(rule, status=201)


@bp.route("/jurisdiction-rules", methods=["GET"])
def list_rules():
    require_role(ALL_ROLES)
    limit, offset = get_pagination()
    state_code = request.args.get("state_code")
    items = sorted(db.jurisdiction_rules.values(), key=lambda r: r["created_at"])
    if state_code is not None:
        items = [r for r in items if r["state_code"] == state_code]
    total = len(items)
    return success_array(items[offset:offset + limit], limit, offset, total)

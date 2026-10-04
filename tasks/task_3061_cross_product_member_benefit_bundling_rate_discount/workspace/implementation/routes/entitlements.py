"""Benefit entitlement routes beyond declaration and reconcile."""

from flask import Blueprint

from db import DB
from errors import ERR_BENEFIT_ALREADY_GRANTED, ERR_INVALID_STATE, ApiError
from middleware import as_string, auth, raw_body, reject_unknown, require_fields
from response import ok_object
from routes.common import fetch, guard_member_view, list_response
from services import calc, recompute, serialize, workflows

BP = Blueprint("entitlements", __name__)

OVERRIDE_ALLOWED = {"override_reason"}


@BP.route("/benefits/benefit-entitlements", methods=["GET"])
def list_entitlements():
    auth(("PlatformAdmin", "BenefitsAdmin", "ComplianceOfficer"))
    items = list(DB.entitlements.values())
    filters = {
        "member_id": "member_id",
        "benefit_code": "benefit_code",
        "entitlement_status": "entitlement_status",
        "source_holding_id": "source_holding_id",
        "governing_rule_id": "governing_rule_id",
    }
    return list_response(items, serialize.entitlement, filters)


@BP.route("/benefits/benefit-entitlements/<entitlement_id>", methods=["GET"])
def get_entitlement(entitlement_id):
    user_id, role = auth(("Member", "PlatformAdmin", "BenefitsAdmin", "ComplianceOfficer"))
    ent = fetch("entitlements", entitlement_id)
    guard_member_view(user_id, role, ent["member_id"])
    return ok_object(serialize.entitlement(ent))


@BP.route("/benefits/benefit-entitlements/<entitlement_id>/step-down", methods=["POST"])
def step_down(entitlement_id):
    auth(("BenefitsAdmin",))
    ent = fetch("entitlements", entitlement_id)
    if ent["entitlement_status"] not in ("GRANTED", "PENDING_REQUALIFICATION"):
        raise ApiError(ERR_INVALID_STATE)
    workflows.step_down_entitlement(ent)
    return ok_object(serialize.entitlement(ent))


@BP.route("/benefits/benefit-entitlements/<entitlement_id>/restore", methods=["POST"])
def restore(entitlement_id):
    auth(("BenefitsAdmin",))
    ent = fetch("entitlements", entitlement_id)
    if ent["entitlement_status"] == "GRANTED":
        raise ApiError(ERR_BENEFIT_ALREADY_GRANTED)
    if ent["entitlement_status"] != "STEPPED_DOWN":
        raise ApiError(ERR_INVALID_STATE)
    workflows.restore_entitlement(ent)
    return ok_object(serialize.entitlement(ent))


@BP.route("/benefits/benefit-entitlements/<entitlement_id>/request-override", methods=["POST"])
def request_override(entitlement_id):
    user_id, role = auth(("BenefitsAdmin",))
    del role
    ent = fetch("entitlements", entitlement_id)
    payload = raw_body()
    reject_unknown(payload, OVERRIDE_ALLOWED)
    require_fields(payload, ("override_reason",))
    reason = as_string(payload, "override_reason")
    workflows.request_override(ent, user_id, reason)
    return ok_object(serialize.entitlement(ent))


@BP.route("/benefits/benefit-entitlements/<entitlement_id>/approve-override", methods=["POST"])
def approve_override(entitlement_id):
    user_id, role = auth(("ComplianceOfficer",))
    del role
    ent = fetch("entitlements", entitlement_id)
    workflows.approve_override(ent, user_id)
    return ok_object(serialize.entitlement(ent))

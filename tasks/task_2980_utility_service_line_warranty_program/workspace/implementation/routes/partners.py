"""Utility brand partners: registration, reads and the lifecycle cascade."""

from flask import Blueprint

import config
import serializers
from errors import ApiError
from response import object_response, paginate
from services import cascades
from store import create_record, ordered, store, touch
from validation import Field, current_user_id, filter_enum, filter_value, parse_body, require_path_uuid, require_role

bp = Blueprint("partners", __name__)

READ_ROLES = (
    config.ROLE_PLATFORM_ADMIN,
    config.ROLE_MARKETING_OPS,
    config.ROLE_PARTNER_BRAND_REVIEWER,
    config.ROLE_CUSTOMER_SERVICE_REP,
    config.ROLE_BILLING_OPS,
    config.ROLE_CLAIMS_ADJUSTER,
    config.ROLE_APPEALS_OFFICER,
    config.ROLE_REGULATORY_AFFAIRS,
    config.ROLE_OPERATIONS_ADMIN,
)

CREATE_SPEC = {
    "name": Field("string", required=True, min_len=1, max_len=120),
    "utility_type": Field("enum", required=True, enum=config.UTILITY_TYPES),
    "state_code": Field("state_code", required=True),
    "brand_approval_required": Field("boolean"),
    "min_days_between_drops": Field("integer", minimum=0, maximum=180),
    "max_mailings_per_year": Field("integer", minimum=1, maximum=12),
    "rate_filing_required": Field("boolean"),
    "bill_insert_supported": Field("boolean"),
}

STATUS_SPEC = {
    "target_status": Field("enum", required=True, enum=config.PARTNER_STATUSES),
    "reason": Field("string", required=True, min_len=1, max_len=500),
    "expected_partner_version": Field("integer", required=True),
}


def lookup_partner(partner_id):
    partner = store.partners.get(partner_id)
    if partner is None:
        raise ApiError("ERR_PARTNER_NOT_FOUND", "No partner with id %s" % partner_id)
    return partner


@bp.post("/partners")
def create_partner():
    current_user_id()
    require_role(config.ROLE_PLATFORM_ADMIN)
    body = parse_body(CREATE_SPEC)
    record = create_record(
        store.partners,
        {
            "name": body["name"],
            "utility_type": body["utility_type"],
            "state_code": body["state_code"],
            "status": "ONBOARDING",
            "brand_approval_required": True if body["brand_approval_required"] is None else body["brand_approval_required"],
            "min_days_between_drops": 21 if body["min_days_between_drops"] is None else body["min_days_between_drops"],
            "max_mailings_per_year": 2 if body["max_mailings_per_year"] is None else body["max_mailings_per_year"],
            "rate_filing_required": False if body["rate_filing_required"] is None else body["rate_filing_required"],
            "bill_insert_supported": True if body["bill_insert_supported"] is None else body["bill_insert_supported"],
            "suspension_reason": None,
        },
    )
    return object_response(serializers.partner(record), 201)


@bp.get("/partners")
def list_partners():
    current_user_id()
    require_role(*READ_ROLES)
    status = filter_enum("status", config.PARTNER_STATUSES)
    utility_type = filter_enum("utility_type", config.UTILITY_TYPES)
    state_code = filter_value("state_code")

    def matches(partner):
        if status is not None and partner["status"] != status:
            return False
        if utility_type is not None and partner["utility_type"] != utility_type:
            return False
        if state_code is not None and partner["state_code"] != state_code:
            return False
        return True

    return paginate(ordered(store.partners, matches), serializers.partner)


@bp.get("/partners/<partner_id>")
def get_partner(partner_id):
    current_user_id()
    require_role(*READ_ROLES)
    require_path_uuid(partner_id)
    return object_response(serializers.partner(lookup_partner(partner_id)))


@bp.post("/partners/<partner_id>/status-changes")
def change_partner_status(partner_id):
    current_user_id()
    require_role(config.ROLE_PLATFORM_ADMIN)
    require_path_uuid(partner_id)
    body = parse_body(STATUS_SPEC)
    partner = lookup_partner(partner_id)
    if body["expected_partner_version"] != partner["version"]:
        raise ApiError("ERR_STALE_PARTNER_VERSION", "The partner has changed since it was read")

    current = partner["status"]
    target = body["target_status"]
    permitted = {
        "ONBOARDING": ["ACTIVE"],
        "ACTIVE": ["SUSPENDED", "TERMINATED"],
        "SUSPENDED": ["ACTIVE", "TERMINATED"],
        "TERMINATED": [],
    }
    if target not in permitted.get(current, []):
        raise ApiError("ERR_INVALID_PARTNER_STATE", "A partner in %s may not move to %s" % (current, target))

    if target == "ACTIVE" and current == "ONBOARDING":
        available = [
            p
            for p in store.products.values()
            if p["partner_id"] == partner["id"] and p["status"] == "AVAILABLE"
        ]
        if not available:
            raise ApiError("ERR_NO_FILED_PRODUCT", "The partner has no product in AVAILABLE")

    partner["status"] = target
    if target == "ACTIVE":
        partner["suspension_reason"] = None
    else:
        partner["suspension_reason"] = body["reason"]
    touch(partner)

    if target == "SUSPENDED":
        cascades.withdraw_partner_campaigns(partner)
    elif target == "TERMINATED":
        cascades.withdraw_partner_campaigns(partner)
        cascades.withdraw_partner_products(partner)

    return object_response(serializers.partner(partner))

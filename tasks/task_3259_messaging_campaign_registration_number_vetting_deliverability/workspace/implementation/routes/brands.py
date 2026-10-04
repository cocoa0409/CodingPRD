"""Brand routes: CRUD, submit/verify/fail/revoke, sub-collections."""
from flask import Blueprint, request

import store
from constants import BUSINESS_TYPES, OPT_IN_MECHANISMS, COUNTRY_CODES, MAX_RESUBMISSIONS
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_BRAND_REVOKED,
    ERR_BRAND_SCORE_TOO_LOW,
    validation,
)
from response import success_object, success_list
from serializers import ser_brand, ser_campaign, ser_consent
from services.calc import identity_score
from services.shared import (
    cascade_suspend_campaign,
    check_account_gate,
    record_charge,
)
from util import (
    find_or_404,
    get_json_body,
    new_id,
    pagination_params,
    require_auth,
    require_enum,
    require_nonempty,
    sort_by_created,
    touch,
)

bp = Blueprint("brands", __name__)

BRAND_READ_ROLES = [
    "PlatformAdmin", "ComplianceOfficer", "BrandManager", "CampaignManager",
    "NumberProvisioner", "CarrierReviewer", "SystemDriver",
]
BRAND_LIST_ROLES = [
    "PlatformAdmin", "ComplianceOfficer", "BrandManager", "CampaignManager",
    "CarrierReviewer",
]

REQUIRED_BRAND_FIELDS = [
    "legal_name", "tax_id", "business_type", "address_line1", "city",
    "region_code", "postal_code", "country_code",
    "opt_in_mechanism",
]


@bp.post("/messaging/accounts/<account_id>/brands")
def create_brand(account_id):
    require_auth(["BrandManager", "PlatformAdmin"])
    account = find_or_404(store.ACCOUNTS, account_id)
    check_account_gate(account)
    body = get_json_body()
    require_nonempty(body, [
        "legal_name", "tax_id", "address_line1", "city", "region_code",
        "postal_code",
    ])
    business_type = require_enum(body, "business_type", BUSINESS_TYPES)
    country_code = require_enum(body, "country_code", COUNTRY_CODES)
    opt_in = require_enum(body, "opt_in_mechanism", OPT_IN_MECHANISMS)
    brand = {
        "id": new_id(),
        "created_at": store.now_iso(),
        "updated_at": store.now_iso(),
        "version": 1,
        "account_id": account_id,
        "legal_name": body["legal_name"],
        "tax_id": body["tax_id"],
        "business_type": business_type,
        "address_line1": body["address_line1"],
        "city": body["city"],
        "region_code": body["region_code"],
        "postal_code": body["postal_code"],
        "country_code": country_code,
        "website_url": body.get("website_url", ""),
        "opt_in_mechanism": opt_in,
        "identity_score": 0,
        "resubmission_count": 0,
        "status": "DRAFT",
        "verified_at": None,
    }
    store.BRANDS[brand["id"]] = brand
    return success_object(ser_brand(brand), 201)


@bp.get("/messaging/accounts/<account_id>/brands/<brand_id>")
def get_brand(account_id, brand_id):
    require_auth(BRAND_READ_ROLES)
    find_or_404(store.ACCOUNTS, account_id)
    brand = find_or_404(store.BRANDS, brand_id, account_id)
    return success_object(ser_brand(brand))


@bp.get("/messaging/brands/<brand_id>")
def get_brand_alias(brand_id):
    require_auth(BRAND_LIST_ROLES)
    brand = find_or_404(store.BRANDS, brand_id)
    return success_object(ser_brand(brand))


@bp.get("/messaging/accounts/<account_id>/brands")
def list_account_brands(account_id):
    require_auth(BRAND_LIST_ROLES)
    find_or_404(store.ACCOUNTS, account_id)
    limit, offset = pagination_params()
    items = [b for b in store.BRANDS.values() if b["account_id"] == account_id]
    status_filter = request.args.get("status")
    if status_filter:
        items = [b for b in items if b["status"] == status_filter]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_brand(b) for b in page], limit, offset, total)


@bp.get("/messaging/brands")
def list_brands():
    require_auth(["PlatformAdmin", "ComplianceOfficer"])
    limit, offset = pagination_params()
    items = list(store.BRANDS.values())
    account_filter = request.args.get("account_id")
    if account_filter:
        items = [b for b in items if b["account_id"] == account_filter]
    status_filter = request.args.get("status")
    if status_filter:
        items = [b for b in items if b["status"] == status_filter]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_brand(b) for b in page], limit, offset, total)


@bp.get("/messaging/accounts/<account_id>/brands/<brand_id>/campaigns")
def list_brand_campaigns(account_id, brand_id):
    require_auth(BRAND_LIST_ROLES)
    find_or_404(store.ACCOUNTS, account_id)
    find_or_404(store.BRANDS, brand_id, account_id)
    limit, offset = pagination_params()
    items = [
        c for c in store.CAMPAIGNS.values()
        if c["account_id"] == account_id and c["brand_id"] == brand_id
    ]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_campaign(c) for c in page], limit, offset, total)


@bp.get("/messaging/accounts/<account_id>/brands/<brand_id>/consent_records")
def list_brand_consent_records(account_id, brand_id):
    require_auth(BRAND_LIST_ROLES)
    find_or_404(store.ACCOUNTS, account_id)
    find_or_404(store.BRANDS, brand_id, account_id)
    limit, offset = pagination_params()
    items = [
        c for c in store.CONSENTS.values()
        if c["account_id"] == account_id and c["brand_id"] == brand_id
    ]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_consent(c) for c in page], limit, offset, total)


def _brand_submit(account, brand):
    if brand["status"] == "REVOKED":
        raise ApiError(ERR_BRAND_REVOKED, "Brand is revoked", 409)
    if brand["status"] not in ("DRAFT", "UNVERIFIED"):
        raise ApiError(ERR_INVALID_STATE, "Brand is not in a submittable state", 409)
    for f in REQUIRED_BRAND_FIELDS:
        v = brand.get(f)
        if not isinstance(v, str) or v.strip() == "":
            raise validation("Required brand field missing or empty: %s" % f)
    if brand["country_code"] != account["country_code"]:
        raise validation("brand.country_code must equal account.country_code")
    brand["identity_score"] = identity_score(brand)
    record_charge(account["id"], "BRAND_VETTING", "BRAND", brand["id"], 200)
    brand["status"] = "PENDING_VERIFICATION"
    touch(brand)


@bp.post("/messaging/accounts/<account_id>/brands/<brand_id>/submit")
def submit_brand(account_id, brand_id):
    require_auth(["BrandManager"])
    account = find_or_404(store.ACCOUNTS, account_id)
    brand = find_or_404(store.BRANDS, brand_id, account_id)
    check_account_gate(account)
    _brand_submit(account, brand)
    return success_object(ser_brand(brand))


@bp.post("/messaging/accounts/<account_id>/brands/<brand_id>/verify")
def verify_brand(account_id, brand_id):
    require_auth(["CarrierReviewer"])
    account = find_or_404(store.ACCOUNTS, account_id)
    brand = find_or_404(store.BRANDS, brand_id, account_id)
    check_account_gate(account)
    if brand["status"] == "REVOKED":
        raise ApiError(ERR_BRAND_REVOKED, "Brand is revoked", 409)
    if brand["status"] != "PENDING_VERIFICATION":
        raise ApiError(ERR_INVALID_STATE, "Brand is not PENDING_VERIFICATION", 409)
    if brand["identity_score"] < 60:
        raise ApiError(
            ERR_BRAND_SCORE_TOO_LOW,
            "Brand identity_score below verification minimum",
            409,
        )
    brand["status"] = "VERIFIED"
    brand["verified_at"] = store.now_iso()
    touch(brand)
    return success_object(ser_brand(brand))


@bp.post("/messaging/accounts/<account_id>/brands/<brand_id>/fail")
def fail_brand(account_id, brand_id):
    require_auth(["CarrierReviewer"])
    account = find_or_404(store.ACCOUNTS, account_id)
    brand = find_or_404(store.BRANDS, brand_id, account_id)
    check_account_gate(account)
    if brand["status"] == "REVOKED":
        raise ApiError(ERR_BRAND_REVOKED, "Brand is revoked", 409)
    if brand["status"] != "PENDING_VERIFICATION":
        raise ApiError(ERR_INVALID_STATE, "Brand is not PENDING_VERIFICATION", 409)
    brand["resubmission_count"] += 1
    if brand["resubmission_count"] >= MAX_RESUBMISSIONS:
        brand["status"] = "REVOKED"
    else:
        brand["status"] = "UNVERIFIED"
    touch(brand)
    return success_object(ser_brand(brand))


@bp.post("/messaging/accounts/<account_id>/brands/<brand_id>/revoke")
def revoke_brand(account_id, brand_id):
    require_auth(["ComplianceOfficer"])
    account = find_or_404(store.ACCOUNTS, account_id)
    brand = find_or_404(store.BRANDS, brand_id, account_id)
    check_account_gate(account)
    if brand["status"] == "REVOKED":
        raise ApiError(ERR_BRAND_REVOKED, "Brand is revoked", 409)
    if brand["status"] != "VERIFIED":
        raise ApiError(ERR_INVALID_STATE, "Brand is not VERIFIED", 409)
    body = get_json_body()
    reason = body.get("reason", "")
    if not isinstance(reason, str):
        raise validation("reason must be a string")
    brand["status"] = "REVOKED"
    touch(brand)
    campaigns = [
        c for c in store.CAMPAIGNS.values()
        if c["brand_id"] == brand_id and c["status"] == "APPROVED"
    ]
    for campaign in sort_by_created(campaigns):
        campaign["status"] = "SUSPENDED"
        touch(campaign)
        cascade_suspend_campaign(campaign, "CAMPAIGN_SUSPENDED")
    return success_object(ser_brand(brand))

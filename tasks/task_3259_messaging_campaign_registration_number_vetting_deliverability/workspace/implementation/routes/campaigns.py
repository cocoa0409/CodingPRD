"""Campaign routes: CRUD, submit/approve/reject/suspend/reactivate/deactivate,
sub-collections, snapshots."""
from flask import Blueprint, request

import store
from constants import (
    USE_CASES,
    PATH_KINDS,
    REJECTION_REASON_CODES,
    MAX_CAMPAIGN_RESUBMISSIONS,
)
from errors import (
    ApiError,
    ERR_BRAND_NOT_VERIFIED,
    ERR_TOLLFREE_VETTING_INSUFFICIENT,
    ERR_SHORT_CODE_GEO,
    ERR_SHORT_CODE_USE_CASE,
    ERR_CAMPAIGN_RESUBMISSION_LIMIT,
    ERR_CAMPAIGN_NOT_DEACTIVATABLE,
    ERR_ACCOUNT_SUSPENDED,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_REJECTION_REASON_INVALID,
    validation,
)
from response import success_object, success_list
from serializers import (
    ser_campaign,
    ser_number,
    ser_message,
    ser_feedback,
    ser_snapshot,
)
from services.calc import (
    compute_allocated_mps,
    initial_trust_score,
    recompute_trust_from_snapshot,
    snapshot_rates,
)
from services.shared import (
    cascade_suspend_campaign,
    check_account_gate,
    record_charge,
    spam_floor_check,
)
from util import (
    day_of,
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

bp = Blueprint("campaigns", __name__)

CAMPAIGN_READ_ROLES = [
    "PlatformAdmin", "ComplianceOfficer", "BrandManager", "CampaignManager",
    "NumberProvisioner", "CarrierReviewer", "SystemDriver",
]
CAMPAIGN_LIST_ROLES = [
    "PlatformAdmin", "ComplianceOfficer", "BrandManager", "CampaignManager",
    "NumberProvisioner", "CarrierReviewer",
]


@bp.post("/messaging/accounts/<account_id>/campaigns")
def create_campaign(account_id):
    require_auth(["CampaignManager", "PlatformAdmin"])
    account = find_or_404(store.ACCOUNTS, account_id)
    check_account_gate(account)
    body = get_json_body()
    require_nonempty(body, ["brand_id", "description", "help_message", "stop_message"])
    use_case = require_enum(body, "use_case", USE_CASES)
    path_kind = require_enum(body, "path_kind", PATH_KINDS)
    samples = body.get("sample_messages")
    if not isinstance(samples, list) or not (1 <= len(samples) <= 5):
        raise validation("sample_messages must contain 1 to 5 entries")
    for s in samples:
        if not isinstance(s, str) or s.strip() == "":
            raise validation("sample_messages entries must be non-empty strings")
    brand = store.BRANDS.get(body["brand_id"])
    if brand is None or brand["account_id"] != account_id:
        from errors import ERR_NOT_FOUND
        raise ApiError(ERR_NOT_FOUND, "Brand not found under account", 404)
    campaign = {
        "id": new_id(),
        "created_at": store.now_iso(),
        "updated_at": store.now_iso(),
        "version": 1,
        "account_id": account_id,
        "brand_id": brand["id"],
        "use_case": use_case,
        "description": body["description"],
        "sample_messages": samples,
        "help_message": body["help_message"],
        "stop_message": body["stop_message"],
        "path_kind": path_kind,
        "trust_score": 0,
        "allocated_mps": 0,
        "rejection_reason_code": "",
        "rejected_cycle_count": 0,
        "recurring_fee_last_charge_at": None,
        "status": "DRAFT",
    }
    store.CAMPAIGNS[campaign["id"]] = campaign
    return success_object(ser_campaign(campaign), 201)


@bp.get("/messaging/accounts/<account_id>/campaigns/<campaign_id>")
def get_campaign(account_id, campaign_id):
    require_auth(CAMPAIGN_READ_ROLES)
    find_or_404(store.ACCOUNTS, account_id)
    campaign = find_or_404(store.CAMPAIGNS, campaign_id, account_id)
    campaign["allocated_mps"] = compute_allocated_mps(campaign)
    return success_object(ser_campaign(campaign))


@bp.get("/messaging/campaigns/<campaign_id>")
def get_campaign_alias(campaign_id):
    require_auth(CAMPAIGN_READ_ROLES)
    campaign = find_or_404(store.CAMPAIGNS, campaign_id)
    campaign["allocated_mps"] = compute_allocated_mps(campaign)
    return success_object(ser_campaign(campaign))


@bp.get("/messaging/accounts/<account_id>/campaigns")
def list_account_campaigns(account_id):
    require_auth(CAMPAIGN_LIST_ROLES)
    find_or_404(store.ACCOUNTS, account_id)
    limit, offset = pagination_params()
    items = [c for c in store.CAMPAIGNS.values() if c["account_id"] == account_id]
    items = _filter_campaigns(items)
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_campaign(c) for c in page], limit, offset, total)


@bp.get("/messaging/accounts/<account_id>/campaigns/<campaign_id>/numbers")
def list_campaign_numbers(account_id, campaign_id):
    require_auth(CAMPAIGN_LIST_ROLES)
    find_or_404(store.ACCOUNTS, account_id)
    find_or_404(store.CAMPAIGNS, campaign_id, account_id)
    limit, offset = pagination_params()
    items = [
        n for n in store.NUMBERS.values()
        if n["account_id"] == account_id and n.get("campaign_id") == campaign_id
    ]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_number(n) for n in page], limit, offset, total)


@bp.get("/messaging/accounts/<account_id>/campaigns/<campaign_id>/messages")
def list_campaign_messages(account_id, campaign_id):
    require_auth(CAMPAIGN_LIST_ROLES)
    find_or_404(store.ACCOUNTS, account_id)
    find_or_404(store.CAMPAIGNS, campaign_id, account_id)
    limit, offset = pagination_params()
    items = [
        m for m in store.MESSAGES.values()
        if m["account_id"] == account_id and m["campaign_id"] == campaign_id
    ]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_message(m) for m in page], limit, offset, total)


@bp.get("/messaging/accounts/<account_id>/campaigns/<campaign_id>/feedback_events")
def list_campaign_feedback(account_id, campaign_id):
    require_auth(CAMPAIGN_LIST_ROLES)
    find_or_404(store.ACCOUNTS, account_id)
    find_or_404(store.CAMPAIGNS, campaign_id, account_id)
    limit, offset = pagination_params()
    items = [
        f for f in store.FEEDBACK.values()
        if f["account_id"] == account_id and f["campaign_id"] == campaign_id
    ]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_feedback(f) for f in page], limit, offset, total)


def _check_brand_gates(account, campaign, brand):
    """PRD 3.3 submit gates in order: verified, toll-free, short-code,
    resubmission cap (checked by caller for resubmit path)."""
    if brand["status"] != "VERIFIED":
        raise ApiError(ERR_BRAND_NOT_VERIFIED, "Brand is not VERIFIED", 409)
    if campaign["path_kind"] == "TOLL_FREE" and brand["identity_score"] < 75:
        raise ApiError(
            ERR_TOLLFREE_VETTING_INSUFFICIENT,
            "Brand identity_score below toll-free minimum",
            409,
        )
    if campaign["path_kind"] == "SHORT_CODE":
        if account["plan_tier"] != "PREMIUM" or account["country_code"] != "US":
            raise ApiError(
                ERR_SHORT_CODE_GEO,
                "SHORT_CODE requires US PREMIUM account",
                422,
            )
        if campaign["use_case"] != "MARKETING":
            raise ApiError(
                ERR_SHORT_CODE_USE_CASE,
                "SHORT_CODE campaigns must have use_case MARKETING",
                409,
            )


def _check_campaign_field_shape(campaign):
    for f in ("description", "help_message", "stop_message"):
        v = campaign.get(f)
        if not isinstance(v, str) or v.strip() == "":
            raise validation("Field must be non-empty: %s" % f)
    samples = campaign.get("sample_messages")
    if not isinstance(samples, list) or not (1 <= len(samples) <= 5):
        raise validation("sample_messages must contain 1 to 5 entries")


@bp.post("/messaging/accounts/<account_id>/campaigns/<campaign_id>/submit")
def submit_campaign(account_id, campaign_id):
    require_auth(["CampaignManager"])
    account = find_or_404(store.ACCOUNTS, account_id)
    campaign = find_or_404(store.CAMPAIGNS, campaign_id, account_id)
    check_account_gate(account)
    if campaign["status"] not in ("DRAFT", "REJECTED"):
        raise ApiError(ERR_INVALID_STATE, "Campaign is not in a submittable state", 409)
    brand = store.BRANDS.get(campaign["brand_id"])
    if brand is None or brand["account_id"] != account_id:
        from errors import ERR_NOT_FOUND
        raise ApiError(ERR_NOT_FOUND, "Brand not found under account", 404)
    _check_brand_gates(account, campaign, brand)
    if campaign["status"] == "REJECTED" and campaign["rejected_cycle_count"] >= MAX_CAMPAIGN_RESUBMISSIONS:
        raise ApiError(
            ERR_CAMPAIGN_RESUBMISSION_LIMIT,
            "Campaign resubmission cap reached",
            409,
        )
    _check_campaign_field_shape(campaign)
    body = get_json_body()
    if campaign["status"] == "REJECTED":
        expected = body.get("expected_campaign_version")
        if expected is None or expected != campaign["version"]:
            raise ApiError(
                ERR_STALE_VERSION,
                "expected_campaign_version does not match current version",
                412,
            )
    campaign["trust_score"] = initial_trust_score(campaign, brand)
    campaign["allocated_mps"] = compute_allocated_mps(campaign)
    record_charge(
        account_id, "CAMPAIGN_REGISTRATION", "CAMPAIGN", campaign["id"], 1500,
    )
    campaign["status"] = "PENDING_REVIEW"
    touch(campaign)
    return success_object(ser_campaign(campaign))


@bp.post("/messaging/accounts/<account_id>/campaigns/<campaign_id>/approve")
def approve_campaign(account_id, campaign_id):
    require_auth(["CarrierReviewer"])
    account = find_or_404(store.ACCOUNTS, account_id)
    campaign = find_or_404(store.CAMPAIGNS, campaign_id, account_id)
    check_account_gate(account)
    if campaign["status"] != "PENDING_REVIEW":
        raise ApiError(ERR_INVALID_STATE, "Campaign is not PENDING_REVIEW", 409)
    campaign["status"] = "APPROVED"
    touch(campaign)
    return success_object(ser_campaign(campaign))


@bp.post("/messaging/accounts/<account_id>/campaigns/<campaign_id>/reject")
def reject_campaign(account_id, campaign_id):
    require_auth(["CarrierReviewer"])
    account = find_or_404(store.ACCOUNTS, account_id)
    campaign = find_or_404(store.CAMPAIGNS, campaign_id, account_id)
    check_account_gate(account)
    if campaign["status"] != "PENDING_REVIEW":
        raise ApiError(ERR_INVALID_STATE, "Campaign is not PENDING_REVIEW", 409)
    body = get_json_body()
    code = body.get("rejection_reason_code")
    if code not in REJECTION_REASON_CODES:
        raise ApiError(
            ERR_REJECTION_REASON_INVALID,
            "rejection_reason_code is not a declared code",
            400,
        )
    campaign["rejection_reason_code"] = code
    campaign["rejected_cycle_count"] += 1
    campaign["status"] = "REJECTED"
    touch(campaign)
    return success_object(ser_campaign(campaign))


@bp.post("/messaging/accounts/<account_id>/campaigns/<campaign_id>/suspend")
def suspend_campaign(account_id, campaign_id):
    require_auth(["ComplianceOfficer"])
    account = find_or_404(store.ACCOUNTS, account_id)
    campaign = find_or_404(store.CAMPAIGNS, campaign_id, account_id)
    check_account_gate(account)
    if campaign["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, "Campaign is not APPROVED", 409)
    body = get_json_body()
    reason = body.get("reason", "")
    if not isinstance(reason, str):
        raise validation("reason must be a string")
    campaign["status"] = "SUSPENDED"
    touch(campaign)
    cascade_suspend_campaign(campaign, "CAMPAIGN_SUSPENDED")
    return success_object(ser_campaign(campaign))


@bp.post("/messaging/accounts/<account_id>/campaigns/<campaign_id>/reactivate")
def reactivate_campaign(account_id, campaign_id):
    require_auth(["ComplianceOfficer"])
    account = find_or_404(store.ACCOUNTS, account_id)
    campaign = find_or_404(store.CAMPAIGNS, campaign_id, account_id)
    if account["status"] != "ACTIVE":
        raise ApiError(ERR_ACCOUNT_SUSPENDED, "Account is not ACTIVE", 409)
    if campaign["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, "Campaign is not SUSPENDED", 409)
    brand = store.BRANDS.get(campaign["brand_id"])
    if brand is None or brand["status"] != "VERIFIED":
        raise ApiError(ERR_BRAND_NOT_VERIFIED, "Brand is not VERIFIED", 409)
    campaign["status"] = "APPROVED"
    touch(campaign)
    numbers = [
        n for n in store.NUMBERS.values()
        if n.get("campaign_id") == campaign_id
        and n["status"] == "SUSPENDED"
        and n["suspended_reason"] == "CAMPAIGN_SUSPENDED"
    ]
    for number in sort_by_created(numbers):
        number["status"] = "ACTIVE"
        number["suspended_reason"] = ""
        touch(number)
    return success_object(ser_campaign(campaign))


@bp.post("/messaging/accounts/<account_id>/campaigns/<campaign_id>/deactivate")
def deactivate_campaign(account_id, campaign_id):
    require_auth(["CampaignManager"])
    account = find_or_404(store.ACCOUNTS, account_id)
    campaign = find_or_404(store.CAMPAIGNS, campaign_id, account_id)
    check_account_gate(account)
    if campaign["status"] not in ("DRAFT", "REJECTED", "APPROVED"):
        raise ApiError(ERR_INVALID_STATE, "Campaign cannot be deactivated from this state", 409)
    attached_active = any(
        n.get("campaign_id") == campaign_id and n["status"] == "ACTIVE"
        for n in store.NUMBERS.values()
    )
    if attached_active:
        raise ApiError(
            ERR_CAMPAIGN_NOT_DEACTIVATABLE,
            "An ACTIVE sender number is attached to the campaign",
            409,
        )
    campaign["status"] = "DEACTIVATED"
    touch(campaign)
    return success_object(ser_campaign(campaign))


SNAPSHOT_ROLES = [
    "PlatformAdmin", "ComplianceOfficer", "CampaignManager",
    "DeliverabilityAnalyst",
]


@bp.post("/messaging/accounts/<account_id>/campaigns/<campaign_id>/snapshots")
def create_snapshot(account_id, campaign_id):
    require_auth(["DeliverabilityAnalyst", "PlatformAdmin"])
    account = find_or_404(store.ACCOUNTS, account_id)
    campaign = find_or_404(store.CAMPAIGNS, campaign_id, account_id)
    check_account_gate(account)
    body = get_json_body()
    day_utc = body.get("day_utc")
    if not isinstance(day_utc, str) or not __import__("re").match(r"^\d{4}-\d{2}-\d{2}$", day_utc):
        raise validation("day_utc must be a YYYY-MM-DD string")
    terminal = {"SENT", "DELIVERED", "UNDELIVERED", "FILTERED", "FAILED"}
    day_messages = [
        m for m in store.MESSAGES.values()
        if m["campaign_id"] == campaign_id
        and m["status"] in terminal
        and day_of(m["created_at"]) == day_utc
    ]
    attempted = len(day_messages)
    delivered = sum(1 for m in day_messages if m["status"] == "DELIVERED")
    blocked = sum(
        1 for f in store.FEEDBACK.values()
        if f["campaign_id"] == campaign_id
        and f["kind"] == "BLOCK"
        and day_of(f["created_at"]) == day_utc
    )
    spam = sum(
        1 for f in store.FEEDBACK.values()
        if f["campaign_id"] == campaign_id
        and f["kind"] == "SPAM_COMPLAINT"
        and day_of(f["created_at"]) == day_utc
    )
    pct, block_bps, spam_bps = snapshot_rates(attempted, delivered, blocked, spam)
    snapshot = {
        "id": new_id(),
        "created_at": store.now_iso(),
        "account_id": account_id,
        "campaign_id": campaign_id,
        "day_utc": day_utc,
        "attempted": attempted,
        "delivered": delivered,
        "blocked": blocked,
        "spam": spam,
        "delivery_rate_pct": pct,
        "block_rate_bps": block_bps,
        "spam_rate_bps": spam_bps,
    }
    store.SNAPSHOTS[snapshot["id"]] = snapshot

    # Trust recompute from this snapshot (penalties before bonus, clamp last).
    campaign["trust_score"] = recompute_trust_from_snapshot(
        campaign["trust_score"], snapshot
    )
    campaign["allocated_mps"] = compute_allocated_mps(campaign)
    touch(campaign)

    # Spam floor check (after trust recompute).
    spam_floor_check(campaign, snapshot)

    return success_object(ser_snapshot(snapshot), 201)


@bp.get("/messaging/accounts/<account_id>/campaigns/<campaign_id>/snapshots/<snapshot_id>")
def get_snapshot(account_id, campaign_id, snapshot_id):
    require_auth(SNAPSHOT_ROLES)
    find_or_404(store.ACCOUNTS, account_id)
    find_or_404(store.CAMPAIGNS, campaign_id, account_id)
    snapshot = find_or_404(store.SNAPSHOTS, snapshot_id, account_id)
    if snapshot["campaign_id"] != campaign_id:
        from errors import ERR_NOT_FOUND
        raise ApiError(ERR_NOT_FOUND, "Snapshot not nested under campaign", 404)
    return success_object(ser_snapshot(snapshot))


@bp.get("/messaging/accounts/<account_id>/campaigns/<campaign_id>/snapshots")
def list_campaign_snapshots(account_id, campaign_id):
    require_auth(SNAPSHOT_ROLES)
    find_or_404(store.ACCOUNTS, account_id)
    find_or_404(store.CAMPAIGNS, campaign_id, account_id)
    limit, offset = pagination_params()
    items = [
        s for s in store.SNAPSHOTS.values()
        if s["account_id"] == account_id and s["campaign_id"] == campaign_id
    ]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_snapshot(s) for s in page], limit, offset, total)


@bp.get("/messaging/snapshots/<snapshot_id>")
def get_snapshot_alias(snapshot_id):
    require_auth(["PlatformAdmin", "ComplianceOfficer", "DeliverabilityAnalyst"])
    snapshot = find_or_404(store.SNAPSHOTS, snapshot_id)
    return success_object(ser_snapshot(snapshot))


@bp.get("/messaging/snapshots")
def list_snapshots():
    require_auth(["PlatformAdmin", "ComplianceOfficer", "DeliverabilityAnalyst"])
    limit, offset = pagination_params()
    items = list(store.SNAPSHOTS.values())
    account_filter = request.args.get("account_id")
    if account_filter:
        items = [s for s in items if s["account_id"] == account_filter]
    campaign_filter = request.args.get("campaign_id")
    if campaign_filter:
        items = [s for s in items if s["campaign_id"] == campaign_filter]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_snapshot(s) for s in page], limit, offset, total)


def _filter_campaigns(items):
    status_filter = request.args.get("status")
    if status_filter:
        items = [c for c in items if c["status"] == status_filter]
    brand_filter = request.args.get("brand_id")
    if brand_filter:
        items = [c for c in items if c["brand_id"] == brand_filter]
    return items


@bp.get("/messaging/campaigns")
def list_campaigns():
    require_auth(["PlatformAdmin", "ComplianceOfficer"])
    limit, offset = pagination_params()
    items = list(store.CAMPAIGNS.values())
    account_filter = request.args.get("account_id")
    if account_filter:
        items = [c for c in items if c["account_id"] == account_filter]
    items = _filter_campaigns(items)
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_campaign(c) for c in page], limit, offset, total)

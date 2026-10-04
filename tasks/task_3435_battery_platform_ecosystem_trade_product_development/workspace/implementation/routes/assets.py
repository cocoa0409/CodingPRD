"""Service centers, One-Key asset accounts, and tracked assets."""
from flask import Blueprint, request

import db
from constants import (
    ACCOUNT_TIERS,
    API_PREFIX,
    ASSET_STATUSES,
    CENTER_CAPABILITIES,
    ROLES,
    SUBJECT_TYPES,
)
from errors import fail
from helpers import (
    authorize,
    body,
    check_enum,
    check_int,
    check_num,
    ok_list,
    ok_object,
    pagination,
    page_window,
    parse_dt,
    present,
    req_field,
    req_int,
    req_str,
)
from services import (
    account_active_count,
    account_asset_limit,
    bump,
    make_entity,
)
from views import view_account, view_asset, view_center

bp = Blueprint("assets", __name__)

# TrackedAsset edges: ACTIVE -> REPORTED_LOST -> ACTIVE; either -> DECOMMISSIONED.
ASSET_EDGES = {
    "ACTIVE": {"REPORTED_LOST", "DECOMMISSIONED"},
    "REPORTED_LOST": {"ACTIVE", "DECOMMISSIONED"},
    "DECOMMISSIONED": set(),
}


@bp.route(f"{API_PREFIX}/service-centers", methods=["POST"])
def create_center():
    authorize(["PlatformAdmin"])
    data = body()
    code = req_str(data, "code")
    region = req_str(data, "region")
    capabilities = req_field(data, "capabilities")
    if (
        not isinstance(capabilities, list)
        or not capabilities
        or any(not isinstance(c, str) or c not in CENTER_CAPABILITIES for c in capabilities)
    ):
        fail("ERR_VALIDATION", "capabilities must be a non-empty subset of "
                               "[TOOL_REPAIR, BATTERY_SERVICE]")
    daily_capacity = req_int(data, "daily_capacity", minimum=1)
    for c in db.STORE["centers"].values():
        if c["code"] == code:
            fail("ERR_DUPLICATE_SKU", "A service center with this code already exists")
    center = make_entity(
        {
            "code": code,
            "region": region,
            "capabilities": list(capabilities),
            "daily_capacity": daily_capacity,
        }
    )
    db.STORE["centers"][center["id"]] = center
    return ok_object(view_center(center), 201)


@bp.route(f"{API_PREFIX}/asset-accounts", methods=["POST"])
def create_account():
    authorize(["PlatformAdmin"])
    data = body()
    org_name = req_str(data, "org_name")
    tier = check_enum(req_field(data, "tier"), "tier", ACCOUNT_TIERS)
    account = make_entity({"org_name": org_name, "tier": tier})
    db.STORE["accounts"][account["id"]] = account
    return ok_object(view_account(account), 201)


def _get_asset_or_404(asset_id):
    asset = db.STORE["assets"].get(asset_id)
    if asset is None:
        fail("ERR_NOT_FOUND", "Tracked asset not found")
    return asset


def _check_asset_ownership(user_id, asset):
    if user_id != asset["account_id"]:
        fail("ERR_FORBIDDEN", "X-User-ID does not match the asset's account_id")


@bp.route(f"{API_PREFIX}/tracked-assets", methods=["POST"])
def create_asset():
    user_id, _ = authorize(["AccountManager"])
    data = body()
    # Priority 4: account existence, then Priority 3 ownership.
    account_id = req_field(data, "account_id")
    account = db.STORE["accounts"].get(account_id)
    if account is None:
        fail("ERR_NOT_FOUND", "account_id does not reference an existing account")
    if user_id != account_id:
        fail("ERR_FORBIDDEN", "X-User-ID does not match account_id")
    # Priority 4: existence of any provided subject FKs
    tool_model_id = data.get("tool_model_id")
    battery_pack_id = data.get("battery_pack_id")
    if tool_model_id is not None and db.STORE["tools"].get(tool_model_id) is None:
        fail("ERR_NOT_FOUND", "tool_model_id does not reference an existing tool")
    if battery_pack_id is not None and db.STORE["packs"].get(battery_pack_id) is None:
        fail("ERR_NOT_FOUND", "battery_pack_id does not reference an existing pack")
    # Priority 5: request shape incl. subject-FK matching
    subject_type = check_enum(req_field(data, "subject_type"), "subject_type", SUBJECT_TYPES)
    if subject_type == "TOOL":
        if tool_model_id is None or battery_pack_id is not None:
            fail("ERR_VALIDATION", "TOOL assets require tool_model_id and forbid "
                                   "battery_pack_id")
    else:
        if battery_pack_id is None or tool_model_id is not None:
            fail("ERR_VALIDATION", "BATTERY assets require battery_pack_id and forbid "
                                   "tool_model_id")
    serial_number = req_str(data, "serial_number")
    manufactured_at = parse_dt(req_field(data, "manufactured_at"), "manufactured_at")
    # Priority 11: serial uniqueness
    for a in db.STORE["assets"].values():
        if a["serial_number"] == serial_number:
            fail("ERR_DUPLICATE_SERIAL", "serial_number already registered")
    # Priority 22: account asset limit (inclusive maximum)
    if account_active_count(account["id"]) >= account_asset_limit(account):
        fail("ERR_ASSET_LIMIT_EXCEEDED", "Account already holds its full asset limit")
    asset = make_entity(
        {
            "account_id": account_id,
            "subject_type": subject_type,
            "tool_model_id": tool_model_id,
            "battery_pack_id": battery_pack_id,
            "serial_number": serial_number,
            "manufactured_at": manufactured_at,
            "first_paired_at": db.clock_now(),
            "status": "ACTIVE",
            "custom_torque_limit_nm": None,
            "anti_theft_lock_enabled": False,
            "is_replacement_unit": False,
        }
    )
    db.STORE["assets"][asset["id"]] = asset
    return ok_object(view_asset(asset), 201)


@bp.route(f"{API_PREFIX}/tracked-assets/<asset_id>", methods=["GET"])
def get_asset(asset_id):
    authorize(ROLES)
    return ok_object(view_asset(_get_asset_or_404(asset_id)))


@bp.route(f"{API_PREFIX}/tracked-assets", methods=["GET"])
def list_assets():
    authorize(ROLES)
    limit, offset = pagination()
    items = list(db.STORE["assets"].values())
    for f in ("account_id", "tool_model_id", "battery_pack_id"):
        v = request.args.get(f)
        if v is not None:
            items = [a for a in items if a.get(f) == v]
    page, total = page_window(items, limit, offset)
    return ok_list([view_asset(a) for a in page], total, limit, offset)


@bp.route(f"{API_PREFIX}/tracked-assets/<asset_id>/customize", methods=["POST"])
def customize_asset(asset_id):
    user_id, _ = authorize(["AccountManager"])
    asset = _get_asset_or_404(asset_id)
    _check_asset_ownership(user_id, asset)
    data = body()
    # Priority 5: shape (OCC field required; torque rules)
    expected = check_int(req_field(data, "expected_tracked_asset_version"),
                         "expected_tracked_asset_version")
    new_torque = None
    if present(data, "custom_torque_limit_nm"):
        new_torque = check_num(data["custom_torque_limit_nm"], "custom_torque_limit_nm")
        if asset["subject_type"] != "TOOL":
            fail("ERR_VALIDATION", "custom_torque_limit_nm applies to TOOL assets only")
        tool = db.STORE["tools"][asset["tool_model_id"]]
        if not (tool["torque_min_nm"] <= new_torque <= tool["torque_max_nm"]):
            fail("ERR_VALIDATION", "custom_torque_limit_nm outside the model's range")
    new_lock = None
    if present(data, "anti_theft_lock_enabled"):
        if not isinstance(data["anti_theft_lock_enabled"], bool):
            fail("ERR_VALIDATION", "anti_theft_lock_enabled must be a boolean")
        new_lock = data["anti_theft_lock_enabled"]
    # Priority 6: asset must be ACTIVE
    if asset["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "Asset is not ACTIVE")
    # Priority 8: optimistic concurrency
    if expected != asset["version"]:
        fail("ERR_STALE_VERSION", "expected_tracked_asset_version does not match")
    if new_torque is not None:
        asset["custom_torque_limit_nm"] = new_torque
    if new_lock is not None:
        asset["anti_theft_lock_enabled"] = new_lock
    bump(asset)
    return ok_object(view_asset(asset))


@bp.route(f"{API_PREFIX}/tracked-assets/<asset_id>/transition", methods=["POST"])
def transition_asset(asset_id):
    user_id, _ = authorize(["AccountManager"])
    asset = _get_asset_or_404(asset_id)
    _check_asset_ownership(user_id, asset)
    data = body()
    to_status = check_enum(req_field(data, "to_status"), "to_status", ASSET_STATUSES)
    if to_status not in ASSET_EDGES[asset["status"]]:
        fail("ERR_INVALID_STATE", f"Cannot transition {asset['status']} -> {to_status}")
    asset["status"] = to_status
    bump(asset)
    return ok_object(view_asset(asset))

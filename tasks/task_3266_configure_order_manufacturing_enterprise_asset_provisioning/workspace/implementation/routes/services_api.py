from flask import Blueprint, request
from db import STORE, new_entity, touch, logical_now
from errors import (ApiError, err_invalid_request, err_invalid_state,
                    ERR_PARTS_STOCKING_REQUIRED, ERR_ENTITLEMENT_OVERLAP,
                    ERR_ASSET_NOT_RECOVERABLE, ERR_INVALID_STATE)
from middleware import require_roles, require_ownership
from helpers import (get_json_body, require_field, optional_field, get_pagination,
                     paginate, store_lookup, ser_entitlement, ser_recovery,
                     parse_iso8601, iso_z, iso_z_logical, chassis_of_line)
from response import success_object, success_list
from services.core import round_half_up_cents, ESTIMATE_PCT, GRADE_PCT

bp = Blueprint("services_api", __name__)

TIERS = {"BASIC", "NBD", "ONSITE_4H"}
PROGRAM_KINDS = {"RECYCLE", "RESALE_CREDIT"}


# ---------------- support entitlements ----------------

@bp.post("/api/order-lines/<lid>/support-entitlements")
def create_entitlement(lid):
    require_roles("AccountManager")
    line = store_lookup("order_lines", lid)
    body = get_json_body()
    tier = require_field(body, "tier", str, enum=TIERS)
    start_raw = require_field(body, "coverage_start", str)
    end_raw = require_field(body, "coverage_end", str)
    start_dt = parse_iso8601(start_raw, "coverage_start")
    end_dt = parse_iso8601(end_raw, "coverage_end")
    parts_required = optional_field(body, "parts_stocking_required", bool, default=False)
    reserved_part_id = optional_field(body, "reserved_part_component_id", str, default=None)
    # priority 16: parts-stocking guard before entitlement overlap (priority 17)
    reserved_comp = None
    chassis = chassis_of_line(line)
    if tier == "ONSITE_4H" and chassis is not None and chassis["category"] == "SERVER":
        if not parts_required or reserved_part_id is None:
            raise ApiError(ERR_PARTS_STOCKING_REQUIRED,
                           "ONSITE_4H on SERVER chassis requires parts stocking", 422)
        reserved_comp = STORE.components.get(reserved_part_id)
        if reserved_comp is None:
            raise ApiError(ERR_PARTS_STOCKING_REQUIRED, "Reserved part not found", 422)
        if reserved_comp["stock_on_hand"] - reserved_comp["reserved_units"] < 1:
            raise ApiError(ERR_PARTS_STOCKING_REQUIRED,
                           "No reservable part stock available", 422)
    elif parts_required and reserved_part_id is not None:
        reserved_comp = STORE.components.get(reserved_part_id)
        if reserved_comp is None:
            raise ApiError(ERR_PARTS_STOCKING_REQUIRED, "Reserved part not found", 422)
        if reserved_comp["stock_on_hand"] - reserved_comp["reserved_units"] < 1:
            raise ApiError(ERR_PARTS_STOCKING_REQUIRED,
                           "No reservable part stock available", 422)
    # priority 17: closed-interval overlap with ACTIVE entitlement of same line+tier
    for e in STORE.entitlements.values():
        if e["order_line_id"] != lid or e["tier"] != tier or e["status"] != "ACTIVE":
            continue
        es = parse_iso8601(e["coverage_start"])
        ee = parse_iso8601(e["coverage_end"])
        if start_dt <= ee and es <= end_dt:
            raise ApiError(ERR_ENTITLEMENT_OVERLAP,
                           "Coverage window duplicates an ACTIVE entitlement for same line and tier", 422)
    ent = new_entity()
    ent.update({
        "order_line_id": lid,
        "tier": tier,
        "coverage_start": iso_z(start_dt),
        "coverage_end": iso_z(end_dt),
        "parts_stocking_required": parts_required,
        "reserved_part_component_id": reserved_part_id,
        "status": "ACTIVE",
    })
    STORE.entitlements[ent["id"]] = ent
    if parts_required and reserved_comp is not None:
        reserved_comp["reserved_units"] += 1
        touch(reserved_comp)
    return success_object(ser_entitlement(ent), 201)


@bp.get("/api/order-lines/<lid>/support-entitlements")
def list_line_entitlements(lid):
    uid, role = require_roles("PlatformAdmin", "AccountManager", "CustomerUser")
    line = store_lookup("order_lines", lid)
    order = STORE.orders.get(line["order_id"])
    if order:
        require_ownership(order["account_id"], uid, role)
    limit, offset = get_pagination()
    items = [e for e in STORE.entitlements.values() if e["order_line_id"] == lid]
    items, total = paginate(items, limit, offset)
    return success_list([ser_entitlement(e) for e in items], limit, offset, total)


@bp.get("/api/support-entitlements")
def list_entitlements():
    require_roles("PlatformAdmin", "AccountManager")
    limit, offset = get_pagination()
    items = list(STORE.entitlements.values())
    for f in ("order_line_id", "tier", "reserved_part_component_id"):
        v = request.args.get(f)
        if v is not None:
            items = [e for e in items if e[f] == v]
    items, total = paginate(items, limit, offset)
    return success_list([ser_entitlement(e) for e in items], limit, offset, total)


@bp.get("/api/support-entitlements/<eid>")
def get_entitlement(eid):
    uid, role = require_roles("PlatformAdmin", "AccountManager", "CustomerUser")
    ent = store_lookup("entitlements", eid)
    line = STORE.order_lines.get(ent["order_line_id"])
    order = STORE.orders.get(line["order_id"]) if line else None
    if order:
        require_ownership(order["account_id"], uid, role)
    return success_object(ser_entitlement(ent))


@bp.post("/api/support-entitlements/<eid>/cancel")
def cancel_entitlement(eid):
    require_roles("AccountManager")
    ent = store_lookup("entitlements", eid)
    if ent["status"] != "ACTIVE":
        raise err_invalid_state("Entitlement is not ACTIVE")
    ent["status"] = "CANCELLED"
    touch(ent)
    if ent.get("parts_stocking_required") and ent.get("reserved_part_component_id"):
        comp = STORE.components.get(ent["reserved_part_component_id"])
        if comp is not None:
            comp["reserved_units"] -= 1
            touch(comp)
    return success_object(ser_entitlement(ent))


# ---------------- asset recovery ----------------

def _line_unit_price(line):
    cfg = STORE.configurations.get(line["configuration_id"]) if line else None
    if cfg is None:
        return 0
    chassis = STORE.chassis_models.get(cfg["chassis_model_id"])
    total = chassis["base_price_cents"] if chassis else 0
    for s in cfg["component_selections"]:
        comp = STORE.components.get(s["component_id"])
        if comp:
            total += comp["price_cents"] * s["qty"]
    return total


@bp.post("/api/asset-recovery-requests")
def create_recovery():
    uid, role = require_roles("CustomerUser")
    body = get_json_body()
    account_id = require_field(body, "account_id", str)
    store_lookup("accounts", account_id)
    require_ownership(account_id, uid, role)
    asset_id = require_field(body, "asset_id", str)
    asset = store_lookup("assets", asset_id)
    program_kind = require_field(body, "program_kind", str, enum=PROGRAM_KINDS)
    if asset["status"] != "DELIVERED":
        raise ApiError(ERR_ASSET_NOT_RECOVERABLE,
                       "Recovery requested for an asset not in DELIVERED status", 422)
    ent = new_entity()
    ent.update({
        "account_id": account_id,
        "asset_id": asset_id,
        "program_kind": program_kind,
        "estimated_credit_cents": None,
        "final_credit_cents": None,
        "status": "INITIATED",
    })
    STORE.recovery_requests[ent["id"]] = ent
    return success_object(ser_recovery(ent), 201)


@bp.get("/api/accounts/<aid>/asset-recovery-requests")
def list_account_recovery(aid):
    uid, role = require_roles("PlatformAdmin", "AccountManager", "CustomerUser")
    store_lookup("accounts", aid)
    require_ownership(aid, uid, role)
    limit, offset = get_pagination()
    items = [r for r in STORE.recovery_requests.values() if r["account_id"] == aid]
    items, total = paginate(items, limit, offset)
    return success_list([ser_recovery(r) for r in items], limit, offset, total)


@bp.get("/api/asset-recovery-requests/<rid>")
def get_recovery(rid):
    uid, role = require_roles("PlatformAdmin", "AccountManager", "CustomerUser")
    ent = store_lookup("recovery_requests", rid)
    require_ownership(ent["account_id"], uid, role)
    return success_object(ser_recovery(ent))


@bp.get("/api/asset-recovery-requests")
def list_recovery():
    require_roles("PlatformAdmin", "AccountManager")
    limit, offset = get_pagination()
    items = list(STORE.recovery_requests.values())
    for f in ("asset_id", "account_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [r for r in items if r[f] == v]
    items, total = paginate(items, limit, offset)
    return success_list([ser_recovery(r) for r in items], limit, offset, total)


@bp.post("/api/asset-recovery-requests/<rid>/issue-label")
def issue_label(rid):
    require_roles("PlatformAdmin")
    ent = store_lookup("recovery_requests", rid)
    if ent["status"] != "INITIATED":
        raise err_invalid_state("Recovery request is not INITIATED")
    asset = STORE.assets.get(ent["asset_id"])
    if asset is None or asset["status"] != "DELIVERED":
        raise err_invalid_state("Asset is not DELIVERED")
    line = STORE.order_lines.get(asset["order_line_id"])
    unit_price = _line_unit_price(line)
    ent["estimated_credit_cents"] = round_half_up_cents(ESTIMATE_PCT * unit_price)
    ent["status"] = "LABEL_ISSUED"
    touch(ent)
    asset["status"] = "RECOVERY_REQUESTED"
    touch(asset)
    return success_object(ser_recovery(ent))


@bp.post("/api/asset-recovery-requests/<rid>/receive")
def receive_recovery(rid):
    require_roles("PlatformAdmin")
    ent = store_lookup("recovery_requests", rid)
    if ent["status"] != "LABEL_ISSUED":
        raise err_invalid_state("Recovery request is not LABEL_ISSUED")
    asset = STORE.assets.get(ent["asset_id"])
    if asset is None or asset["status"] != "RECOVERY_REQUESTED":
        raise err_invalid_state("Asset is not RECOVERY_REQUESTED")
    body = get_json_body()
    grade = require_field(body, "grade", str)
    if grade not in GRADE_PCT:
        raise err_invalid_request("grade must be one of: poor, fair, good")
    line = STORE.order_lines.get(asset["order_line_id"])
    unit_price = _line_unit_price(line)
    ent["final_credit_cents"] = round_half_up_cents(GRADE_PCT[grade] * unit_price)
    ent["status"] = "RECEIVED"
    touch(ent)
    return success_object(ser_recovery(ent))


@bp.post("/api/asset-recovery-requests/<rid>/credit")
def credit_recovery(rid):
    require_roles("PlatformAdmin")
    ent = store_lookup("recovery_requests", rid)
    if ent["status"] != "RECEIVED":
        raise err_invalid_state("Recovery request is not RECEIVED")
    if ent["program_kind"] != "RESALE_CREDIT":
        raise err_invalid_state("Recovery request is not RESALE_CREDIT")
    account = STORE.accounts.get(ent["account_id"])
    if account is not None:
        account["recovery_credit_cents"] += ent["final_credit_cents"] or 0
        touch(account)
    asset = STORE.assets.get(ent["asset_id"])
    if asset is not None:
        asset["status"] = "RECOVERED"
        touch(asset)
    ent["status"] = "CREDITED"
    touch(ent)
    return success_object(ser_recovery(ent))


@bp.post("/api/asset-recovery-requests/<rid>/recycle")
def recycle_recovery(rid):
    require_roles("PlatformAdmin")
    ent = store_lookup("recovery_requests", rid)
    if ent["status"] != "RECEIVED":
        raise err_invalid_state("Recovery request is not RECEIVED")
    if ent["program_kind"] != "RECYCLE":
        raise err_invalid_state("Recovery request is not RECYCLE")
    asset = STORE.assets.get(ent["asset_id"])
    if asset is not None:
        asset["status"] = "RECOVERED"
        touch(asset)
    ent["status"] = "RECYCLED"
    touch(ent)
    return success_object(ser_recovery(ent))


@bp.post("/api/asset-recovery-requests/<rid>/cancel")
def cancel_recovery(rid):
    uid, role = require_roles("CustomerUser")
    ent = store_lookup("recovery_requests", rid)
    require_ownership(ent["account_id"], uid, role)
    if ent["status"] != "INITIATED":
        raise err_invalid_state("Recovery request is not INITIATED")
    ent["status"] = "CANCELLED"
    touch(ent)
    return success_object(ser_recovery(ent))


# ---------------- logical clock ----------------

@bp.post("/api/_clock/set_current_utc")
def set_clock():
    require_roles("PlatformAdmin")
    body = get_json_body()
    to = require_field(body, "to_iso8601", str)
    dt = parse_iso8601(to, "to_iso8601")
    from db import set_logical_now
    set_logical_now(dt)
    return success_object({"current_utc": iso_z_logical(dt)})

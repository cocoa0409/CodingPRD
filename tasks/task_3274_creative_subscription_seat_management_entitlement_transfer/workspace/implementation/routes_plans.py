"""Plans, ProductVersions, Resellers routes."""

from flask import Blueprint, request

from db import db
from errors import (
    err_invalid_request,
    err_not_found,
    err_reference_not_found,
    err_invalid_state,
    err_no_available_version,
    err_deadline_not_future,
)
from helpers import make_record, touch, require_fields, require_enum, require_int
from middleware import get_identity, require_role, resolve_identity, require_org_scope
from response import success_object, success_list, paginate, now_dt, parse_iso

bp = Blueprint("plans", __name__)


# ---------------- plans ----------------

@bp.post("/licensing/plans")
def create_plan():
    identity = get_identity()
    require_role(identity, ["SystemAdmin"])
    resolve_identity(identity)
    payload = request.get_json(silent=True)
    require_fields(payload, [
        "code", "segment", "billing_model", "monthly_price_cents",
        "annual_monthly_price_cents", "storage_gb_per_seat", "seat_limit",
        "deployment_modes", "allows_offline_activation",
        "cancellation_window_days", "etf_rate_pct",
    ])
    require_enum(payload, "segment", {"INDIVIDUAL", "TEAM", "ENTERPRISE"})
    require_enum(payload, "billing_model", {"MONTHLY", "ANNUAL_MONTHLY_BILLED", "ANNUAL_PREPAID"})
    require_int(payload, "monthly_price_cents", minimum=0)
    require_int(payload, "annual_monthly_price_cents", minimum=0)
    require_int(payload, "storage_gb_per_seat", minimum=0)
    seat_limit = require_int(payload, "seat_limit", allow_negative_one=True)
    if seat_limit < -1:
        raise err_invalid_request("seat_limit must be >= -1")
    modes = payload["deployment_modes"]
    if not isinstance(modes, list) or not modes or not set(modes) <= {"NAMED_USER", "SERIALIZED", "SHARED_DEVICE"}:
        raise err_invalid_request("deployment_modes must be a non-empty subset of allowed modes")
    if not isinstance(payload["allows_offline_activation"], bool):
        raise err_invalid_request("allows_offline_activation must be a boolean")
    require_int(payload, "cancellation_window_days", minimum=0)
    etf = require_int(payload, "etf_rate_pct", minimum=0)
    if etf > 100:
        raise err_invalid_request("etf_rate_pct must be 0..100")
    max_devices = payload.get("max_devices_per_seat", 2)
    if isinstance(max_devices, bool) or not isinstance(max_devices, int) or max_devices < 0:
        raise err_invalid_request("max_devices_per_seat must be a non-negative integer")
    rec = make_record({
        "code": payload["code"],
        "segment": payload["segment"],
        "billing_model": payload["billing_model"],
        "monthly_price_cents": payload["monthly_price_cents"],
        "annual_monthly_price_cents": payload["annual_monthly_price_cents"],
        "storage_gb_per_seat": payload["storage_gb_per_seat"],
        "seat_limit": seat_limit,
        "deployment_modes": list(modes),
        "allows_offline_activation": payload["allows_offline_activation"],
        "max_devices_per_seat": max_devices,
        "cancellation_window_days": payload["cancellation_window_days"],
        "etf_rate_pct": etf,
    })
    db["plans"][rec["id"]] = rec
    return success_object(rec, 201)


@bp.get("/licensing/plans/<pid>")
def get_plan(pid):
    identity = get_identity()
    require_role(identity, ["SystemAdmin", "OrgAdmin", "DeploymentAdmin", "ResellerAgent"])
    resolve_identity(identity)
    plan = db["plans"].get(pid)
    if plan is None:
        raise err_not_found("Plan not found")
    return success_object(plan)


# ---------------- product versions ----------------

@bp.post("/licensing/product-versions")
def create_product_version():
    identity = get_identity()
    require_role(identity, ["SystemAdmin"])
    resolve_identity(identity)
    payload = request.get_json(silent=True)
    require_fields(payload, ["plan_id", "version_label", "release_date"])
    if payload["plan_id"] not in db["plans"]:
        raise err_reference_not_found("plan_id does not exist")
    try:
        parse_iso(payload["release_date"])
    except Exception:
        raise err_invalid_request("release_date must be ISO8601")
    rec = make_record({
        "plan_id": payload["plan_id"],
        "version_label": payload["version_label"],
        "release_date": payload["release_date"],
        "availability": "AVAILABLE",
        "forced_upgrade_deadline": payload.get("forced_upgrade_deadline"),
    })
    db["product_versions"][rec["id"]] = rec
    return success_object(rec, 201)


@bp.get("/licensing/product-versions")
def list_product_versions():
    identity = get_identity()
    require_role(identity, ["SystemAdmin", "OrgAdmin", "DeploymentAdmin"])
    resolve_identity(identity)
    items = list(db["product_versions"].values())
    pid = request.args.get("plan_id")
    if pid is not None:
        items = [v for v in items if v["plan_id"] == pid]
    av = request.args.get("availability")
    if av is not None:
        items = [v for v in items if v["availability"] == av]
    items.sort(key=lambda v: v["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/licensing/product-versions/<vid>")
def get_product_version(vid):
    identity = get_identity()
    require_role(identity, ["SystemAdmin", "OrgAdmin", "DeploymentAdmin"])
    resolve_identity(identity)
    pv = db["product_versions"].get(vid)
    if pv is None:
        raise err_not_found("ProductVersion not found")
    return success_object(pv)


@bp.post("/licensing/product-versions/<vid>/deprecate")
def deprecate_product_version(vid):
    identity = get_identity()
    require_role(identity, ["SystemAdmin"])
    resolve_identity(identity)
    pv = db["product_versions"].get(vid)
    if pv is None:
        raise err_not_found("ProductVersion not found")
    if pv["availability"] != "AVAILABLE":
        raise err_invalid_state("Version is not AVAILABLE")
    others = [
        v for v in db["product_versions"].values()
        if v["plan_id"] == pv["plan_id"] and v["id"] != vid and v["availability"] == "AVAILABLE"
    ]
    if not others:
        raise err_no_available_version("Deprecating would leave plan with no AVAILABLE version")
    pv["availability"] = "DEPRECATED"
    touch(pv)
    return success_object(pv)


@bp.post("/licensing/product-versions/<vid>/restore")
def restore_product_version(vid):
    identity = get_identity()
    require_role(identity, ["SystemAdmin"])
    resolve_identity(identity)
    pv = db["product_versions"].get(vid)
    if pv is None:
        raise err_not_found("ProductVersion not found")
    if pv["availability"] != "DEPRECATED":
        raise err_invalid_state("Version is not DEPRECATED")
    pv["availability"] = "AVAILABLE"
    touch(pv)
    return success_object(pv)


@bp.post("/licensing/product-versions/<vid>/force-upgrade")
def force_upgrade_product_version(vid):
    identity = get_identity()
    require_role(identity, ["SystemAdmin"])
    resolve_identity(identity)
    pv = db["product_versions"].get(vid)
    if pv is None:
        raise err_not_found("ProductVersion not found")
    if pv["availability"] != "DEPRECATED":
        raise err_invalid_state("Version is not DEPRECATED")
    payload = request.get_json(silent=True)
    require_fields(payload, ["forced_upgrade_deadline"])
    try:
        deadline = parse_iso(payload["forced_upgrade_deadline"])
    except Exception:
        raise err_invalid_request("forced_upgrade_deadline must be ISO8601")
    if deadline <= now_dt():
        raise err_deadline_not_future()
    pv["availability"] = "FORCED_UPGRADE"
    pv["forced_upgrade_deadline"] = payload["forced_upgrade_deadline"]
    touch(pv)
    return success_object(pv)


# ---------------- resellers ----------------

@bp.post("/licensing/resellers")
def create_reseller():
    identity = get_identity()
    require_role(identity, ["SystemAdmin"])
    resolve_identity(identity)
    payload = request.get_json(silent=True)
    require_fields(payload, ["name", "region", "tier"])
    require_enum(payload, "region", {"NA", "EMEA", "APAC", "LATAM"})
    require_enum(payload, "tier", {"CERTIFIED", "GOLD", "PLATINUM"})
    rec = make_record({
        "name": payload["name"],
        "region": payload["region"],
        "tier": payload["tier"],
        "status": "ACTIVE",
    })
    db["resellers"][rec["id"]] = rec
    return success_object(rec, 201)


@bp.get("/licensing/resellers/<rid>")
def get_reseller(rid):
    identity = get_identity()
    require_role(identity, ["SystemAdmin", "ResellerAgent"])
    resolve_identity(identity)
    reseller = db["resellers"].get(rid)
    if reseller is None:
        raise err_not_found("Reseller not found")
    if identity.role == "ResellerAgent" and identity.user_id != rid:
        from errors import err_identity_mismatch
        raise err_identity_mismatch("ResellerAgent may only read own reseller record")
    return success_object(reseller)


@bp.post("/licensing/resellers/<rid>/suspend")
def suspend_reseller(rid):
    identity = get_identity()
    require_role(identity, ["SystemAdmin"])
    resolve_identity(identity)
    reseller = db["resellers"].get(rid)
    if reseller is None:
        raise err_not_found("Reseller not found")
    if reseller["status"] != "ACTIVE":
        raise err_invalid_state("Reseller is not ACTIVE")
    reseller["status"] = "SUSPENDED"
    touch(reseller)
    return success_object(reseller)


@bp.post("/licensing/resellers/<rid>/reinstate")
def reinstate_reseller(rid):
    identity = get_identity()
    require_role(identity, ["SystemAdmin"])
    resolve_identity(identity)
    reseller = db["resellers"].get(rid)
    if reseller is None:
        raise err_not_found("Reseller not found")
    if reseller["status"] != "SUSPENDED":
        raise err_invalid_state("Reseller is not SUSPENDED")
    reseller["status"] = "ACTIVE"
    touch(reseller)
    return success_object(reseller)

"""AddOnServices, Assets, DeploymentPackages routes."""

from flask import Blueprint, request

from db import db
from errors import (
    err_invalid_request,
    err_not_found,
    err_reference_not_found,
    err_invalid_state,
    err_org_frozen,
    err_audit_freeze,
    err_segregation,
    err_offline_activation,
    err_deployment_mode,
    err_cross_org,
    err_subscription_not_active,
    err_user_not_active,
    err_identity_mismatch,
)
from helpers import (
    make_record,
    touch,
    require_fields,
    require_enum,
    require_int,
    refresh_org,
    refresh_user_storage,
)
from middleware import get_identity, require_role, resolve_identity, require_org_scope
from response import success_object, success_list, paginate

bp = Blueprint("addons_assets", __name__)


# ---------------- add-on services ----------------

@bp.post("/licensing/add-on-services")
def create_addon():
    identity = get_identity()
    require_role(identity, ["OrgAdmin"])
    resolve_identity(identity)
    payload = request.get_json(silent=True)
    require_fields(payload, ["subscription_id", "kind", "quota_total"])
    sub = db["subscriptions"].get(payload["subscription_id"])
    if sub is None:
        raise err_reference_not_found("subscription_id does not exist")
    require_org_scope(identity, sub["org_id"])
    require_enum(payload, "kind", {"STOCK_CREDITS", "FONTS", "CLOUD_SERVICES"})
    quota = require_int(payload, "quota_total", minimum=1)
    overage = payload.get("overage_unit_price_cents", 0)
    if isinstance(overage, bool) or not isinstance(overage, int) or overage < 0:
        raise err_invalid_request("overage_unit_price_cents must be a non-negative integer")
    rec = make_record({
        "subscription_id": sub["id"],
        "kind": payload["kind"],
        "quota_total": quota,
        "quota_used": 0,
        "status": "ACTIVE",
        "overage_unit_price_cents": overage,
    })
    db["add_on_services"][rec["id"]] = rec
    if rec["kind"] == "CLOUD_SERVICES":
        refresh_org(sub["org_id"])
    return success_object(rec, 201)


@bp.get("/licensing/add-on-services")
def list_addons():
    identity = get_identity()
    require_role(identity, ["SystemAdmin", "OrgAdmin"])
    resolve_identity(identity)
    items = list(db["add_on_services"].values())
    if identity.role == "OrgAdmin" and identity.admin:
        org_id = identity.admin["org_id"]
        sub_org = {s["id"]: s["org_id"] for s in db["subscriptions"].values()}
        items = [a for a in items if sub_org.get(a["subscription_id"]) == org_id]
    for key in ("subscription_id", "kind", "status"):
        v = request.args.get(key)
        if v is not None:
            items = [a for a in items if str(a.get(key)) == v]
    items.sort(key=lambda a: a["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/licensing/add-on-services/<aid>")
def get_addon(aid):
    identity = get_identity()
    require_role(identity, ["SystemAdmin", "OrgAdmin"])
    resolve_identity(identity)
    addon = db["add_on_services"].get(aid)
    if addon is None:
        raise err_not_found("AddOnService not found")
    sub = db["subscriptions"].get(addon["subscription_id"])
    require_org_scope(identity, sub["org_id"] if sub else None)
    return success_object(addon)


@bp.post("/licensing/add-on-services/<aid>/consume")
def consume_addon(aid):
    identity = get_identity()
    require_role(identity, ["EndUser", "OrgAdmin"])
    resolve_identity(identity)
    addon = db["add_on_services"].get(aid)
    if addon is None:
        raise err_not_found("AddOnService not found")
    sub = db["subscriptions"].get(addon["subscription_id"])
    if identity.role == "OrgAdmin":
        require_org_scope(identity, sub["org_id"] if sub else None)
    else:
        # EndUser must belong to the org of the subscription
        if identity.end_user and sub and identity.end_user["org_id"] != sub["org_id"]:
            raise err_identity_mismatch("EndUser not in subscription's organization")
    payload = request.get_json(silent=True)
    require_fields(payload, ["units"])
    units = require_int(payload, "units", minimum=1)
    if addon["status"] == "CANCELLED":
        raise err_invalid_state("AddOnService is CANCELLED")
    if addon["status"] == "ACTIVE":
        addon["quota_used"] = min(addon["quota_used"] + units, addon["quota_total"])
        if addon["quota_used"] >= addon["quota_total"]:
            addon["status"] = "EXHAUSTED"
        touch(addon)
    else:  # EXHAUSTED: further consumption billed as overage; quota_used stays at quota_total
        touch(addon)
    return success_object(addon)


@bp.post("/licensing/add-on-services/<aid>/top-up")
def topup_addon(aid):
    identity = get_identity()
    require_role(identity, ["OrgAdmin"])
    resolve_identity(identity)
    addon = db["add_on_services"].get(aid)
    if addon is None:
        raise err_not_found("AddOnService not found")
    sub = db["subscriptions"].get(addon["subscription_id"])
    require_org_scope(identity, sub["org_id"] if sub else None)
    payload = request.get_json(silent=True)
    require_fields(payload, ["units"])
    units = require_int(payload, "units", minimum=1)
    if addon["status"] != "EXHAUSTED":
        raise err_invalid_state("AddOnService is not EXHAUSTED")
    if sub is None or sub["status"] != "ACTIVE":
        raise err_subscription_not_active()
    addon["quota_total"] += units
    if addon["quota_used"] < addon["quota_total"]:
        addon["status"] = "ACTIVE"
    touch(addon)
    if addon["kind"] == "CLOUD_SERVICES":
        refresh_org(sub["org_id"])
    return success_object(addon)


@bp.post("/licensing/add-on-services/<aid>/cancel")
def cancel_addon(aid):
    identity = get_identity()
    require_role(identity, ["OrgAdmin"])
    resolve_identity(identity)
    addon = db["add_on_services"].get(aid)
    if addon is None:
        raise err_not_found("AddOnService not found")
    sub = db["subscriptions"].get(addon["subscription_id"])
    require_org_scope(identity, sub["org_id"] if sub else None)
    if addon["status"] not in ("ACTIVE", "EXHAUSTED"):
        raise err_invalid_state("AddOnService is not cancellable")
    addon["status"] = "CANCELLED"
    touch(addon)
    if addon["kind"] == "CLOUD_SERVICES" and sub:
        refresh_org(sub["org_id"])
    return success_object(addon)


# ---------------- assets ----------------

@bp.post("/licensing/assets")
def create_asset():
    identity = get_identity()
    require_role(identity, ["EndUser", "OrgAdmin"])
    resolve_identity(identity)
    payload = request.get_json(silent=True)
    require_fields(payload, ["owner_user_id", "title", "size_mb"])
    owner = db["end_users"].get(payload["owner_user_id"])
    if owner is None:
        raise err_reference_not_found("owner_user_id does not exist")
    if identity.role == "EndUser" and identity.user_id != owner["id"]:
        raise err_identity_mismatch("EndUser may only create own assets")
    if identity.role == "OrgAdmin":
        require_org_scope(identity, owner["org_id"])
    size = require_int(payload, "size_mb", minimum=0)
    rec = make_record({
        "owner_user_id": owner["id"],
        "org_id": owner["org_id"],
        "title": payload["title"],
        "size_mb": size,
        "status": "ACTIVE",
    })
    db["assets"][rec["id"]] = rec
    refresh_user_storage(owner["id"])
    return success_object(rec, 201)


@bp.get("/licensing/assets")
def list_assets():
    identity = get_identity()
    require_role(identity, ["SystemAdmin", "OrgAdmin", "EndUser"])
    resolve_identity(identity)
    items = list(db["assets"].values())
    if identity.role == "EndUser":
        items = [a for a in items if a["owner_user_id"] == identity.user_id]
    elif identity.role == "OrgAdmin" and identity.admin:
        items = [a for a in items if a["org_id"] == identity.admin["org_id"]]
    for key in ("owner_user_id", "org_id", "status"):
        v = request.args.get(key)
        if v is not None:
            items = [a for a in items if str(a.get(key)) == v]
    items.sort(key=lambda a: a["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/licensing/assets/<aid>")
def get_asset(aid):
    identity = get_identity()
    require_role(identity, ["SystemAdmin", "OrgAdmin", "EndUser"])
    resolve_identity(identity)
    asset = db["assets"].get(aid)
    if asset is None:
        raise err_not_found("Asset not found")
    if identity.role == "EndUser" and asset["owner_user_id"] != identity.user_id:
        raise err_identity_mismatch("Asset does not belong to caller")
    if identity.role == "OrgAdmin":
        require_org_scope(identity, asset["org_id"])
    return success_object(asset)


@bp.post("/licensing/assets/<aid>/transfer")
def transfer_asset(aid):
    identity = get_identity()
    require_role(identity, ["OrgAdmin"])
    resolve_identity(identity)
    asset = db["assets"].get(aid)
    if asset is None:
        raise err_not_found("Asset not found")
    require_org_scope(identity, asset["org_id"])
    payload = request.get_json(silent=True)
    require_fields(payload, ["to_user_id"])
    to_user = db["end_users"].get(payload["to_user_id"])
    if to_user is None:
        raise err_reference_not_found("to_user_id does not exist")
    if asset["status"] != "ACTIVE":
        raise err_invalid_state("Asset is not ACTIVE")
    owner = db["end_users"].get(asset["owner_user_id"])
    if owner is None or owner["status"] not in ("DEPARTED", "ACTIVE"):
        raise err_invalid_state("Owner must be DEPARTED or ACTIVE for transfer")
    if to_user["org_id"] != asset["org_id"]:
        raise err_cross_org()
    asset["status"] = "IN_TRANSFER"
    asset["_transfer_to_user_id"] = to_user["id"]
    touch(asset)
    out = {k: v for k, v in asset.items() if not k.startswith("_")}
    return success_object(out)


@bp.post("/licensing/assets/<aid>/transfer/accept")
def accept_asset_transfer(aid):
    identity = get_identity()
    require_role(identity, ["EndUser"])
    resolve_identity(identity)
    asset = db["assets"].get(aid)
    if asset is None:
        raise err_not_found("Asset not found")
    if asset["status"] != "IN_TRANSFER":
        raise err_invalid_state("Asset is not IN_TRANSFER")
    target = asset.get("_transfer_to_user_id")
    if identity.user_id != target:
        raise err_identity_mismatch("Caller is not the transfer recipient")
    if identity.end_user["status"] != "ACTIVE":
        raise err_user_not_active()
    old_owner = asset["owner_user_id"]
    asset["owner_user_id"] = identity.user_id
    asset["status"] = "ACTIVE"
    asset.pop("_transfer_to_user_id", None)
    touch(asset)
    refresh_user_storage(old_owner)
    refresh_user_storage(identity.user_id)
    return success_object(asset)


@bp.post("/licensing/assets/<aid>/transfer/cancel")
def cancel_asset_transfer(aid):
    identity = get_identity()
    require_role(identity, ["OrgAdmin"])
    resolve_identity(identity)
    asset = db["assets"].get(aid)
    if asset is None:
        raise err_not_found("Asset not found")
    require_org_scope(identity, asset["org_id"])
    if asset["status"] != "IN_TRANSFER":
        raise err_invalid_state("Asset is not IN_TRANSFER")
    asset["status"] = "ACTIVE"
    asset.pop("_transfer_to_user_id", None)
    touch(asset)
    return success_object(asset)


@bp.post("/licensing/assets/<aid>/claim")
def claim_asset(aid):
    identity = get_identity()
    require_role(identity, ["OrgAdmin"])
    resolve_identity(identity)
    asset = db["assets"].get(aid)
    if asset is None:
        raise err_not_found("Asset not found")
    require_org_scope(identity, asset["org_id"])
    payload = request.get_json(silent=True)
    require_fields(payload, ["to_user_id"])
    to_user = db["end_users"].get(payload["to_user_id"])
    if to_user is None:
        raise err_reference_not_found("to_user_id does not exist")
    if asset["status"] != "ORPHANED":
        raise err_invalid_state("Asset is not ORPHANED")
    if to_user["org_id"] != asset["org_id"]:
        raise err_cross_org()
    if to_user["status"] != "ACTIVE":
        raise err_user_not_active()
    asset["owner_user_id"] = to_user["id"]
    asset["status"] = "ACTIVE"
    touch(asset)
    refresh_user_storage(to_user["id"])
    return success_object(asset)


@bp.post("/licensing/assets/<aid>/purge")
def purge_asset(aid):
    identity = get_identity()
    require_role(identity, ["OrgAdmin"])
    resolve_identity(identity)
    asset = db["assets"].get(aid)
    if asset is None:
        raise err_not_found("Asset not found")
    require_org_scope(identity, asset["org_id"])
    if asset["status"] != "ORPHANED":
        raise err_invalid_state("Asset is not ORPHANED")
    org = db["organizations"].get(asset["org_id"])
    if org and org["compliance_posture"] in ("UNDER_AUDIT", "FROZEN"):
        raise err_audit_freeze()
    asset["status"] = "PURGED"
    touch(asset)
    return success_object(asset)


# ---------------- deployment packages ----------------

@bp.post("/licensing/deployment-packages")
def create_package():
    identity = get_identity()
    require_role(identity, ["DeploymentAdmin"])
    resolve_identity(identity)
    payload = request.get_json(silent=True)
    require_fields(payload, ["org_id", "created_by_admin_id", "name", "plan_id", "deployment_mode"])
    org = db["organizations"].get(payload["org_id"])
    if org is None:
        raise err_reference_not_found("org_id does not exist")
    require_org_scope(identity, org["id"])
    plan = db["plans"].get(payload["plan_id"])
    if plan is None:
        raise err_reference_not_found("plan_id does not exist")
    if payload["created_by_admin_id"] not in db["admins"]:
        raise err_reference_not_found("created_by_admin_id does not exist")
    require_enum(payload, "deployment_mode", {"NAMED_USER", "SERIALIZED", "SHARED_DEVICE"})
    offline = payload.get("offline_activation", False)
    if not isinstance(offline, bool):
        raise err_invalid_request("offline_activation must be a boolean")
    if payload["deployment_mode"] not in plan["deployment_modes"]:
        raise err_deployment_mode()
    if offline and (not plan["allows_offline_activation"] or payload["deployment_mode"] != "SERIALIZED"):
        raise err_offline_activation()
    rec = make_record({
        "org_id": org["id"],
        "created_by_admin_id": payload["created_by_admin_id"],
        "name": payload["name"],
        "plan_id": plan["id"],
        "deployment_mode": payload["deployment_mode"],
        "offline_activation": offline,
        "status": "DRAFT",
    })
    db["deployment_packages"][rec["id"]] = rec
    return success_object(rec, 201)


@bp.get("/licensing/deployment-packages")
def list_packages():
    identity = get_identity()
    require_role(identity, ["SystemAdmin", "OrgAdmin", "DeploymentAdmin"])
    resolve_identity(identity)
    items = list(db["deployment_packages"].values())
    if identity.role in ("OrgAdmin", "DeploymentAdmin") and identity.admin:
        items = [p for p in items if p["org_id"] == identity.admin["org_id"]]
    for key in ("org_id", "plan_id", "status", "created_by_admin_id"):
        v = request.args.get(key)
        if v is not None:
            items = [p for p in items if str(p.get(key)) == v]
    items.sort(key=lambda p: p["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/licensing/deployment-packages/<pid>")
def get_package(pid):
    identity = get_identity()
    require_role(identity, ["SystemAdmin", "OrgAdmin", "DeploymentAdmin"])
    resolve_identity(identity)
    pkg = db["deployment_packages"].get(pid)
    if pkg is None:
        raise err_not_found("DeploymentPackage not found")
    require_org_scope(identity, pkg["org_id"])
    return success_object(pkg)


@bp.post("/licensing/deployment-packages/<pid>/submit")
def submit_package(pid):
    identity = get_identity()
    require_role(identity, ["DeploymentAdmin"])
    resolve_identity(identity)
    pkg = db["deployment_packages"].get(pid)
    if pkg is None:
        raise err_not_found("DeploymentPackage not found")
    require_org_scope(identity, pkg["org_id"])
    if pkg["status"] != "DRAFT":
        raise err_invalid_state("Package is not DRAFT")
    org = db["organizations"].get(pkg["org_id"])
    if org and org["compliance_posture"] == "FROZEN":
        raise err_org_frozen()
    plan = db["plans"].get(pkg["plan_id"])
    if plan is None or pkg["deployment_mode"] not in plan["deployment_modes"]:
        raise err_deployment_mode()
    if pkg["offline_activation"] and (not plan["allows_offline_activation"] or pkg["deployment_mode"] != "SERIALIZED"):
        raise err_offline_activation()
    pkg["status"] = "PENDING_APPROVAL"
    touch(pkg)
    return success_object(pkg)


@bp.post("/licensing/deployment-packages/<pid>/approve")
def approve_package(pid):
    identity = get_identity()
    require_role(identity, ["OrgAdmin"])
    resolve_identity(identity)
    pkg = db["deployment_packages"].get(pid)
    if pkg is None:
        raise err_not_found("DeploymentPackage not found")
    require_org_scope(identity, pkg["org_id"])
    if pkg["status"] != "PENDING_APPROVAL":
        raise err_invalid_state("Package is not PENDING_APPROVAL")
    if identity.admin["id"] == pkg["created_by_admin_id"]:
        raise err_segregation()
    pkg["status"] = "APPROVED"
    touch(pkg)
    return success_object(pkg)


@bp.post("/licensing/deployment-packages/<pid>/reject")
def reject_package(pid):
    identity = get_identity()
    require_role(identity, ["OrgAdmin"])
    resolve_identity(identity)
    pkg = db["deployment_packages"].get(pid)
    if pkg is None:
        raise err_not_found("DeploymentPackage not found")
    require_org_scope(identity, pkg["org_id"])
    if pkg["status"] != "PENDING_APPROVAL":
        raise err_invalid_state("Package is not PENDING_APPROVAL")
    if identity.admin["id"] == pkg["created_by_admin_id"]:
        raise err_segregation()
    pkg["status"] = "REJECTED"
    touch(pkg)
    return success_object(pkg)


@bp.post("/licensing/deployment-packages/<pid>/publish")
def publish_package(pid):
    identity = get_identity()
    require_role(identity, ["DeploymentAdmin"])
    resolve_identity(identity)
    pkg = db["deployment_packages"].get(pid)
    if pkg is None:
        raise err_not_found("DeploymentPackage not found")
    require_org_scope(identity, pkg["org_id"])
    if pkg["status"] != "APPROVED":
        raise err_invalid_state("Package is not APPROVED")
    plan = db["plans"].get(pkg["plan_id"])
    if plan is None or pkg["deployment_mode"] not in plan["deployment_modes"]:
        raise err_deployment_mode()
    pkg["status"] = "PUBLISHED"
    touch(pkg)
    return success_object(pkg)


@bp.post("/licensing/deployment-packages/<pid>/retire")
def retire_package(pid):
    identity = get_identity()
    require_role(identity, ["DeploymentAdmin"])
    resolve_identity(identity)
    pkg = db["deployment_packages"].get(pid)
    if pkg is None:
        raise err_not_found("DeploymentPackage not found")
    require_org_scope(identity, pkg["org_id"])
    if pkg["status"] != "PUBLISHED":
        raise err_invalid_state("Package is not PUBLISHED")
    pkg["status"] = "RETIRED"
    touch(pkg)
    return success_object(pkg)

"""Organizations, Admins, EndUsers, Devices routes."""

from flask import Blueprint, request

from db import db
from errors import (
    err_invalid_request,
    err_not_found,
    err_reference_not_found,
    err_invalid_state,
    err_user_not_active,
)
from helpers import (
    make_record,
    touch,
    require_fields,
    require_enum,
    refresh_org,
    refresh_user_storage,
    revoke_entitlement,
    suspend_entitlement,
    resume_entitlement,
    entitlements_of_seat,
    finalize_reclaim,
)
from middleware import get_identity, require_role, resolve_identity, require_org_scope
from response import (
    success_object,
    success_list,
    paginate,
    now_dt,
    now_iso,
    add_hours,
    iso_no_frac,
    parse_iso,
)

bp = Blueprint("orgs_users", __name__)


@bp.post("/licensing/organizations")
def create_organization():
    identity = get_identity()
    require_role(identity, ["SystemAdmin"])
    resolve_identity(identity)
    payload = request.get_json(silent=True)
    require_fields(payload, ["name", "org_type", "primary_admin_id"])
    require_enum(payload, "org_type", {"INDIVIDUAL", "TEAM", "ENTERPRISE"})
    rec = make_record({
        "name": payload["name"],
        "org_type": payload["org_type"],
        "primary_admin_id": payload["primary_admin_id"],
        "status": "ACTIVE",
        "storage_pool_gb": 0,
        "compliance_posture": "COMPLIANT",
    })
    db["organizations"][rec["id"]] = rec
    return success_object(rec, 201)


@bp.get("/licensing/organizations")
def list_organizations():
    identity = get_identity()
    require_role(identity, ["SystemAdmin"])
    resolve_identity(identity)
    items = list(db["organizations"].values())
    pa = request.args.get("primary_admin_id")
    if pa is not None:
        items = [o for o in items if o["primary_admin_id"] == pa]
    st = request.args.get("status")
    if st is not None:
        items = [o for o in items if o["status"] == st]
    items.sort(key=lambda o: o["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/licensing/organizations/<oid>")
def get_organization(oid):
    identity = get_identity()
    require_role(identity, ["SystemAdmin", "OrgAdmin"])
    resolve_identity(identity)
    org = db["organizations"].get(oid)
    if org is None:
        raise err_not_found("Organization not found")
    require_org_scope(identity, org["id"])
    refresh_org(org["id"])
    return success_object(org)


# ---------------- admins ----------------

@bp.post("/licensing/admins")
def create_admin():
    identity = get_identity()
    require_role(identity, ["SystemAdmin"])
    resolve_identity(identity)
    payload = request.get_json(silent=True)
    require_fields(payload, ["email", "full_name", "admin_kind", "org_id"])
    require_enum(payload, "admin_kind", {"SYSTEM_ADMIN", "PRODUCT_ADMIN", "DEPLOYMENT_ADMIN"})
    if payload["org_id"] not in db["organizations"]:
        raise err_reference_not_found("org_id does not exist")
    rec = make_record({
        "email": payload["email"],
        "full_name": payload["full_name"],
        "admin_kind": payload["admin_kind"],
        "org_id": payload["org_id"],
    })
    db["admins"][rec["id"]] = rec
    return success_object(rec, 201)


@bp.get("/licensing/admins")
def list_admins():
    identity = get_identity()
    require_role(identity, ["SystemAdmin"])
    resolve_identity(identity)
    items = list(db["admins"].values())
    oid = request.args.get("org_id")
    if oid is not None:
        items = [a for a in items if a["org_id"] == oid]
    items.sort(key=lambda a: a["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/licensing/admins/<aid>")
def get_admin(aid):
    identity = get_identity()
    require_role(identity, ["SystemAdmin", "OrgAdmin", "DeploymentAdmin"])
    resolve_identity(identity)
    admin = db["admins"].get(aid)
    if admin is None:
        raise err_not_found("Admin not found")
    require_org_scope(identity, admin["org_id"])
    return success_object(admin)


# ---------------- end users ----------------

@bp.post("/licensing/end-users")
def create_end_user():
    identity = get_identity()
    require_role(identity, ["SystemAdmin", "OrgAdmin"])
    resolve_identity(identity)
    payload = request.get_json(silent=True)
    require_fields(payload, ["email", "full_name", "org_id"])
    if payload["org_id"] not in db["organizations"]:
        raise err_reference_not_found("org_id does not exist")
    require_org_scope(identity, payload["org_id"])
    rec = make_record({
        "email": payload["email"],
        "full_name": payload["full_name"],
        "org_id": payload["org_id"],
        "status": "ACTIVE",
        "storage_used_gb": 0,
    })
    db["end_users"][rec["id"]] = rec
    return success_object(rec, 201)


@bp.get("/licensing/end-users")
def list_end_users():
    identity = get_identity()
    require_role(identity, ["SystemAdmin", "OrgAdmin"])
    resolve_identity(identity)
    items = list(db["end_users"].values())
    oid = request.args.get("org_id")
    if oid is not None:
        if identity.role == "OrgAdmin" and identity.admin and identity.admin["org_id"] != oid:
            items = []
        else:
            items = [u for u in items if u["org_id"] == oid]
    elif identity.role == "OrgAdmin" and identity.admin:
        items = [u for u in items if u["org_id"] == identity.admin["org_id"]]
    st = request.args.get("status")
    if st is not None:
        items = [u for u in items if u["status"] == st]
    items.sort(key=lambda u: u["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/licensing/end-users/<uid>")
def get_end_user(uid):
    identity = get_identity()
    require_role(identity, ["SystemAdmin", "OrgAdmin", "EndUser"])
    resolve_identity(identity)
    user = db["end_users"].get(uid)
    if user is None:
        raise err_not_found("EndUser not found")
    if identity.role == "OrgAdmin":
        require_org_scope(identity, user["org_id"])
    elif identity.role == "EndUser":
        if identity.user_id != uid:
            from errors import err_identity_mismatch
            raise err_identity_mismatch("EndUser may only read own record")
    return success_object(user)


@bp.post("/licensing/end-users/<uid>/deactivate")
def deactivate_end_user(uid):
    identity = get_identity()
    require_role(identity, ["OrgAdmin"])
    resolve_identity(identity)
    user = db["end_users"].get(uid)
    if user is None:
        raise err_not_found("EndUser not found")
    require_org_scope(identity, user["org_id"])
    org = db["organizations"].get(user["org_id"])
    if org is None or org["status"] != "ACTIVE":
        raise err_invalid_state("Organization is not ACTIVE")
    if user["status"] != "ACTIVE":
        raise err_invalid_state("EndUser is not ACTIVE")
    user["status"] = "DEACTIVATED"
    touch(user)
    grace_end = iso_no_frac(add_hours(now_dt(), 24))
    for seat in db["seats"].values():
        if seat["end_user_id"] == uid and seat["status"] == "ASSIGNED":
            seat["status"] = "PENDING_RECLAIM"
            seat["pending_reclaim_not_before"] = grace_end
            seat["_deactivation_initiated"] = uid
            touch(seat)
            for ent in entitlements_of_seat(seat["id"]):
                suspend_entitlement(ent)
    return success_object(user)


@bp.post("/licensing/end-users/<uid>/reactivate")
def reactivate_end_user(uid):
    identity = get_identity()
    require_role(identity, ["OrgAdmin"])
    resolve_identity(identity)
    user = db["end_users"].get(uid)
    if user is None:
        raise err_not_found("EndUser not found")
    require_org_scope(identity, user["org_id"])
    org = db["organizations"].get(user["org_id"])
    if org is None or org["status"] != "ACTIVE":
        raise err_invalid_state("Organization is not ACTIVE")
    if user["status"] != "DEACTIVATED":
        raise err_invalid_state("EndUser is not DEACTIVATED")
    user["status"] = "ACTIVE"
    touch(user)
    now = now_dt()
    for seat in db["seats"].values():
        if seat["status"] == "PENDING_RECLAIM" and seat.get("_deactivation_initiated") == uid:
            if seat.get("pending_reclaim_not_before") and now < parse_iso(seat["pending_reclaim_not_before"]):
                seat["status"] = "ASSIGNED"
                seat["pending_reclaim_not_before"] = None
                seat.pop("_deactivation_initiated", None)
                touch(seat)
                for ent in entitlements_of_seat(seat["id"]):
                    resume_entitlement(ent)
    return success_object(user)


@bp.post("/licensing/end-users/<uid>/mark-departed")
def mark_departed(uid):
    identity = get_identity()
    require_role(identity, ["OrgAdmin"])
    resolve_identity(identity)
    user = db["end_users"].get(uid)
    if user is None:
        raise err_not_found("EndUser not found")
    require_org_scope(identity, user["org_id"])
    if user["status"] != "DEACTIVATED":
        raise err_invalid_state("EndUser is not DEACTIVATED")
    user["status"] = "DEPARTED"
    touch(user)
    for seat in list(db["seats"].values()):
        if seat["end_user_id"] == uid and seat["status"] == "PENDING_RECLAIM":
            finalize_reclaim(seat)
    for asset in list(db["assets"].values()):
        if asset["owner_user_id"] == uid and asset["status"] == "ACTIVE":
            asset["status"] = "ORPHANED"
            touch(asset)
    refresh_user_storage(uid)
    refresh_org(user["org_id"])
    return success_object(user)


# ---------------- devices ----------------

@bp.post("/licensing/devices")
def create_device():
    identity = get_identity()
    require_role(identity, ["EndUser", "OrgAdmin"])
    resolve_identity(identity)
    payload = request.get_json(silent=True)
    require_fields(payload, ["end_user_id", "device_fingerprint", "label"])
    owner = db["end_users"].get(payload["end_user_id"])
    if owner is None:
        raise err_reference_not_found("end_user_id does not exist")
    if identity.role == "EndUser" and identity.user_id != payload["end_user_id"]:
        from errors import err_identity_mismatch
        raise err_identity_mismatch("EndUser may only register own devices")
    if identity.role == "OrgAdmin":
        require_org_scope(identity, owner["org_id"])
    rec = make_record({
        "end_user_id": payload["end_user_id"],
        "device_fingerprint": payload["device_fingerprint"],
        "label": payload["label"],
        "status": "ACTIVE",
    })
    db["devices"][rec["id"]] = rec
    return success_object(rec, 201)


@bp.get("/licensing/devices")
def list_devices():
    identity = get_identity()
    require_role(identity, ["SystemAdmin", "OrgAdmin", "EndUser"])
    resolve_identity(identity)
    items = list(db["devices"].values())
    if identity.role == "EndUser":
        items = [d for d in items if d["end_user_id"] == identity.user_id]
    elif identity.role == "OrgAdmin" and identity.admin:
        my_org = identity.admin["org_id"]
        items = [
            d for d in items
            if db["end_users"].get(d["end_user_id"], {}).get("org_id") == my_org
        ]
    eid = request.args.get("end_user_id")
    if eid is not None:
        items = [d for d in items if d["end_user_id"] == eid]
    items.sort(key=lambda d: d["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/licensing/devices/<did>")
def get_device(did):
    identity = get_identity()
    require_role(identity, ["SystemAdmin", "OrgAdmin", "EndUser"])
    resolve_identity(identity)
    device = db["devices"].get(did)
    if device is None:
        raise err_not_found("Device not found")
    if identity.role == "EndUser" and device["end_user_id"] != identity.user_id:
        from errors import err_identity_mismatch
        raise err_identity_mismatch("EndUser may only read own devices")
    if identity.role == "OrgAdmin":
        owner = db["end_users"].get(device["end_user_id"])
        require_org_scope(identity, owner["org_id"] if owner else None)
    return success_object(device)

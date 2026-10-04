"""App integrations and sync conflicts."""
from flask import Blueprint
import db
from auth import require_role, require_company_scope, active_grant
from errors import (ok, ok_list, invalid_state, not_writable,
                    integration_resume_blocked, conflict_not_open,
                    not_found, forbidden_role, invalid_request)
from helpers import (body_json, req_str, get_or_404, paginate, sort_by_created,
                     enum_check, filter_items, company_subscription)
import serializers

bp = Blueprint("integrations", __name__, url_prefix="/api/companies/<company_id>")

SYNC_DIRECTIONS = ("PULL", "PUSH", "BIDIRECTIONAL")
ACTIVATE_LIFECYCLES = ("TRIAL", "ACTIVE", "REACTIVATED", "PAST_DUE")


def _gate_admin(identity):
    if identity is None or identity.get("permission_level") not in ("PRIMARY_ADMIN", "COMPANY_ADMIN"):
        forbidden_role()


@bp.post("/integrations")
def create_integration(company_id):
    role, identity = require_role(["CompanyUser"])
    get_or_404("ClientCompany", company_id)
    require_company_scope(identity, company_id)
    sub = company_subscription(company_id)
    if sub is not None and sub["lifecycle_status"] in ("CANCELLED_READ_ONLY", "CANCELLED_EXPIRED"):
        not_writable()
    data = body_json()
    body_company = data.get("company_id")
    if body_company is not None and body_company != company_id:
        not_found("company_id in body does not match path")
    direction = enum_check(req_str(data, "sync_direction"), SYNC_DIRECTIONS, "sync_direction")
    rec = {
        "company_id": company_id,
        "app_code": req_str(data, "app_code"),
        "sync_direction": direction,
        "integration_status": "LINKED",
        "conflict_count": 0,
        "last_sync_at": None,
    }
    db.stamp_common(rec)
    db.TABLES["AppIntegration"][rec["id"]] = rec
    return ok(serializers.serialize_integration(rec), status=201)


@bp.get("/integrations")
def list_integrations(company_id):
    role, identity = require_role(["PlatformAdmin", "CompanyUser", "AccountantUser"])
    get_or_404("ClientCompany", company_id)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
    items = [i for i in db.TABLES["AppIntegration"].values() if i["company_id"] == company_id]
    items = filter_items(items, [("integration_status", "integration_status")])
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list([serializers.serialize_integration(i) for i in page], limit, offset, total)


def _get_integration(company_id, iid):
    get_or_404("ClientCompany", company_id)
    rec = get_or_404("AppIntegration", iid)
    if rec["company_id"] != company_id:
        not_found("Integration not in company")
    return rec


@bp.get("/integrations/<iid>")
def get_integration(company_id, iid):
    role, identity = require_role(["PlatformAdmin", "CompanyUser", "AccountantUser"])
    rec = _get_integration(company_id, iid)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
    return ok(serializers.serialize_integration(rec))


@bp.post("/integrations/<iid>/activate")
def activate_integration(company_id, iid):
    role, identity = require_role(["CompanyUser"])
    rec = _get_integration(company_id, iid)
    require_company_scope(identity, company_id)
    _gate_admin(identity)
    sub = company_subscription(company_id)
    if sub is None or sub["lifecycle_status"] not in ACTIVATE_LIFECYCLES:
        invalid_state("Subscription not in an activatable state")
    if rec["integration_status"] != "LINKED":
        invalid_state("Integration not LINKED")
    rec["integration_status"] = "ACTIVE"
    db.touch(rec)
    return ok(serializers.serialize_integration(rec))


@bp.post("/integrations/<iid>/resume")
def resume_integration(company_id, iid):
    role, identity = require_role(["CompanyUser"])
    rec = _get_integration(company_id, iid)
    require_company_scope(identity, company_id)
    _gate_admin(identity)
    if rec["integration_status"] != "CONFLICT_PAUSED":
        invalid_state("Integration not CONFLICT_PAUSED")
    if rec["conflict_count"] != 0:
        integration_resume_blocked()
    rec["integration_status"] = "ACTIVE"
    db.touch(rec)
    return ok(serializers.serialize_integration(rec))


@bp.post("/integrations/<iid>/disconnect")
def disconnect_integration(company_id, iid):
    role, identity = require_role(["CompanyUser"])
    rec = _get_integration(company_id, iid)
    require_company_scope(identity, company_id)
    _gate_admin(identity)
    if rec["integration_status"] not in ("LINKED", "ACTIVE", "CONFLICT_PAUSED"):
        invalid_state("Integration not disconnectable")
    rec["integration_status"] = "DISCONNECTED"
    db.touch(rec)
    return ok(serializers.serialize_integration(rec))


@bp.post("/integrations/<iid>/conflicts")
def create_conflict(company_id, iid):
    require_role(["PlatformAdmin"])
    integration = _get_integration(company_id, iid)
    data = body_json()
    rec = {
        "app_integration_id": integration["id"],
        "conflict_field": req_str(data, "conflict_field"),
        "local_value": req_str(data, "local_value"),
        "remote_value": req_str(data, "remote_value"),
        "conflict_status": "OPEN",
    }
    db.stamp_common(rec)
    db.TABLES["SyncConflict"][rec["id"]] = rec
    integration["conflict_count"] = integration.get("conflict_count", 0) + 1
    if integration["conflict_count"] >= 3 and integration["integration_status"] == "ACTIVE":
        integration["integration_status"] = "CONFLICT_PAUSED"
    db.touch(integration)
    return ok(serializers.serialize_sync_conflict(rec), status=201)


@bp.get("/integrations/<iid>/conflicts")
def list_conflicts(company_id, iid):
    role, identity = require_role(["PlatformAdmin", "CompanyUser", "AccountantUser"])
    _get_integration(company_id, iid)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
    items = [c for c in db.TABLES["SyncConflict"].values()
             if c["app_integration_id"] == iid]
    items = filter_items(items, [("conflict_status", "conflict_status")])
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list([serializers.serialize_sync_conflict(c) for c in page],
                   limit, offset, total)


@bp.post("/integrations/<iid>/conflicts/<cid>/resolve")
def resolve_conflict(company_id, iid, cid):
    role, identity = require_role(["CompanyUser", "AccountantUser"])
    integration = _get_integration(company_id, iid)
    conflict = get_or_404("SyncConflict", cid)
    if conflict["app_integration_id"] != iid:
        not_found("Conflict not in integration")
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
        if identity.get("permission_level") in ("REPORTS_ONLY", "TIME_TRACKING"):
            forbidden_role()
    else:
        active_grant(identity, company_id, ("FULL_BOOKKEEPING",))
    data = body_json()
    resolution = req_str(data, "resolution")
    if resolution not in ("LOCAL", "REMOTE", "IGNORE"):
        invalid_request("resolution must be LOCAL, REMOTE, or IGNORE")
    if conflict["conflict_status"] != "OPEN":
        conflict_not_open()
    if resolution == "LOCAL":
        conflict["conflict_status"] = "RESOLVED_LOCAL"
    elif resolution == "REMOTE":
        conflict["conflict_status"] = "RESOLVED_REMOTE"
        conflict["local_value"] = conflict["remote_value"]
    else:
        conflict["conflict_status"] = "IGNORED"
    db.touch(conflict)
    integration["conflict_count"] = max(0, integration.get("conflict_count", 0) - 1)
    db.touch(integration)
    return ok(serializers.serialize_sync_conflict(conflict))

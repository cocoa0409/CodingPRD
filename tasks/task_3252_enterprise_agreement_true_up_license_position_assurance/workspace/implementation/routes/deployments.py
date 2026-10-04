"""Deployment endpoints."""
import flask

import db
from helpers import (err, success, get_json_body, require_fields, require_int,
                     require_enum, parse_pagination, list_response, stamp_new, touch)
from middleware import (authenticate, require_role, check_ownership,
                        authorize_agreement_path, scope_filter_for)

bp = flask.Blueprint("deployments", __name__)
ALL = ("ProgramAdministrator", "LicensingSpecialist", "CustomerAdmin", "Auditor")
MODEL_FOR_SCOPE = {"USER": "PER_USER", "DEVICE": "PER_DEVICE", "SERVER": "PER_SERVER_CORE"}


def _deployment_org_id(d):
    ag = db.agreements.get(d["agreement_id"])
    return ag["organization_id"] if ag else None


@bp.post("/licensing/agreements/<ag_id>/deployments")
def create_deployment(ag_id):
    _, role, ag = authorize_agreement_path(("CustomerAdmin",), ag_id)
    if ag["status"] != "ACTIVE":
        err("ERR_AGREEMENT_NOT_ACTIVE", "Agreement must be ACTIVE.", 409)
    body = get_json_body()
    require_fields(body, ["product_id", "scope", "deployment_date", "hosting"])
    product = db.products.get(body["product_id"])
    if product is None:
        err("ERR_NOT_FOUND", "Product not found.", 404)
    scope = require_enum(body, "scope", ("USER", "DEVICE", "SERVER"))
    hosting = require_enum(body, "hosting",
                           ("ON_PREMISES", "AUTHORIZED_MOBILITY_PARTNER", "THIRD_PARTY_DATACENTER"))
    try:
        dep_date = db.parse_date(body["deployment_date"])
    except Exception:
        err("ERR_INVALID_REQUEST", "deployment_date must be an ISO date.", 400)
    if dep_date > db.today():
        err("ERR_INVALID_DATE_RANGE", "deployment_date must not be in the future.", 422)

    # scope consistency + scope-dependent fields
    if MODEL_FOR_SCOPE[scope] != product["license_model"]:
        err("ERR_SCOPE_MISMATCH", "Deployment scope is inconsistent with the product license_model.", 422)
    user_count = body.get("user_count", 0)
    device_count = body.get("device_count", 0)
    physical_cores = body.get("physical_cores_per_server", 0)
    core_factor = body.get("core_factor", None)
    vm_count = body.get("vm_count", 0)
    vcores_per_vm = body.get("vcores_per_vm", 0)
    licensing_mode = body.get("licensing_mode", None)

    if scope == "USER":
        if not isinstance(user_count, int) or isinstance(user_count, bool) or user_count < 1:
            err("ERR_SCOPE_MISMATCH", "user_count >= 1 is required for scope USER.", 422)
        device_count = 0
        physical_cores = 0
        vm_count = 0
        vcores_per_vm = 0
        core_factor = None
        licensing_mode = None
    elif scope == "DEVICE":
        if not isinstance(device_count, int) or isinstance(device_count, bool) or device_count < 1:
            err("ERR_SCOPE_MISMATCH", "device_count >= 1 is required for scope DEVICE.", 422)
        user_count = 0
        physical_cores = 0
        vm_count = 0
        vcores_per_vm = 0
        core_factor = None
        licensing_mode = None
    else:  # SERVER
        if not isinstance(physical_cores, int) or isinstance(physical_cores, bool) or physical_cores < 1:
            err("ERR_SCOPE_MISMATCH", "physical_cores_per_server >= 1 is required for scope SERVER.", 422)
        if not isinstance(core_factor, (int, float)) or isinstance(core_factor, bool) or core_factor <= 0:
            err("ERR_SCOPE_MISMATCH", "core_factor > 0 is required for scope SERVER.", 422)
        if not isinstance(vm_count, int) or isinstance(vm_count, bool) or vm_count < 0:
            err("ERR_SCOPE_MISMATCH", "vm_count >= 0 is required for scope SERVER.", 422)
        if vm_count >= 1 and (not isinstance(vcores_per_vm, int) or isinstance(vcores_per_vm, bool) or vcores_per_vm < 1):
            err("ERR_SCOPE_MISMATCH", "vcores_per_vm >= 1 is required when vm_count >= 1.", 422)
        if vm_count == 0:
            vcores_per_vm = 0
        if licensing_mode not in ("PER_HOST", "PER_VM"):
            err("ERR_SCOPE_MISMATCH", "licensing_mode PER_HOST or PER_VM is required for scope SERVER.", 422)
        user_count = 0
        device_count = 0
        if hosting == "THIRD_PARTY_DATACENTER":
            authorized = product["license_mobility"] and any(
                h["agreement_id"] == ag["id"] and h["product_id"] == product["id"]
                and h["status"] == "APPROVED"
                and db.parse_date(h["effective_on"]) <= dep_date
                for h in db.hosting_auths.values())
            if not authorized:
                err("ERR_HOSTING_NOT_AUTHORIZED",
                    "Third-party datacenter hosting requires license mobility and an APPROVED, effective authorization.",
                    422)
    dep = {
        "agreement_id": ag["id"],
        "product_id": product["id"],
        "scope": scope,
        "deployment_date": dep_date.isoformat(),
        "user_count": user_count,
        "device_count": device_count,
        "physical_cores_per_server": physical_cores,
        "core_factor": core_factor,
        "vm_count": vm_count,
        "vcores_per_vm": vcores_per_vm,
        "licensing_mode": licensing_mode,
        "hosting": hosting,
        "retired": False,
    }
    stamp_new(dep, with_version=True)
    db.deployments[dep["id"]] = dep
    return success(dep, status=201, response_type="object")


@bp.get("/licensing/deployments/<did>")
def get_deployment(did):
    user_id, role = authenticate()
    require_role(role, ALL)
    dep = db.deployments.get(did)
    if dep is None:
        err("ERR_NOT_FOUND", "Deployment not found.", 404)
    check_ownership(user_id, role, _deployment_org_id(dep))
    return success(dep, status=200, response_type="object")


@bp.get("/licensing/agreements/<ag_id>/deployments")
def list_agreement_deployments(ag_id):
    _, role, ag = authorize_agreement_path(ALL, ag_id)
    limit, offset = parse_pagination()
    args = flask.request.args
    include_retired = args.get("include_retired", "false").lower() == "true"
    items = [d for d in db.deployments.values() if d["agreement_id"] == ag["id"]]
    if not include_retired:
        items = [d for d in items if not d["retired"]]
    pid = args.get("product_id")
    if pid is not None:
        items = [d for d in items if d["product_id"] == pid]
    return list_response(items, limit, offset)


@bp.delete("/licensing/deployments/<did>")
def retire_deployment(did):
    user_id, role = authenticate()
    require_role(role, ("CustomerAdmin",))
    dep = db.deployments.get(did)
    if dep is None:
        err("ERR_NOT_FOUND", "Deployment not found.", 404)
    check_ownership(user_id, role, _deployment_org_id(dep))
    dep["retired"] = True
    touch(dep)
    return success(dep, status=200, response_type="object")


@bp.get("/licensing/deployments")
def flat_list_deployments():
    user_id, role = authenticate()
    require_role(role, ALL)
    limit, offset = parse_pagination()
    args = flask.request.args
    items = list(db.deployments.values())
    aid = args.get("agreement_id")
    if aid is not None:
        items = [d for d in items if d["agreement_id"] == aid]
    pid = args.get("product_id")
    if pid is not None:
        items = [d for d in items if d["product_id"] == pid]
    items = scope_filter_for(role, user_id, items, _deployment_org_id)
    return list_response(items, limit, offset)

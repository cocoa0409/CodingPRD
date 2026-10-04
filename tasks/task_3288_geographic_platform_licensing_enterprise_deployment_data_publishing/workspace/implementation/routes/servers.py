"""Deployment servers and version compatibility (§3.10)."""
from flask import Blueprint, request

import store
from auth import require_role
from envelope import paginate, success
from errors import err
from helpers import cascade_grant_suspended, get_body, require_fields

bp = Blueprint("servers", __name__)

SERVER_ROLES = "GIS_SERVER|PORTAL|DATA_STORE|NOTEBOOK_SERVER"
AUTH_MODES = "BUILTIN|SAML|OIDC|IWA"


@bp.post("/geo-orgs/deployment-servers")
def create_server():
    require_role("DeploymentAdmin")
    body = get_body()
    require_fields(body, [
        ("organization_id", "str", True),
        ("hostname", "str", True),
        ("role", "enum:" + SERVER_ROLES, True),
        ("installed_major_version", "int", True),
        ("auth_mode", "enum:" + AUTH_MODES, True),
        ("license_grant_id", "str", True),
        ("cores_allocated", "int", True),
    ])
    org = store.orgs.get(body["organization_id"])
    if org is None:
        raise err("ERR_ORG_NOT_FOUND")
    grant = store.license_grants.get(body["license_grant_id"])
    if grant is None:
        raise err("ERR_GRANT_NOT_FOUND")
    product = store.license_products.get(grant["license_product_id"])
    if (product is None or product["license_kind"] != "DEPLOYMENT_SERVER"
            or grant["organization_id"] != org["id"]):
        raise err("ERR_GRANT_KIND_MISMATCH")
    for s in store.deployment_servers.values():
        if s["organization_id"] == org["id"] and s["hostname"] == body["hostname"]:
            raise err("ERR_DUPLICATE_VALUE", "hostname must be unique within the org")
    rec = store.new_record()
    rec.update({
        "organization_id": org["id"],
        "hostname": body["hostname"],
        "role": body["role"],
        "installed_major_version": body["installed_major_version"],
        "target_major_version": None,
        "auth_mode": body["auth_mode"],
        "license_grant_id": grant["id"],
        "cores_allocated": body["cores_allocated"],
        "status": "REGISTERED",
    })
    store.deployment_servers[rec["id"]] = rec
    return success(dict(rec), status=201)


@bp.get("/geo-orgs/deployment-servers")
def list_servers():
    require_role("PlatformAdmin", "DeploymentAdmin", "LicenseAdmin")
    items = sorted(store.deployment_servers.values(), key=lambda r: r["created_at"])
    for param in ("organization_id", "license_grant_id", "status", "role"):
        v = request.args.get(param)
        if v is not None:
            items = [s for s in items if s[param] == v]
    page, pg = paginate(items, request.args)
    return success([dict(s) for s in page], pagination=pg)


@bp.get("/geo-orgs/deployment-servers/<server_id>")
def get_server(server_id):
    require_role("PlatformAdmin", "DeploymentAdmin", "LicenseAdmin")
    srv = store.deployment_servers.get(server_id)
    if srv is None:
        raise err("ERR_SERVER_NOT_FOUND")
    return success(dict(srv))


@bp.post("/geo-orgs/deployment-servers/<server_id>/transition")
def server_transition(server_id):
    require_role("DeploymentAdmin")
    body = get_body()
    require_fields(body, [
        ("target_status", "enum:AUTHORIZED|UPGRADING|DECOMMISSIONED", True),
        ("target_major_version", "int", False),
    ])
    target = body["target_status"]
    srv = store.deployment_servers.get(server_id)
    if srv is None:
        raise err("ERR_SERVER_NOT_FOUND")
    org = store.orgs.get(srv["organization_id"])
    grant = store.license_grants.get(srv["license_grant_id"])

    if target == "AUTHORIZED":
        if srv["status"] == "REGISTERED":
            if org is None or org["status"] != "ACTIVE":
                raise err("ERR_ORG_NOT_ACTIVE")
            if grant is None or grant["status"] != "ACTIVE":
                raise err("ERR_GRANT_NOT_ACTIVE")
            product = store.license_products.get(grant["license_product_id"])
            if product is None or product["license_kind"] != "DEPLOYMENT_SERVER":
                raise err("ERR_GRANT_KIND_MISMATCH")
            if grant["seats_in_use"] + srv["cores_allocated"] > grant["seats_allocated"]:
                raise err("ERR_INSUFFICIENT_CORES")
            if product["major_version"] != srv["installed_major_version"]:
                raise err("ERR_VERSION_INCOMPATIBLE")
            srv["status"] = "AUTHORIZED"
            store.touch(srv)
            grant["seats_in_use"] += srv["cores_allocated"]
            store.touch(grant)
        elif srv["status"] == "UPGRADING":
            # Complete an upgrade
            target_v = srv.get("target_major_version")
            rules = sorted(
                (r for r in store.compat_rules.values()
                 if r["consumer_role"] == srv["role"]
                 and r["consumer_major_version"] == target_v),
                key=lambda r: r["created_at"],
            )
            if not rules:
                raise err("ERR_NO_COMPAT_RULE")
            warnings = []
            for rule in rules:
                for peer in store.deployment_servers.values():
                    if (peer["id"] == srv["id"]
                            or peer["organization_id"] != srv["organization_id"]
                            or peer["role"] != rule["dependency_role"]
                            or peer["status"] not in ("AUTHORIZED", "UPGRADING")):
                        continue
                    if peer["installed_major_version"] not in rule["allowed_dependency_major_versions"]:
                        if rule["strict"]:
                            raise err("ERR_VERSION_INCOMPATIBLE",
                                      f"peer {peer['id']} violates strict compat rule")
                        warnings.append(
                            f"peer {peer['id']} version {peer['installed_major_version']} "
                            f"not in allowed {rule['allowed_dependency_major_versions']}")
            srv["installed_major_version"] = target_v
            srv["target_major_version"] = None
            srv["status"] = "AUTHORIZED"
            store.touch(srv)
            # License-grant cascade check runs LAST
            if grant is not None:
                product = store.license_products.get(grant["license_product_id"])
                if (product is not None
                        and srv["installed_major_version"] > product["major_version"]
                        and grant["status"] == "ACTIVE"):
                    cascade_grant_suspended(grant)
            extra = {"warnings": warnings} if warnings else None
            return success(dict(srv), extra_meta=extra)
        else:
            raise err("ERR_SERVER_NOT_REGISTERED"
                      if srv["status"] in ("DECOMMISSIONED",)
                      else "ERR_SERVER_NOT_AUTHORIZED")
    elif target == "UPGRADING":
        if srv["status"] != "AUTHORIZED":
            raise err("ERR_SERVER_NOT_AUTHORIZED")
        tv = body.get("target_major_version")
        if tv is None or tv <= srv["installed_major_version"]:
            raise err("ERR_INVALID_TARGET_VERSION")
        srv["target_major_version"] = tv
        srv["status"] = "UPGRADING"
        store.touch(srv)
    elif target == "DECOMMISSIONED":
        if srv["status"] != "AUTHORIZED":
            raise err("ERR_SERVER_NOT_AUTHORIZED")
        if srv["role"] == "PORTAL":
            for peer in store.deployment_servers.values():
                if (peer["id"] != srv["id"]
                        and peer["organization_id"] == srv["organization_id"]
                        and peer["status"] in ("AUTHORIZED", "UPGRADING")):
                    raise err("ERR_PORTAL_IN_USE")
        srv["status"] = "DECOMMISSIONED"
        store.touch(srv)
        if grant is not None:
            grant["seats_in_use"] = max(0, grant["seats_in_use"] - srv["cores_allocated"])
            store.touch(grant)
    return success(dict(srv))


@bp.post("/geo-orgs/version-compatibility-rules")
def create_rule():
    require_role("PlatformAdmin")
    body = get_body()
    require_fields(body, [
        ("consumer_role", "enum:" + SERVER_ROLES, True),
        ("consumer_major_version", "int", True),
        ("dependency_role", "enum:" + SERVER_ROLES, True),
        ("allowed_dependency_major_versions", "int_list", True),
        ("strict", "bool", True),
    ])
    rec = store.new_record()
    rec.update({
        "consumer_role": body["consumer_role"],
        "consumer_major_version": body["consumer_major_version"],
        "dependency_role": body["dependency_role"],
        "allowed_dependency_major_versions": body["allowed_dependency_major_versions"],
        "strict": body["strict"],
    })
    store.compat_rules[rec["id"]] = rec
    return success(dict(rec), status=201)

"""Routes: env vars, domains, certificates, redirects."""

from datetime import timedelta
from flask import Blueprint, request

from db import db, new_id, now_iso, touch
from errors import err
from middleware import (
    require_roles, parse_pagination, body, require_fields, require_str,
)
from response import ok_object, ok_list, ok_empty
from services import (
    env_var_view, domain_view, certificate_view, redirect_view,
    get_project_or_404, get_domain_or_404, get_certificate_or_404,
    create_certificate, CERT_VALIDITY_DAYS,
)

bp = Blueprint("misc", __name__)

ALL_READ = ("PlatformAdmin", "TeamOwner", "TeamBillingManager", "Developer", "Viewer")
SCOPES = ("DEVELOPMENT", "PREVIEW", "PRODUCTION")


def _paginate(items, sort_key=None, view=None):
    limit, offset = parse_pagination()
    if sort_key:
        items = sorted(items, key=sort_key)
    else:
        items = sorted(items, key=lambda x: (x["created_at_dt"], x["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    if view:
        page = [view(x) for x in page]
    return ok_list(page, total, limit, offset)


def _check_project_mutable(project):
    if project["status"] == "ARCHIVED":
        err("ERR_PROJECT_ARCHIVED", "Mutation attempted on an ARCHIVED project or its children")


# --- Env vars ---------------------------------------------------------------

def _validate_scopes(scopes):
    if not isinstance(scopes, list) or not scopes:
        err("ERR_INVALID_REQUEST", "scopes must be a non-empty array")
    for s in scopes:
        if s not in SCOPES:
            err("ERR_INVALID_REQUEST", "scopes must be a subset of DEVELOPMENT|PREVIEW|PRODUCTION")
    if len(set(scopes)) != len(scopes):
        err("ERR_INVALID_REQUEST", "scopes must not contain duplicates")


@bp.post("/v1/projects/<project_id>/env-vars")
@require_roles("TeamOwner", "Developer")
def create_env_var(project_id):
    project = get_project_or_404(project_id)
    _check_project_mutable(project)
    data = body()
    require_fields(data, "key", "value", "scopes")
    key = require_str(data, "key")
    value = data["value"]
    if not isinstance(value, str):
        err("ERR_INVALID_REQUEST", "value must be a string")
    scopes = data["scopes"]
    _validate_scopes(scopes)
    is_secret = data.get("is_secret", False)
    if not isinstance(is_secret, bool):
        err("ERR_INVALID_REQUEST", "is_secret must be a boolean")
    for e in db.env_vars.values():
        if e["project_id"] == project_id and e["key"] == key:
            if set(e["scopes"]) & set(scopes):
                err("ERR_ENV_SCOPE_OVERLAP",
                    "Another env var with same key in project already covers one of the requested scopes")
    ev = {
        "id": new_id(), "project_id": project_id, "key": key, "value": value,
        "scopes": list(scopes), "is_secret": is_secret,
        "created_at": now_iso(), "updated_at": now_iso(), "version": 1,
        "created_at_dt": db.clock,
    }
    db.env_vars[ev["id"]] = ev
    return ok_object(env_var_view(ev), 201)


@bp.get("/v1/projects/<project_id>/env-vars")
@require_roles(*ALL_READ)
def list_env_vars(project_id):
    get_project_or_404(project_id)
    scope = request.args.get("scope")
    items = [e for e in db.env_vars.values() if e["project_id"] == project_id
             and (scope is None or scope in e["scopes"])]
    return _paginate(items, view=env_var_view)


def _get_env_var_or_404(ev_id):
    e = db.env_vars.get(ev_id)
    if not e:
        err("ERR_ENV_VAR_NOT_FOUND", "EnvironmentVariable id does not exist")
    return e


@bp.get("/v1/env-vars/<ev_id>")
@require_roles(*ALL_READ)
def get_env_var(ev_id):
    return ok_object(env_var_view(_get_env_var_or_404(ev_id)))


@bp.patch("/v1/env-vars/<ev_id>")
@require_roles("TeamOwner", "Developer")
def patch_env_var(ev_id):
    ev = _get_env_var_or_404(ev_id)
    project = db.projects[ev["project_id"]]
    _check_project_mutable(project)
    data = body()
    new_scopes = ev["scopes"]
    if "scopes" in data and data["scopes"] is not None:
        _validate_scopes(data["scopes"])
        new_scopes = list(data["scopes"])
    # re-validate overlap against other same-key vars
    for e in db.env_vars.values():
        if e["project_id"] == ev["project_id"] and e["key"] == ev["key"] \
                and e["id"] != ev["id"]:
            if set(e["scopes"]) & set(new_scopes):
                err("ERR_ENV_SCOPE_OVERLAP",
                    "Another env var with same key in project already covers one of the requested scopes")
    if "value" in data and data["value"] is not None:
        if not isinstance(data["value"], str):
            err("ERR_INVALID_REQUEST", "value must be a string")
        ev["value"] = data["value"]
    ev["scopes"] = new_scopes
    if "is_secret" in data and data["is_secret"] is not None:
        if not isinstance(data["is_secret"], bool):
            err("ERR_INVALID_REQUEST", "is_secret must be a boolean")
        ev["is_secret"] = data["is_secret"]
    touch(ev)
    return ok_object(env_var_view(ev))


@bp.delete("/v1/env-vars/<ev_id>")
@require_roles("TeamOwner", "Developer")
def delete_env_var(ev_id):
    ev = _get_env_var_or_404(ev_id)
    project = db.projects[ev["project_id"]]
    _check_project_mutable(project)
    del db.env_vars[ev_id]
    return ok_empty(204)


# --- Domains -----------------------------------------------------------------

@bp.post("/v1/projects/<project_id>/domains")
@require_roles("TeamOwner", "Developer")
def create_domain(project_id):
    project = get_project_or_404(project_id)
    _check_project_mutable(project)
    data = body()
    require_fields(data, "name")
    name = require_str(data, "name")
    for d in db.domains.values():
        if d["name"] == name:
            err("ERR_DOMAIN_ALREADY_ASSIGNED", "Domain name already assigned to any project")
    dom = {
        "id": new_id(), "project_id": project_id, "name": name,
        "certificate_id": None, "verification_status": "PENDING",
        "status": "ACTIVE", "created_at": now_iso(), "updated_at": now_iso(),
        "version": 1, "created_at_dt": db.clock,
    }
    db.domains[dom["id"]] = dom
    return ok_object(domain_view(dom), 201)


@bp.get("/v1/projects/<project_id>/domains")
@require_roles(*ALL_READ)
def list_domains(project_id):
    get_project_or_404(project_id)
    items = [d for d in db.domains.values() if d["project_id"] == project_id]
    return _paginate(items, view=domain_view)


@bp.get("/v1/domains/<domain_id>")
@require_roles(*ALL_READ)
def get_domain(domain_id):
    return ok_object(domain_view(get_domain_or_404(domain_id)))


@bp.patch("/v1/domains/<domain_id>")
@require_roles("TeamOwner")
def patch_domain(domain_id):
    dom = get_domain_or_404(domain_id)
    data = body()
    expected = data.get("expected_domain_version")
    if expected is not None and expected != dom["version"]:
        err("ERR_STALE_VERSION", "expected_domain_version does not match current version")
    if "name" in data and data["name"] is not None:
        if not isinstance(data["name"], str):
            err("ERR_INVALID_REQUEST", "name must be a string")
        for d in db.domains.values():
            if d["name"] == data["name"] and d["id"] != dom["id"]:
                err("ERR_DOMAIN_ALREADY_ASSIGNED", "Domain name already assigned to any project")
        dom["name"] = data["name"]
    touch(dom)
    return ok_object(domain_view(dom))


@bp.post("/v1/domains/<domain_id>/verify")
@require_roles("TeamOwner", "Developer")
def verify_domain(domain_id):
    dom = get_domain_or_404(domain_id)
    data = body()
    require_fields(data, "outcome")
    outcome = data["outcome"]
    if outcome not in ("SUCCESS", "FAILURE"):
        err("ERR_INVALID_REQUEST", "outcome must be SUCCESS or FAILURE")
    if dom["verification_status"] != "PENDING":
        err("ERR_INVALID_STATE", "Domain.verification_status == PENDING required")
    if outcome == "SUCCESS":
        dom["verification_status"] = "VERIFIED"
        has_cert = any(c["domain_id"] == dom["id"] for c in db.certificates.values())
        if not has_cert:
            create_certificate(dom)
    else:
        dom["verification_status"] = "FAILED"
    touch(dom)
    return ok_object(domain_view(dom))


@bp.post("/v1/domains/<domain_id>/reverify")
@require_roles("TeamOwner", "Developer")
def reverify_domain(domain_id):
    dom = get_domain_or_404(domain_id)
    if dom["verification_status"] != "FAILED":
        err("ERR_INVALID_STATE", "Domain.verification_status == FAILED required")
    dom["verification_status"] = "PENDING"
    touch(dom)
    return ok_object(domain_view(dom))


@bp.delete("/v1/domains/<domain_id>")
@require_roles("TeamOwner")
def delete_domain(domain_id):
    dom = get_domain_or_404(domain_id)
    for cert in db.certificates.values():
        if cert["domain_id"] == domain_id and cert["status"] == "ACTIVE":
            cert["status"] = "REVOKED"
            touch(cert)
    del db.domains[domain_id]
    return ok_empty(204)


# --- Certificates --------------------------------------------------------------

@bp.get("/v1/domains/<domain_id>/certificates")
@require_roles(*ALL_READ)
def list_certificates(domain_id):
    get_domain_or_404(domain_id)
    items = [c for c in db.certificates.values() if c["domain_id"] == domain_id]
    return _paginate(items, view=certificate_view)


@bp.get("/v1/certificates/<cert_id>")
@require_roles(*ALL_READ)
def get_certificate(cert_id):
    return ok_object(certificate_view(get_certificate_or_404(cert_id)))


@bp.post("/v1/certificates/<cert_id>/complete")
@require_roles("SystemWebhook")
def complete_certificate(cert_id):
    cert = get_certificate_or_404(cert_id)
    if cert["status"] != "ISSUING":
        err("ERR_INVALID_STATE", "Certificate.status == ISSUING required")
    cert["status"] = "ACTIVE"
    cert["not_before"] = now_iso()
    not_after_dt = db.clock + timedelta(days=CERT_VALIDITY_DAYS)
    cert["not_after_dt"] = not_after_dt
    from db import format_ts
    cert["not_after"] = format_ts(not_after_dt)
    domain = db.domains.get(cert["domain_id"])
    if domain:
        prior_id = domain.get("certificate_id")
        if prior_id and prior_id != cert["id"]:
            prior = db.certificates.get(prior_id)
            if prior and prior["status"] == "ACTIVE":
                prior["status"] = "EXPIRED"
                touch(prior)
                cert["auto_renewed_from_id"] = prior_id
        domain["certificate_id"] = cert["id"]
        if domain["status"] == "SUSPENDED":
            domain["status"] = "ACTIVE"
        touch(domain)
    touch(cert)
    return ok_object(certificate_view(cert))


@bp.post("/v1/certificates/<cert_id>/revoke")
@require_roles("TeamOwner")
def revoke_certificate(cert_id):
    cert = get_certificate_or_404(cert_id)
    if cert["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", "Certificate.status == ACTIVE required")
    cert["status"] = "REVOKED"
    touch(cert)
    domain = db.domains.get(cert["domain_id"])
    if domain:
        if domain.get("certificate_id") == cert["id"]:
            domain["certificate_id"] = None
        domain["status"] = "SUSPENDED"
        touch(domain)
    return ok_object(certificate_view(cert))


# --- Redirects ------------------------------------------------------------------

REDIRECT_STATUS_CODES = (301, 302, 307, 308)


@bp.post("/v1/projects/<project_id>/redirects")
@require_roles("TeamOwner", "Developer")
def create_redirect(project_id):
    project = get_project_or_404(project_id)
    _check_project_mutable(project)
    data = body()
    require_fields(data, "source", "target", "status_code", "priority")
    source = require_str(data, "source")
    target = require_str(data, "target")
    status_code = data["status_code"]
    if status_code not in REDIRECT_STATUS_CODES:
        err("ERR_INVALID_REQUEST", "status_code must be one of 301|302|307|308")
    priority = data["priority"]
    if not isinstance(priority, int) or isinstance(priority, bool):
        err("ERR_INVALID_REQUEST", "priority must be an integer")
    for r in db.redirects.values():
        if r["project_id"] == project_id and r["priority"] == priority:
            err("ERR_REDIRECT_PRIORITY_CONFLICT",
                "Another redirect in the project already uses this priority")
    red = {
        "id": new_id(), "project_id": project_id, "source": source,
        "target": target, "status_code": status_code, "priority": priority,
        "created_at": now_iso(), "updated_at": now_iso(), "version": 1,
        "created_at_dt": db.clock,
    }
    db.redirects[red["id"]] = red
    return ok_object(redirect_view(red), 201)


@bp.get("/v1/projects/<project_id>/redirects")
@require_roles(*ALL_READ)
def list_redirects(project_id):
    get_project_or_404(project_id)
    items = [r for r in db.redirects.values() if r["project_id"] == project_id]
    # redirects sorted by priority ASC (explicit exception to created_at ordering)
    return _paginate(items, sort_key=lambda r: r["priority"],
                     view=redirect_view)


def _get_redirect_or_404(red_id):
    r = db.redirects.get(red_id)
    if not r:
        err("ERR_REDIRECT_NOT_FOUND", "Redirect id does not exist")
    return r


@bp.get("/v1/redirects/<red_id>")
@require_roles(*ALL_READ)
def get_redirect(red_id):
    return ok_object(redirect_view(_get_redirect_or_404(red_id)))


@bp.delete("/v1/redirects/<red_id>")
@require_roles("TeamOwner", "Developer")
def delete_redirect(red_id):
    r = _get_redirect_or_404(red_id)
    project = db.projects[r["project_id"]]
    _check_project_mutable(project)
    del db.redirects[red_id]
    return ok_empty(204)

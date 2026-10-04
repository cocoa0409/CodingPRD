import re
from datetime import timedelta

import db
import clock
import fiscal
import engine
from util import fmt_iso, parse_iso, add_years, hash_token
from services import domain_view, link_view, AUTO_RENEW_GRACE_DAYS, REDEMPTION_GRACE_DAYS
from middleware import require_roles, body_json, require_fields, pagination_params
from response import success_object, success_list
from errors import (
    err_invalid_request, err_not_found, err_invalid_state, err_stale_version, ApiError,
)
from flask import Blueprint, request

bp = Blueprint("domains", __name__)

NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$")


def _get_domain_or_404(did):
    d = db.domains.get(did)
    if d is None:
        raise err_not_found()
    return d


def _check_sponsoring_registrar(d, user_id=None):
    reg = db.registrars.get(d["registrar_id"]) if d["registrar_id"] else None
    if reg is None or reg["status"] != "ACTIVE":
        raise ApiError("ERR_REGISTRAR_NOT_ACTIVE", "Sponsoring registrar is not ACTIVE", 409)
    if reg["credit_hold"]:
        raise ApiError("ERR_REGISTRAR_CREDIT_HOLD", "Registrar credit_hold blocks billable mutations", 409)
    return reg


@bp.post("/domains")
def create_domain():
    role, user_id = require_roles("RegistrarOperator")
    data = body_json()
    require_fields(data, ["name", "registrar_id", "years"])
    name = data["name"]
    if not isinstance(name, str) or not NAME_RE.match(name) or len(name) > 63:
        raise err_invalid_request("name must be a lowercase [a-z0-9-] label, 1..63 chars, no leading/trailing hyphen")
    rid = data["registrar_id"]
    if not isinstance(rid, str):
        raise err_invalid_request("registrar_id must be a string")
    reg = db.registrars.get(rid)
    if reg is None:
        raise err_not_found("registrar_id does not exist")
    years = data["years"]
    if isinstance(years, bool) or not isinstance(years, int) or years < 1 or years > 10:
        raise err_invalid_request("years must be an integer between 1 and 10")
    premium = data.get("premium", False)
    if not isinstance(premium, bool):
        raise err_invalid_request("premium must be boolean")
    # uniqueness among non-DELETED
    for d in db.domains.values():
        if d["name"] == name and d["status"] != "DELETED":
            raise ApiError("ERR_DOMAIN_NAME_TAKEN", "Domain name already registered", 409)
    if reg["status"] != "ACTIVE":
        raise ApiError("ERR_REGISTRAR_NOT_ACTIVE", "Sponsoring registrar is not ACTIVE", 409)
    if reg["credit_hold"]:
        raise ApiError("ERR_REGISTRAR_CREDIT_HOLD", "Registrar credit_hold blocks billable mutations", 409)
    now = clock.now()
    expires = add_years(now, years)
    rec = db.new_common(now)
    rec.update({
        "name": name,
        "registrar_id": rid,
        "years": years,
        "premium": premium,
        "expires_on": fmt_iso(expires),
        "grace_deadline": fmt_iso(expires + timedelta(days=AUTO_RENEW_GRACE_DAYS)),
        "status": "ACTIVE",
        "lock_status": "NONE",
        "suspension_status": "NONE",
        "registry_lock_token_hash": None,
        "auto_renewed_on": None,
        "delete_scheduled_on": None,
        "_redemption_entered_at": None,
    })
    db.domains[rec["id"]] = rec
    fiscal.lifecycle_invoice(rid, rec, "CREATE", years)
    return success_object(domain_view(rec), 201)


@bp.get("/domains")
def list_domains():
    require_roles("RegistryAdmin", "RegistrarOperator", "RegistryFinance", "AbuseAnalyst")
    limit, offset = pagination_params()
    rows = sorted(db.domains.values(), key=lambda d: d["created_at"])
    rid = request.args.get("registrar_id")
    status = request.args.get("status")
    name = request.args.get("name")
    if rid:
        rows = [d for d in rows if d["registrar_id"] == rid]
    if status:
        rows = [d for d in rows if d["status"] == status]
    if name:
        rows = [d for d in rows if d["name"] == name]
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([domain_view(d) for d in page], limit, offset, total)


@bp.get("/domains/<did>")
def get_domain(did):
    require_roles("RegistryAdmin", "RegistrarOperator", "RegistryFinance", "AbuseAnalyst")
    d = _get_domain_or_404(did)
    return success_object(domain_view(d))


@bp.post("/domains/<did>/renew")
def renew_domain(did):
    role, user_id = require_roles("RegistrarOperator")
    d = _get_domain_or_404(did)
    data = body_json()
    require_fields(data, ["years"])
    years = data["years"]
    if isinstance(years, bool) or not isinstance(years, int) or years < 1:
        raise err_invalid_request("years must be an integer >= 1")
    if d["status"] not in ("ACTIVE", "AUTO_RENEW_GRACE"):
        raise err_invalid_state()
    if d["suspension_status"] != "NONE":
        raise ApiError("ERR_DOMAIN_SUSPENDED", "Domain suspension blocks lifecycle mutations", 409)
    now = clock.now()
    if d["status"] == "ACTIVE":
        if now > parse_iso(d["grace_deadline"]):
            raise ApiError("ERR_GRACE_WINDOW_CLOSED", "Renewal attempted after grace_deadline", 409)
    new_expiry = add_years(parse_iso(d["expires_on"]), years)
    # total term cap: expires_on + years must not exceed expires_on + 10 years
    if parse_iso(d["expires_on"]) < new_expiry and \
       new_expiry > add_years(parse_iso(d["expires_on"]), 10):
        raise err_invalid_request("years exceeds 10-year total term cap")
    _check_sponsoring_registrar(d)
    d["expires_on"] = fmt_iso(new_expiry)
    d["grace_deadline"] = fmt_iso(new_expiry + timedelta(days=AUTO_RENEW_GRACE_DAYS))
    d["status"] = "ACTIVE"
    d["auto_renewed_on"] = None
    db.touch(d, now)
    fiscal.lifecycle_invoice(d["registrar_id"], d, "RENEW", years)
    return success_object(domain_view(d))


@bp.post("/domains/<did>/delete")
def delete_domain(did):
    role, user_id = require_roles("RegistrarOperator")
    d = _get_domain_or_404(did)
    if d["status"] not in ("ACTIVE", "AUTO_RENEW_GRACE"):
        raise err_invalid_state()
    if d["suspension_status"] != "NONE":
        raise ApiError("ERR_DOMAIN_SUSPENDED", "Domain suspension blocks lifecycle mutations", 409)
    if d["lock_status"] != "NONE":
        raise ApiError("ERR_DOMAIN_LOCKED", "Domain lock blocks registrar deletes", 409)
    reg = db.registrars.get(d["registrar_id"]) if d["registrar_id"] else None
    if reg is None or reg["status"] != "ACTIVE":
        raise ApiError("ERR_REGISTRAR_NOT_ACTIVE", "Sponsoring registrar is not ACTIVE", 409)
    engine.explicit_delete_to_redemption(d)
    return success_object(domain_view(d))


@bp.post("/domains/<did>/restore")
def restore_domain(did):
    role, user_id = require_roles("RegistrarOperator")
    d = _get_domain_or_404(did)
    if d["status"] != "REDEMPTION_GRACE":
        raise err_invalid_state()
    if d["suspension_status"] != "NONE":
        raise ApiError("ERR_DOMAIN_SUSPENDED", "Domain suspension blocks lifecycle mutations", 409)
    now = clock.now()
    entry = parse_iso(d["_redemption_entered_at"])
    if now > entry + timedelta(days=REDEMPTION_GRACE_DAYS):
        raise ApiError("ERR_REDEMPTION_WINDOW_CLOSED", "Restore attempted after 30-day window", 409)
    _check_sponsoring_registrar(d)
    new_expiry = add_years(parse_iso(d["expires_on"]), 1)
    d["expires_on"] = fmt_iso(new_expiry)
    d["grace_deadline"] = fmt_iso(new_expiry + timedelta(days=AUTO_RENEW_GRACE_DAYS))
    d["status"] = "ACTIVE"
    d["auto_renewed_on"] = None
    db.touch(d, now)
    fiscal.lifecycle_invoice(d["registrar_id"], d, "RESTORE", 1)
    return success_object(domain_view(d))


@bp.post("/domains/<did>/lock")
def lock_domain(did):
    role, user_id = require_roles("RegistrarOperator", "RegistryAdmin")
    d = _get_domain_or_404(did)
    data = body_json()
    require_fields(data, ["lock_action", "expected_domain_version"])
    action = data["lock_action"]
    if action not in ("CLIENT_LOCK", "REGISTRY_LOCK", "NONE"):
        raise err_invalid_request("lock_action must be one of CLIENT_LOCK, REGISTRY_LOCK, NONE")
    ev = data["expected_domain_version"]
    if isinstance(ev, bool) or not isinstance(ev, int):
        raise err_invalid_request("expected_domain_version must be an integer")
    if ev != d["version"]:
        raise err_stale_version()
    token = data.get("lock_token")
    if action == "REGISTRY_LOCK":
        if not token or not isinstance(token, str):
            raise err_invalid_request("lock_token is required to engage REGISTRY_LOCK")
        d["lock_status"] = "REGISTRY_LOCK"
        d["registry_lock_token_hash"] = hash_token(token)
    elif action == "CLIENT_LOCK":
        d["lock_status"] = "CLIENT_LOCK"
    else:  # NONE releases any engaged lock
        d["lock_status"] = "NONE"
        d["registry_lock_token_hash"] = None
    db.touch(d, clock.now())
    return success_object(domain_view(d))


@bp.post("/domains/<did>/nameservers")
def link_nameserver(did):
    role, user_id = require_roles("RegistrarOperator")
    d = _get_domain_or_404(did)
    data = body_json()
    require_fields(data, ["nameserver_id"])
    nid = data["nameserver_id"]
    if not isinstance(nid, str) or nid not in db.nameservers:
        raise err_not_found("nameserver_id does not exist")
    now = clock.now()
    rec = {
        "id": db.new_id(),
        "domain_id": d["id"],
        "nameserver_id": nid,
        "created_at": fmt_iso(now),
    }
    db.links[rec["id"]] = rec
    return success_object(link_view(rec), 201)


@bp.get("/domains/<did>/nameservers")
def list_domain_links(did):
    require_roles("RegistryAdmin", "RegistrarOperator", "AbuseAnalyst")
    d = _get_domain_or_404(did)
    rows = sorted([l for l in db.links.values() if l["domain_id"] == d["id"]],
                  key=lambda l: l["created_at"])
    return success_list([link_view(l) for l in rows], len(rows) or 1, 0, len(rows))

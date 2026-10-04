"""Rights grants: create, list, get, terminate."""
from flask import Blueprint

from db import db, parse_iso
from errors import err_invalid_request, err_already_terminal, err_invalid_state
from middleware import require_roles
from paginate import parse_pagination, paginate
from response import success
from services import new_resource, touch, get_or_404, cascade_grant_end
from validate import (
    body_json, req_string, req_enum, req_datetime, req_int,
)

bp = Blueprint("rights_grants", __name__)


@bp.post("/rights-grants")
@require_roles("PlatformAdmin")
def create_rights_grant(auth):
    body = body_json()
    distributor_name = req_string(body, "distributor_name")
    scope = req_enum(body, "scope", {"OUT_OF_MARKET"})
    exclusivity = req_enum(body, "exclusivity", {"EXCLUSIVE", "NON_EXCLUSIVE"})
    effective_from = req_datetime(body, "effective_from")
    effective_until = req_datetime(body, "effective_until")
    max_cap = req_int(body, "max_commercial_occupancy_cap", minimum=1)
    if parse_iso(effective_until) <= parse_iso(effective_from):
        raise err_invalid_request("effective_until must be strictly after effective_from")

    grant = new_resource()
    grant.update({
        "distributor_name": distributor_name,
        "scope": scope,
        "exclusivity": exclusivity,
        "effective_from": effective_from,
        "effective_until": effective_until,
        "max_commercial_occupancy_cap": max_cap,
        "status": "ACTIVE",
    })
    db.rights_grants[grant["id"]] = grant
    return success(grant, status=201)


@bp.get("/rights-grants")
@require_roles("PlatformAdmin", "LeagueOps", "ComplianceAuditor")
def list_rights_grants(auth):
    limit, offset = parse_pagination()
    status = None
    from flask import request
    status = request.args.get("status")
    items = sorted(db.rights_grants.values(), key=lambda r: r["created_at"])
    if status is not None:
        items = [g for g in items if g["status"] == status]
    window, page = paginate(items, limit, offset)
    return success(window, pagination=page)


@bp.get("/rights-grants/<rid>")
@require_roles("PlatformAdmin", "LeagueOps", "ComplianceAuditor")
def get_rights_grant(rid, auth):
    grant = get_or_404(db.rights_grants, rid)
    return success(grant)


@bp.post("/rights-grants/<rid>/terminate")
@require_roles("PlatformAdmin")
def terminate_rights_grant(rid, auth):
    grant = get_or_404(db.rights_grants, rid)
    if grant["status"] in ("EXPIRED", "TERMINATED"):
        raise err_already_terminal()
    if grant["status"] != "ACTIVE":
        raise err_invalid_state()
    grant["status"] = "TERMINATED"
    touch(grant)
    cascade_grant_end(grant)
    return success(grant)

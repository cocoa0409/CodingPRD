"""Data share grants: grower-owned scoped sharing with closed-interval
overlap rejection (PRD section 3.4)."""

from flask import Blueprint, request

from auth import (
    as_dt,
    as_enum,
    as_scopes,
    as_str,
    body_json,
    caller,
    get_or_404,
    list_resources,
    need,
    require_role,
    access_denied,
)
from constants import GRANTEE_TO_ROLE
from db import STORES, now
from domain import new_record, serialize, touch
from envelope import created, ok, ok_list
from errors import ERR_GRANT_WINDOW_OVERLAP, ERR_INVALID_REQUEST, ApiError, invalid_state

bp = Blueprint("grants", __name__)

GRANTEE_TYPES = {"AGRONOMIST", "COOPERATIVE", "DEALER", "THIRD_PARTY_APP"}
GRANT_READ_ROLES = {
    "GrowerManager",
    "PlatformAdmin",
    "Agronomist",
    "CoopAnalyst",
    "DealerTechnician",
    "PartnerApp",
}


@bp.post("/data-share-grants")
def create_grant():
    uid, role = caller()
    require_role(role, {"GrowerManager"})
    b = body_json()
    organization_id = as_str(need(b, "organization_id"), "organization_id")
    grantee_type = as_enum(need(b, "grantee_type"), "grantee_type", GRANTEE_TYPES)
    grantee_ref_id = as_str(need(b, "grantee_ref_id"), "grantee_ref_id")
    scopes = as_scopes(need(b, "scopes"))
    valid_from = as_dt(need(b, "valid_from"), "valid_from")
    valid_until = as_dt(need(b, "valid_until"), "valid_until")
    if not valid_from < valid_until:
        raise ApiError(ERR_INVALID_REQUEST, 400, "valid_from must precede valid_until")
    get_or_404("organizations", organization_id, "organization")
    if uid != organization_id:
        raise access_denied("grower may grant only its own organization's data")
    # Closed-interval overlap per (organization, grantee_type, grantee_ref_id)
    # sharing at least one scope, against ACTIVE or SUSPENDED grants
    for g in STORES["data_share_grants"].values():
        if g["organization_id"] != organization_id:
            continue
        if g["grantee_type"] != grantee_type or g["grantee_ref_id"] != grantee_ref_id:
            continue
        if g["status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        if not (set(g["scopes"]) & set(scopes)):
            continue
        if valid_from <= g["valid_until"] and g["valid_from"] <= valid_until:
            raise ApiError(ERR_GRANT_WINDOW_OVERLAP, 409, "grant window overlaps an existing grant")
    rec = new_record(
        {
            "organization_id": organization_id,
            "grantee_type": grantee_type,
            "grantee_ref_id": grantee_ref_id,
            "scopes": scopes,
            "valid_from": valid_from,
            "valid_until": valid_until,
            "status": "ACTIVE",
        }
    )
    STORES["data_share_grants"][rec["id"]] = rec
    return created(serialize(rec))


def _grant_visible(g, role, uid):
    if role == "PlatformAdmin":
        return True
    if role == "GrowerManager":
        return uid == g["organization_id"]
    return GRANTEE_TO_ROLE.get(g["grantee_type"]) == role and g["grantee_ref_id"] == uid


@bp.get("/data-share-grants/<gid>")
def get_grant(gid):
    uid, role = caller()
    require_role(role, GRANT_READ_ROLES)
    g = get_or_404("data_share_grants", gid, "data share grant")
    if not _grant_visible(g, role, uid):
        raise access_denied("caller is neither the org owner nor the grantee")
    return ok(serialize(g))


@bp.get("/data-share-grants")
def list_grants():
    uid, role = caller()
    require_role(role, GRANT_READ_ROLES)
    org_filter = request.args.get("organization_id")
    filters = []
    for f in ("organization_id", "grantee_ref_id", "status"):
        v = request.args.get(f)
        if v is not None:
            filters.append((f, v))
    if role == "GrowerManager" and org_filter is not None and org_filter != uid:
        raise access_denied("grower may list only its own organization")
    visible = lambda r: _grant_visible(r, role, uid)
    page, total, limit, offset = list_resources("data_share_grants", filters, visible)
    return ok_list([serialize(r) for r in page], total, limit, offset)


def _owned_grant(gid, uid):
    g = get_or_404("data_share_grants", gid, "data share grant")
    if uid != g["organization_id"]:
        raise access_denied("grant belongs to another organization")
    return g


@bp.post("/data-share-grants/<gid>/suspend")
def suspend_grant(gid):
    uid, role = caller()
    require_role(role, {"GrowerManager"})
    g = _owned_grant(gid, uid)
    if g["status"] != "ACTIVE":
        raise invalid_state("grant is not ACTIVE")
    g["status"] = "SUSPENDED"
    touch(g)
    return ok(serialize(g))


@bp.post("/data-share-grants/<gid>/resume")
def resume_grant(gid):
    uid, role = caller()
    require_role(role, {"GrowerManager"})
    g = _owned_grant(gid, uid)
    if g["status"] != "SUSPENDED":
        raise invalid_state("grant is not SUSPENDED")
    # Temporal window: a resume past valid_until is rejected
    if now() > g["valid_until"]:
        raise invalid_state("grant validity window has passed")
    g["status"] = "ACTIVE"
    touch(g)
    return ok(serialize(g))


@bp.post("/data-share-grants/<gid>/revoke")
def revoke_grant(gid):
    uid, role = caller()
    require_role(role, {"GrowerManager"})
    g = _owned_grant(gid, uid)
    if g["status"] not in ("ACTIVE", "SUSPENDED"):
        raise invalid_state("grant is not ACTIVE or SUSPENDED")
    g["status"] = "REVOKED"
    touch(g)
    return ok(serialize(g))

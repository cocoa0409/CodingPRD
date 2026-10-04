"""Contributor and ContributorGrant endpoints."""
from flask import Blueprint, request

import clock
import domain
import store
from errors import raise_err
from response import envelope, require_roles, body, paginate
from validation import require_fields, require_enum, get_or_404

bp = Blueprint("contributors", __name__)

SOURCE_TYPES = {"EDIT", "PHOTO", "REVIEW", "VERIFICATION_ASSIST", "ADJUSTMENT"}


@bp.post("/v1/contributors")
def create_contributor():
    require_roles({"Anonymous"})
    data = body()
    require_fields(data, ["display_name", "email", "home_region_id"])
    region = store.regions.get(data["home_region_id"])
    if region is None:
        raise_err("ERR_NOT_FOUND", "home_region_id not found")
    email = data["email"]
    if not isinstance(email, str) or "@" not in email:
        raise_err("ERR_INVALID_REQUEST", "email invalid")
    if any(c["email"] == email for c in store.contributors.values()):
        raise_err("ERR_INVALID_REQUEST", "email already registered")
    now = clock.iso(clock.now())
    rec = {
        "id": domain.new_id(),
        "display_name": data["display_name"],
        "email": email,
        "home_region_id": region["id"],
        "status": "ACTIVE",
        "total_points": 0,
        "lifetime_points": 0,
        "level": "NEWCOMER",
        "provisional_trust_score": 50,
        "finalized_trust_score": 50,
        "failed_verification_count": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.contributors[rec["id"]] = rec
    return envelope(domain.contributor_view(rec), status=201)


@bp.get("/v1/contributors")
def list_contributors():
    require_roles({"PlatformAdmin", "Moderator", "PolicyAnalyst"})
    items = list(store.contributors.values())
    for f in ("status", "level", "home_region_id"):
        v = request.args.get(f)
        if v is not None:
            if f == "level":
                items = [c for c in items
                         if domain.recompute_points(c) == v]
            else:
                items = [c for c in items if c[f] == v]
    page, pg = paginate(items, request.args)
    return envelope([domain.contributor_view(c) for c in page],
                    response_type="array", pagination=pg)


@bp.get("/v1/contributors/<cid>")
def get_contributor(cid):
    require_roles({"PlatformAdmin", "Contributor", "BusinessOwner", "Moderator", "PolicyAnalyst"})
    c = get_or_404(store.contributors, cid)
    domain.recompute_contributor(c, demote=True)
    return envelope(dict(c))


@bp.get("/v1/contributors/<cid>/grants")
def list_contributor_grants(cid):
    require_roles({"PlatformAdmin", "Contributor", "BusinessOwner", "Moderator", "PolicyAnalyst"})
    get_or_404(store.contributors, cid)
    items = [g for g in store.grants.values() if g["contributor_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        items = [g for g in items if g["status"] == status]
    page, pg = paginate(items, request.args)
    return envelope([domain.grant_view(g) for g in page],
                    response_type="array", pagination=pg)


@bp.post("/v1/contributor-grants")
def create_grant():
    require_roles({"PlatformAdmin"})
    data = body()
    require_fields(data, ["contributor_id", "source_type", "source_id", "base_points"])
    c = store.contributors.get(data["contributor_id"])
    if c is None:
        raise_err("ERR_NOT_FOUND", "contributor not found")
    source_type = require_enum(data, "source_type", SOURCE_TYPES)
    base = data["base_points"]
    if isinstance(base, bool) or not isinstance(base, int):
        raise_err("ERR_INVALID_REQUEST", "base_points must be an integer")
    mult = data.get("quality_multiplier", 1.0)
    if isinstance(mult, bool) or not isinstance(mult, (int, float)) \
            or mult < 0.0 or mult > 3.0:
        raise_err("ERR_INVALID_REQUEST", "quality_multiplier must be in [0.0, 3.0]")
    note = data.get("note", "")
    if source_type == "ADJUSTMENT" and (not isinstance(note, str) or not note.strip()):
        raise_err("ERR_INVALID_REQUEST", "note required for ADJUSTMENT grants")
    points = domain.round_half_up_int(base * mult)
    rec = {
        "id": domain.new_id(),
        "contributor_id": c["id"],
        "source_type": source_type,
        "source_id": data["source_id"],
        "base_points": base,
        "quality_multiplier": float(mult),
        "points": points,
        "status": "POSTED",
        "note": note,
        "created_at": clock.iso(clock.now()),
    }
    store.grants[rec["id"]] = rec
    domain.recompute_points(c)
    return envelope(domain.grant_view(rec), status=201)


@bp.post("/v1/contributor-grants/<gid>/revoke")
def revoke_grant(gid):
    require_roles({"PlatformAdmin", "Moderator"})
    g = get_or_404(store.grants, gid)
    if g["status"] != "POSTED":
        raise_err("ERR_INVALID_STATE", "grant not POSTED")
    g["status"] = "REVOKED"
    c = store.contributors.get(g["contributor_id"])
    if c is not None:
        domain.recompute_points(c)
    return envelope(domain.grant_view(g))

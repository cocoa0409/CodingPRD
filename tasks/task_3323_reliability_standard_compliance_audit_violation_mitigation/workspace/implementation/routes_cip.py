"""CIP asset and access grant endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from db import db
from errors import (
    err_active_access_grants, err_asset_decommissioned, err_entity_restricted,
    err_forbidden, err_invalid_request, err_invalid_state, err_not_found,
)
from helpers import (
    clock_now, new_common, parse_pagination, serialize, sort_and_page, touch,
)
from middleware import require_roles
from response import success_list, success_object

bp = Blueprint("cip", __name__)

READ_ROLES = (
    "ComplianceAuditor", "RegionalEntityReviewer", "FederalReviewer",
    "EntityComplianceOfficer", "CIPAssetManager",
)

IMPACT_RATINGS = {"HIGH", "MEDIUM", "LOW"}
SCOPES = {"PHYSICAL", "ELECTRONIC"}


@bp.post("/cip-assets")
def create_cip_asset():
    require_roles("CIPAssetManager")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("request body must be a JSON object")
    entity_id = body.get("entity_id")
    if not isinstance(entity_id, str):
        raise err_invalid_request("entity_id is required")
    entity = db.registered_entities.get(entity_id)
    if entity is None:
        raise err_not_found("RegisteredEntity not found")
    asset_name = body.get("asset_name")
    if not isinstance(asset_name, str) or not asset_name:
        raise err_invalid_request("asset_name is required")
    impact = body.get("impact_rating")
    if impact not in IMPACT_RATINGS:
        raise err_invalid_request("impact_rating must be HIGH, MEDIUM, or LOW")

    row = new_common()
    row.update({
        "entity_id": entity_id,
        "asset_name": asset_name,
        "impact_rating": impact,
        "is_bes_cyber_asset": impact == "HIGH",
        "status": "ACTIVE",
    })
    db.cip_assets[row["id"]] = row
    return success_object(serialize(row), status=201)


@bp.get("/cip-assets")
def list_cip_assets():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    rows = list(db.cip_assets.values())
    entity_id = request.args.get("entity_id")
    if entity_id is not None:
        rows = [r for r in rows if r["entity_id"] == entity_id]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = sort_and_page(rows, limit, offset)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.get("/cip-assets/<assetId>")
def get_cip_asset(assetId):
    require_roles(*READ_ROLES)
    row = db.cip_assets.get(assetId)
    if row is None:
        raise err_not_found("CIPAsset not found")
    return success_object(serialize(row))


@bp.post("/cip-assets/<assetId>/decommission")
def decommission_asset(assetId):
    require_roles("CIPAssetManager")
    row = db.cip_assets.get(assetId)
    if row is None:
        raise err_not_found("CIPAsset not found")
    if row["status"] != "ACTIVE":
        raise err_invalid_state("asset is not ACTIVE")
    active_grants = [
        g for g in db.access_grants.values()
        if g["asset_id"] == assetId and g["status"] == "ACTIVE"
    ]
    if active_grants:
        raise err_active_access_grants()
    row["status"] = "DECOMMISSIONED"
    touch(row)
    return success_object(serialize(row))


# ---------------------------------------------------------------------------
# Access grants
# ---------------------------------------------------------------------------

@bp.post("/access-grants")
def create_access_grant():
    user_id, _ = require_roles("CIPAssetManager")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("request body must be a JSON object")
    asset_id = body.get("asset_id")
    if not isinstance(asset_id, str):
        raise err_invalid_request("asset_id is required")
    asset = db.cip_assets.get(asset_id)
    if asset is None:
        raise err_not_found("CIPAsset not found")

    entity = db.registered_entities.get(asset["entity_id"])

    # posture gate (priority 4) — access grants are entity-initiated mutations
    if entity is not None and entity["compliance_status"] == "RESTRICTED":
        raise err_entity_restricted()

    grantee_badge = body.get("grantee_badge")
    if not isinstance(grantee_badge, str) or not grantee_badge:
        raise err_invalid_request("grantee_badge is required")
    scope = body.get("scope")
    if scope not in SCOPES:
        raise err_invalid_request("scope must be PHYSICAL or ELECTRONIC")

    # ownership: CIPAssetManager's entity must own the asset
    if asset["entity_id"] != user_id:
        raise err_forbidden()

    if asset["status"] != "ACTIVE":
        raise err_asset_decommissioned()

    row = new_common()
    row.update({
        "asset_id": asset_id,
        "grantee_badge": grantee_badge,
        "scope": scope,
        "granted_at": clock_now(),
        "revoked_at": None,
        "status": "ACTIVE",
    })
    db.access_grants[row["id"]] = row
    return success_object(serialize(row), status=201)


@bp.get("/access-grants")
def list_access_grants():
    require_roles("ComplianceAuditor", "RegionalEntityReviewer", "FederalReviewer", "CIPAssetManager")
    limit, offset = parse_pagination(request.args)
    rows = list(db.access_grants.values())
    asset_id = request.args.get("asset_id")
    if asset_id is not None:
        rows = [r for r in rows if r["asset_id"] == asset_id]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = sort_and_page(rows, limit, offset)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.get("/access-grants/<grantId>")
def get_access_grant(grantId):
    require_roles("ComplianceAuditor", "RegionalEntityReviewer", "FederalReviewer", "CIPAssetManager")
    row = db.access_grants.get(grantId)
    if row is None:
        raise err_not_found("AccessGrant not found")
    return success_object(serialize(row))


@bp.post("/access-grants/<grantId>/revoke")
def revoke_access_grant(grantId):
    require_roles("CIPAssetManager")
    row = db.access_grants.get(grantId)
    if row is None:
        raise err_not_found("AccessGrant not found")
    if row["status"] != "ACTIVE":
        raise err_invalid_state("grant is not ACTIVE")
    row["status"] = "REVOKED"
    row["revoked_at"] = clock_now()
    touch(row)
    return success_object(serialize(row))

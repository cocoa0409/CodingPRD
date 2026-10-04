"""Entitlement overrides: grant, list, get, rescind."""
from flask import Blueprint, request

from db import db
from errors import err_not_owner, err_already_terminal, err_invalid_state
from middleware import require_roles
from paginate import parse_pagination, paginate
from response import success
from services import new_resource, touch, get_or_404
from validate import body_json, req_string, req_enum

bp = Blueprint("entitlement_overrides", __name__)


@bp.post("/entitlement-overrides")
@require_roles("SupportAgent")
def create_override(auth):
    user_id, _role = auth
    body = body_json()
    account_id = req_string(body, "account_id")
    game_id = req_string(body, "game_id")
    reason_code = req_enum(body, "reason_code", {"GOODWILL", "SERVICE_OUTAGE", "REGULATORY"})
    get_or_404(db.accounts, account_id)
    get_or_404(db.games, game_id)

    override = new_resource()
    override.update({
        "account_id": account_id,
        "game_id": game_id,
        "reason_code": reason_code,
        "created_by": user_id,
        "status": "ACTIVE",
    })
    db.entitlement_overrides[override["id"]] = override
    return success(override, status=201)


@bp.get("/entitlement-overrides")
@require_roles("PlatformAdmin", "SupportAgent", "ComplianceAuditor")
def list_overrides(auth):
    limit, offset = parse_pagination()
    account_id = request.args.get("account_id")
    game_id = request.args.get("game_id")
    status = request.args.get("status")
    items = sorted(db.entitlement_overrides.values(), key=lambda r: r["created_at"])
    if account_id is not None:
        items = [o for o in items if o["account_id"] == account_id]
    if game_id is not None:
        items = [o for o in items if o["game_id"] == game_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    window, page = paginate(items, limit, offset)
    return success(window, pagination=page)


@bp.get("/entitlement-overrides/<oid>")
@require_roles("PlatformAdmin", "SupportAgent", "ComplianceAuditor")
def get_override(oid, auth):
    override = get_or_404(db.entitlement_overrides, oid)
    return success(override)


@bp.post("/entitlement-overrides/<oid>/rescind")
@require_roles("SupportAgent")
def rescind_override(oid, auth):
    user_id, _role = auth
    override = get_or_404(db.entitlement_overrides, oid)
    if override["status"] == "RESCINDED":
        raise err_already_terminal()
    if override["status"] != "ACTIVE":
        raise err_invalid_state()
    if override["created_by"] != user_id:
        raise err_not_owner()
    override["status"] = "RESCINDED"
    touch(override)
    return success(override)

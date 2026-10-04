"""Game entitlements: list, get."""
from flask import Blueprint, request

from db import db
from errors import err_invalid_request
from middleware import require_roles
from paginate import parse_pagination, paginate
from response import success
from services import get_or_404

bp = Blueprint("game_entitlements", __name__)


@bp.get("/game-entitlements")
@require_roles("PlatformAdmin", "SupportAgent", "ComplianceAuditor")
def list_game_entitlements(auth):
    limit, offset = parse_pagination()
    subscription_id = request.args.get("subscription_id")
    game_id = request.args.get("game_id")
    week_index = request.args.get("week_index")
    status = request.args.get("status")
    items = sorted(db.game_entitlements.values(), key=lambda r: r["created_at"])
    if subscription_id is not None:
        items = [e for e in items if e["subscription_id"] == subscription_id]
    if game_id is not None:
        items = [e for e in items if e["game_id"] == game_id]
    if week_index is not None:
        try:
            wi = int(week_index)
        except (TypeError, ValueError):
            raise err_invalid_request("week_index must be an integer")
        items = [e for e in items if e["week_index"] == wi]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    window, page = paginate(items, limit, offset)
    return success(window, pagination=page)


@bp.get("/game-entitlements/<eid>")
@require_roles("PlatformAdmin", "SupportAgent", "ComplianceAuditor")
def get_game_entitlement(eid, auth):
    ent = get_or_404(db.game_entitlements, eid)
    return success(ent)

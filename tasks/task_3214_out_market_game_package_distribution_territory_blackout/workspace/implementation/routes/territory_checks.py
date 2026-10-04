"""Territory checks: run, list, get."""
from flask import Blueprint, request

from db import db
from errors import err_not_owner
from middleware import require_roles
from paginate import parse_pagination, paginate
from response import success
from services import (
    new_resource, get_or_404, resolve_market, effective_market, compute_verdict,
)
from validate import body_json, req_string, req_zip

bp = Blueprint("territory_checks", __name__)


@bp.post("/territory-checks")
@require_roles("Subscriber", "VenueManager", "SupportAgent")
def create_territory_check(auth):
    body = body_json()
    account_id = req_string(body, "account_id")
    subscription_id = req_string(body, "subscription_id")
    game_id = req_string(body, "game_id")
    device_zip = req_zip(body, "device_zip")
    account = get_or_404(db.accounts, account_id)
    subscription = get_or_404(db.subscriptions, subscription_id)
    game = get_or_404(db.games, game_id)

    user_id, role = auth
    if role in ("Subscriber", "VenueManager") and user_id != account["id"]:
        raise err_not_owner()

    device_market_code = resolve_market(device_zip)
    eff_market = effective_market(account, device_market_code)
    verdict = compute_verdict(account, subscription, game, eff_market)

    check = new_resource(common=False)
    check.update({
        "account_id": account["id"],
        "subscription_id": subscription["id"],
        "game_id": game["id"],
        "device_zip": device_zip,
        "device_market_code": device_market_code,
        "effective_market_code": eff_market,
        "verdict": verdict,
        "checked_at": db.clock.now_iso(),
    })
    db.territory_checks[check["id"]] = check
    return success(check, status=201)


@bp.get("/territory-checks")
@require_roles("PlatformAdmin", "SupportAgent", "ComplianceAuditor")
def list_territory_checks(auth):
    limit, offset = parse_pagination()
    account_id = request.args.get("account_id")
    subscription_id = request.args.get("subscription_id")
    game_id = request.args.get("game_id")
    verdict = request.args.get("verdict")
    items = sorted(db.territory_checks.values(), key=lambda r: r["created_at"])
    if account_id is not None:
        items = [c for c in items if c["account_id"] == account_id]
    if subscription_id is not None:
        items = [c for c in items if c["subscription_id"] == subscription_id]
    if game_id is not None:
        items = [c for c in items if c["game_id"] == game_id]
    if verdict is not None:
        items = [c for c in items if c["verdict"] == verdict]
    window, page = paginate(items, limit, offset)
    return success(window, pagination=page)


@bp.get("/territory-checks/<cid>")
@require_roles("PlatformAdmin", "SupportAgent", "ComplianceAuditor")
def get_territory_check(cid, auth):
    check = get_or_404(db.territory_checks, cid)
    return success(check)

"""Markets: create, list, get."""
from flask import Blueprint, request

from db import db
from errors import err_duplicate, err_market_prefix_overlap, err_invalid_request
from middleware import require_roles
from paginate import parse_pagination, paginate
from response import success
from services import new_resource, get_or_404
from validate import body_json, req_string, req_string_list

bp = Blueprint("markets", __name__)

PREFIX_LEN = 3


def _validate_prefixes(prefixes):
    if not prefixes:
        raise err_invalid_request("zip_prefixes must be non-empty")
    for p in prefixes:
        if len(p) != PREFIX_LEN or not p.isdigit():
            raise err_invalid_request("zip_prefixes must be 3-digit strings")


def _check_prefix_overlap(prefixes, exclude_id=None):
    claimed = {}
    for m in db.markets.values():
        if exclude_id is not None and m["id"] == exclude_id:
            continue
        for p in m["zip_prefixes"]:
            claimed.setdefault(p, m["code"])
    for p in prefixes:
        if p in claimed:
            raise err_market_prefix_overlap()


@bp.post("/markets")
@require_roles("LeagueOps", "PlatformAdmin")
def create_market(auth):
    body = body_json()
    code = req_string(body, "code")
    name = req_string(body, "name")
    zip_prefixes = req_string_list(body, "zip_prefixes", allow_empty=False)
    home_team_codes = req_string_list(body, "home_team_codes", allow_empty=True)
    _validate_prefixes(zip_prefixes)
    for m in db.markets.values():
        if m["code"] == code:
            raise err_duplicate("Market code already exists")
    _check_prefix_overlap(zip_prefixes)

    market = new_resource()
    market.update({
        "code": code,
        "name": name,
        "zip_prefixes": zip_prefixes,
        "home_team_codes": home_team_codes,
    })
    db.markets[market["id"]] = market
    return success(market, status=201)


@bp.get("/markets")
@require_roles("PlatformAdmin", "LeagueOps", "ComplianceAuditor", "SupportAgent")
def list_markets(auth):
    limit, offset = parse_pagination()
    code = request.args.get("code")
    items = sorted(db.markets.values(), key=lambda r: r["created_at"])
    if code is not None:
        items = [m for m in items if m["code"] == code]
    window, page = paginate(items, limit, offset)
    return success(window, pagination=page)


@bp.get("/markets/<mid>")
@require_roles("PlatformAdmin", "LeagueOps", "ComplianceAuditor", "SupportAgent")
def get_market(mid, auth):
    market = get_or_404(db.markets, mid)
    return success(market)

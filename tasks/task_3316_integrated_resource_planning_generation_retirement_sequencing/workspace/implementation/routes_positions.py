"""Position routes: add (DRAFT portfolios only), soft-remove, flat reads."""

from flask import Blueprint, request

from db import store
from errors import (
    ERR_CANDIDATE_NOT_FOUND, ERR_DUPLICATE_POSITION, ERR_INVALID_REQUEST,
    ERR_NAMEPLATE_EXCEEDED, ERR_PORTFOLIO_FROZEN, raise_error,
)
from errors import ApiError
from helpers import (
    body, get_num, paginate, parse_pagination, require_fields, stamp_new, touch,
)
from middleware import require_roles
from response import success_list, success_object
from routes_candidates import get_candidate_or_404
from routes_portfolios import PORTFOLIO_READ_ROLES, get_portfolio_or_404
from serializers import position_view

bp = Blueprint("positions", __name__)

ERR_POSITION_NOT_FOUND = ("ERR_PORTFOLIO_NOT_FOUND", 404)  # no dedicated id; see note


def get_position_or_404(position_id: str, portfolio_id: str = None) -> dict:
    pos = store.positions.get(position_id)
    if pos is None or (portfolio_id is not None and pos["portfolio_id"] != portfolio_id):
        # Scaffold has no ERR_POSITION_NOT_FOUND; reuse the portfolio-family 404.
        raise_error(ERR_POSITION_NOT_FOUND, f"Position {position_id} not found")
    return pos


@bp.route("/portfolios/<portfolioId>/positions", methods=["POST"])
@require_roles("UtilityPlanner")
def add_position(user_id, role, portfolioId):
    pf = get_portfolio_or_404(portfolioId)
    payload = body()
    require_fields(payload, "candidate_id", "committed_mw")
    candidate_id = payload["candidate_id"]
    if not isinstance(candidate_id, str):
        raise_error(ERR_INVALID_REQUEST, "candidate_id must be a string")
    cand = store.candidates.get(candidate_id)
    if cand is None:
        raise_error(ERR_CANDIDATE_NOT_FOUND, f"Candidate {candidate_id} not found")
    committed = get_num(payload, "committed_mw")
    if committed <= 0:
        raise_error(ERR_INVALID_REQUEST, "committed_mw must be > 0")
    if pf["status"] != "DRAFT":
        raise_error(ERR_PORTFOLIO_FROZEN, "Portfolio is FROZEN")
    if committed > cand["nameplate_mw"]:
        raise_error(ERR_NAMEPLATE_EXCEEDED,
                    "committed_mw exceeds candidate nameplate_mw")
    for pos in store.positions.values():
        if (pos["portfolio_id"] == pf["id"] and pos["candidate_id"] == cand["id"]
                and pos.get("selected", True)):
            raise_error(ERR_DUPLICATE_POSITION,
                        "A selected position for this candidate already exists")
    pos = stamp_new({
        "portfolio_id": pf["id"],
        "candidate_id": cand["id"],
        "committed_mw": committed,
        "selected": True,
    }, with_version=False)
    store.positions[pos["id"]] = pos
    touch(pf)
    return success_object(position_view(pos), 201)


@bp.route("/portfolios/<portfolioId>/positions", methods=["GET"])
@require_roles(*PORTFOLIO_READ_ROLES)
def list_positions(user_id, role, portfolioId):
    pf = get_portfolio_or_404(portfolioId)
    limit, offset = parse_pagination()
    items = [p for p in store.positions.values() if p["portfolio_id"] == pf["id"]]
    if "selected" in request.args:
        want = request.args["selected"].lower() == "true"
        items = [p for p in items if p.get("selected", True) == want]
    page, total = paginate(items, limit, offset)
    return success_list([position_view(p) for p in page], limit, offset, total)


@bp.route("/portfolios/<portfolioId>/positions/<positionId>", methods=["DELETE"])
@require_roles("UtilityPlanner")
def remove_position(user_id, role, portfolioId, positionId):
    pf = get_portfolio_or_404(portfolioId)
    pos = get_position_or_404(positionId, portfolio_id=portfolioId)
    if pf["status"] != "DRAFT":
        raise_error(ERR_PORTFOLIO_FROZEN, "Portfolio is FROZEN")
    pos["selected"] = False
    touch(pf)
    return success_object(position_view(pos), 200)


@bp.route("/positions/<positionId>", methods=["GET"])
@require_roles(*PORTFOLIO_READ_ROLES)
def get_position_flat(user_id, role, positionId):
    pos = get_position_or_404(positionId)
    return success_object(position_view(pos), 200)


@bp.route("/positions", methods=["GET"])
@require_roles(*PORTFOLIO_READ_ROLES)
def list_positions_flat(user_id, role):
    limit, offset = parse_pagination()
    items = list(store.positions.values())
    args = request.args
    if "portfolio_id" in args:
        items = [p for p in items if p["portfolio_id"] == args["portfolio_id"]]
    if "candidate_id" in args:
        items = [p for p in items if p["candidate_id"] == args["candidate_id"]]
    page, total = paginate(items, limit, offset)
    return success_list([position_view(p) for p in page], limit, offset, total)

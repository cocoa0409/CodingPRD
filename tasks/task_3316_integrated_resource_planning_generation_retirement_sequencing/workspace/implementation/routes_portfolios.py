"""ResourcePortfolio routes."""

from flask import Blueprint, request

from db import store
from errors import (
    ERR_PLAN_NOT_DRAFT, ERR_PORTFOLIO_NOT_FOUND,
    ERR_PREFERRED_PORTFOLIO_CONFLICT, raise_error,
)
from helpers import (
    body, get_bool, get_str, paginate, parse_pagination, require_fields,
    stamp_new,
)
from middleware import require_roles
from response import success_list, success_object
from routes_plans import ALL_ROLES, get_plan_or_404
from serializers import portfolio_view

bp = Blueprint("portfolios", __name__)

PORTFOLIO_READ_ROLES = ("UtilityPlanner", "Commissioner", "Intervener", "PlatformAdmin")


def get_portfolio_or_404(portfolio_id: str, plan_id: str = None) -> dict:
    pf = store.portfolios.get(portfolio_id)
    if pf is None or (plan_id is not None and pf["plan_id"] != plan_id):
        raise_error(ERR_PORTFOLIO_NOT_FOUND, f"Portfolio {portfolio_id} not found")
    return pf


@bp.route("/plans/<planId>/portfolios", methods=["POST"])
@require_roles("UtilityPlanner")
def create_portfolio(user_id, role, planId):
    plan = get_plan_or_404(planId)
    payload = body()
    require_fields(payload, "portfolio_name")
    name = get_str(payload, "portfolio_name")
    preferred = get_bool(payload, "preferred_flag", default=False)
    if plan["status"] != "DRAFT":
        raise_error(ERR_PLAN_NOT_DRAFT, "Plan is not DRAFT")
    if preferred:
        for pf in store.portfolios.values():
            if pf["plan_id"] == plan["id"] and pf.get("preferred_flag"):
                raise_error(ERR_PREFERRED_PORTFOLIO_CONFLICT,
                            "Plan already has a preferred portfolio")
    pf = stamp_new({
        "plan_id": plan["id"],
        "portfolio_name": name,
        "preferred_flag": preferred,
        "status": "DRAFT",
    })
    store.portfolios[pf["id"]] = pf
    return success_object(portfolio_view(pf), 201)


@bp.route("/plans/<planId>/portfolios", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_plan_portfolios(user_id, role, planId):
    plan = get_plan_or_404(planId)
    limit, offset = parse_pagination()
    items = [pf for pf in store.portfolios.values() if pf["plan_id"] == plan["id"]]
    page, total = paginate(items, limit, offset)
    return success_list([portfolio_view(pf) for pf in page], limit, offset, total)


@bp.route("/plans/<planId>/portfolios/<portfolioId>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_plan_portfolio(user_id, role, planId, portfolioId):
    get_plan_or_404(planId)
    pf = get_portfolio_or_404(portfolioId, plan_id=planId)
    return success_object(portfolio_view(pf), 200)


@bp.route("/portfolios/<portfolioId>", methods=["GET"])
@require_roles(*PORTFOLIO_READ_ROLES)
def get_portfolio_flat(user_id, role, portfolioId):
    pf = get_portfolio_or_404(portfolioId)
    return success_object(portfolio_view(pf), 200)


@bp.route("/portfolios", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_portfolios(user_id, role):
    limit, offset = parse_pagination()
    items = list(store.portfolios.values())
    if "plan_id" in request.args:
        items = [pf for pf in items if pf["plan_id"] == request.args["plan_id"]]
    page, total = paginate(items, limit, offset)
    return success_list([portfolio_view(pf) for pf in page], limit, offset, total)

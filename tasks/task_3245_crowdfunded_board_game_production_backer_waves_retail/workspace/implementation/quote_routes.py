"""ManufacturingQuote routes."""
from flask import Blueprint, request

from db import db
from errors import (err_not_found, err_invalid_state, err_invalid_request,
                    err_unknown_action, ApiError)
from middleware import require_auth, ANY_ROLE
from response import success_obj
from routes_common import stamp_new, touch, serialize, paginate
from services import (recompute_quote_provisional, quote_units_final,
                      tier_price)
from util import body_of, req_str

bp = Blueprint("quotes", __name__)


def _validate_tier_breaks(tier_breaks):
    if not isinstance(tier_breaks, list) or not tier_breaks:
        raise err_invalid_request("tier_breaks must be a non-empty array")
    prev = None
    for tb in tier_breaks:
        if not isinstance(tb, dict):
            raise err_invalid_request("tier_breaks entries must be objects")
        mu = tb.get("min_units")
        up = tb.get("unit_price_cents")
        if isinstance(mu, bool) or not isinstance(mu, int) or mu <= 0:
            raise err_invalid_request("min_units must be a positive integer")
        if isinstance(up, bool) or not isinstance(up, int):
            raise err_invalid_request("unit_price_cents must be an integer")
        if prev is not None and mu <= prev:
            raise err_invalid_request("tier_breaks must be sorted ascending by min_units")
        prev = mu


@bp.route("/manufacturing-quotes", methods=["POST"])
def create_quote():
    require_auth({"FactoryCoordinator"})
    data = body_of(request)
    campaign_id = data.get("campaign_id")
    if not isinstance(campaign_id, str):
        raise err_invalid_request("campaign_id is required")
    campaign = db.campaigns.get(campaign_id)
    if not campaign:
        raise err_not_found("campaign not found")
    factory_name = req_str(data, "factory_name")
    tier_breaks = data.get("tier_breaks")
    _validate_tier_breaks(tier_breaks)

    quote = {
        "campaign_id": campaign_id,
        "factory_name": factory_name,
        "tier_breaks": [{"min_units": t["min_units"], "unit_price_cents": t["unit_price_cents"]} for t in tier_breaks],
        "provisional_units": None,
        "provisional_unit_price_cents": None,
        "final_units": None,
        "final_unit_price_cents": None,
        "status": "PROVISIONAL",
    }
    stamp_new(quote)
    recompute_quote_provisional(quote)
    db.quotes[quote["id"]] = quote
    touch(campaign)
    return success_obj(serialize(quote), 201)


@bp.route("/manufacturing-quotes/<qid>", methods=["GET"])
def get_quote(qid):
    require_auth(ANY_ROLE)
    q = db.quotes.get(qid)
    if not q:
        raise err_not_found("quote not found")
    return success_obj(serialize(q))


@bp.route("/manufacturing-quotes", methods=["GET"])
def list_quotes():
    require_auth(ANY_ROLE)
    items = list(db.quotes.values())
    args = request.args
    if args.get("campaign_id"):
        items = [q for q in items if q["campaign_id"] == args["campaign_id"]]
    if args.get("status"):
        items = [q for q in items if q["status"] == args["status"]]
    return paginate(items)


@bp.route("/manufacturing-quotes/<qid>/transition", methods=["POST"])
def quote_transition(qid):
    require_auth({"FactoryCoordinator"})
    q = db.quotes.get(qid)
    if not q:
        raise err_not_found("quote not found")
    data = body_of(request)
    action = data.get("action")
    if not isinstance(action, str):
        raise err_invalid_request("action is required")
    if action not in ("submit", "revise", "finalize"):
        raise err_unknown_action(f"unknown action {action}")
    campaign = db.campaigns.get(q["campaign_id"])

    if action == "submit":
        if q["status"] != "PROVISIONAL":
            raise err_invalid_state("submit requires PROVISIONAL")
        if campaign["status"] != "CLOSED_SUCCESS":
            raise ApiError("ERR_CAMPAIGN_NOT_CLOSED", 409, "campaign not closed successfully")
        q["status"] = "SUBMITTED"
        touch(q)

    elif action == "revise":
        if q["status"] != "SUBMITTED":
            raise err_invalid_state("revise requires SUBMITTED")
        for r in db.production_runs.values():
            if r["quote_id"] == qid and r["status"] in ("LOCKED", "IN_PRODUCTION", "SHIPPED"):
                raise err_invalid_state("run referencing quote is LOCKED or later")
        q["status"] = "PROVISIONAL"
        recompute_quote_provisional(q)
        touch(q)

    elif action == "finalize":
        if q["status"] != "SUBMITTED":
            raise err_invalid_state("finalize requires SUBMITTED")
        for sib in db.quotes.values():
            if sib["campaign_id"] == q["campaign_id"] and sib["id"] != qid and sib["status"] == "FINAL":
                raise ApiError("ERR_QUOTE_ALREADY_FINAL", 409, "sibling quote already FINAL")
        units = quote_units_final(q["campaign_id"])
        q["final_units"] = units
        q["final_unit_price_cents"] = tier_price(q["tier_breaks"], units)
        q["status"] = "FINAL"
        touch(q)
        for sib in db.quotes.values():
            if sib["campaign_id"] == q["campaign_id"] and sib["id"] != qid and sib["status"] in ("PROVISIONAL", "SUBMITTED"):
                sib["status"] = "SUPERSEDED"
                touch(sib)
        if campaign:
            touch(campaign)

    return success_obj(serialize(q))

"""Alumina supply agreements and internal transfer pricing (PRD 3.4)."""
from flask import Blueprint

from auth import require_roles
from constants import PRICING_MODELS
from db import STORE, new_id, stamp_new
from envelope import ok_object
from errors import raise_err
from serializers import agreement_json
from util import D, as_enum, as_number, as_str, get_body, req

bp = Blueprint("alumina", __name__, url_prefix="/smelter-ops")


@bp.post("/alumina-agreements")
@require_roles("Controller")
def create_agreement():
    body = get_body()
    smelter_id = as_str(req(body, "smelter_id"), "smelter_id")
    if STORE["smelters"].get(smelter_id) is None:
        raise_err("ERR_NOT_FOUND", "Smelter not found.")
    refinery = as_str(req(body, "refinery_name"), "refinery_name")
    pricing_model = as_enum(req(body, "pricing_model"), "pricing_model", PRICING_MODELS)
    monthly_volume = as_number(
        req(body, "monthly_volume_tonnes"), "monthly_volume_tonnes"
    )
    if monthly_volume <= 0:
        raise_err("ERR_INVALID_REQUEST", "monthly_volume_tonnes must be > 0.")
    base = body.get("base_cost_per_tonne")
    markup = body.get("markup_pct")
    discount = body.get("market_discount_pct")
    if pricing_model == "COST_PLUS":
        base = as_number(req(body, "base_cost_per_tonne"), "base_cost_per_tonne")
        markup = as_number(req(body, "markup_pct"), "markup_pct")
        if markup < 0:
            raise_err("ERR_INVALID_REQUEST", "markup_pct must be >= 0.")
        if discount is not None:
            raise_err(
                "ERR_INVALID_REQUEST",
                "market_discount_pct is forbidden for COST_PLUS.",
            )
    else:  # MARKET_LINKED
        discount = as_number(
            req(body, "market_discount_pct"), "market_discount_pct"
        )
        if not (D(discount) >= 0 and D(discount) < 1):
            raise_err(
                "ERR_INVALID_REQUEST", "market_discount_pct must be in [0, 1)."
            )
        if base is not None or markup is not None:
            raise_err(
                "ERR_INVALID_REQUEST",
                "base_cost_per_tonne and markup_pct are forbidden for MARKET_LINKED.",
            )
        base = None
        markup = None
    rec = stamp_new(
        {
            "id": new_id(),
            "smelter_id": smelter_id,
            "refinery_name": refinery,
            "pricing_model": pricing_model,
            "base_cost_per_tonne": base,
            "markup_pct": markup,
            "market_discount_pct": discount,
            "monthly_volume_tonnes": monthly_volume,
        }
    )
    STORE["alumina_agreements"][rec["id"]] = rec
    return ok_object(agreement_json(rec), 201)

"""Production plans: monthly product-mix publication (PRD 3.9)."""
from flask import Blueprint

from auth import require_roles
from constants import (
    BILLET_CONVERSION_PER_T,
    GLOBAL_REGION,
    PRODUCT_FORMS,
    SLAB_CONVERSION_PER_T,
    VA_PREMIUM_TIER_HIGH,
    VA_PREMIUM_TIER_LOW,
    VA_PREMIUM_TIER_MID,
    VA_SHARE_TIER1_MAX,
    VA_SHARE_TIER2_MAX,
    VALUE_ADDED_CONVERSION_PER_T,
)
from db import STORE, bump, logical_clock, new_id, stamp_new
from envelope import ok_object
from errors import raise_err
from serializers import production_plan_json
from services.core import monthly_capacity
from services.pricing import latest_observation
from util import D, as_enum, as_number, as_str, get_body, is_int, parse_month, req, round2_dec

bp = Blueprint("plans", __name__, url_prefix="/smelter-ops")

_CONVERSION = {
    "BILLET": BILLET_CONVERSION_PER_T,
    "SLAB": SLAB_CONVERSION_PER_T,
    "VALUE_ADDED": VALUE_ADDED_CONVERSION_PER_T,
}


@bp.post("/production-plans")
@require_roles("Controller")
def create_production_plan():
    body = get_body()
    smelter_id = as_str(req(body, "smelter_id"), "smelter_id")
    smelter = STORE["smelters"].get(smelter_id)
    if smelter is None:
        raise_err("ERR_NOT_FOUND", "Smelter not found.")
    expected = body.get("expected_smelter_version")
    if expected is None or not is_int(expected):
        raise_err(
            "ERR_INVALID_REQUEST",
            "expected_smelter_version is required and must be an integer.",
        )
    if expected != smelter["version"]:
        raise_err(
            "ERR_STALE_VERSION",
            "expected_smelter_version does not match the smelter's current version.",
        )
    period_month = req(body, "period_month")
    year, month = parse_month(period_month, "period_month")
    now = logical_clock()
    if (year, month) < (now.year, now.month):
        raise_err(
            "ERR_INVALID_REQUEST",
            "period_month must not be earlier than the current month.",
        )
    allocations = req(body, "allocations")
    if not isinstance(allocations, list):
        raise_err("ERR_INVALID_REQUEST", "allocations must be an array.")
    seen = set()
    for item in allocations:
        if not isinstance(item, dict):
            raise_err("ERR_INVALID_REQUEST", "Each allocation must be an object.")
        form = as_enum(req(item, "product_form"), "product_form", PRODUCT_FORMS)
        if form in seen:
            raise_err(
                "ERR_INVALID_REQUEST",
                "allocations must not contain duplicate product_form entries.",
            )
        seen.add(form)
        tonnes = as_number(req(item, "tonnes"), "tonnes")
        if tonnes <= 0:
            raise_err("ERR_INVALID_REQUEST", "allocation tonnes must be > 0.")
    if seen != set(PRODUCT_FORMS):
        raise_err(
            "ERR_INVALID_REQUEST",
            "allocations must cover exactly BILLET, SLAB, and VALUE_ADDED.",
        )
    total = D(0)
    for item in allocations:
        total += D(item["tonnes"])
    if total > monthly_capacity(smelter):
        raise_err(
            "ERR_PRODUCT_MIX_OVER_CAPACITY",
            "Allocation sum exceeds the smelter's monthly capacity basis.",
        )
    lme_obs = latest_observation("ALUMINUM_LME", GLOBAL_REGION)
    premium_obs = latest_observation("REGIONAL_PREMIUM", smelter["region_code"])
    if lme_obs is None or premium_obs is None:
        raise_err(
            "ERR_NO_PRICE_OBSERVATION",
            "Latest LME and regional premium observations are required.",
        )
    lme = D(lme_obs["price_usd"])
    premium = D(premium_obs["price_usd"])
    # The value-added share is computed from the whole basket before any line.
    va_tonnes = D(0)
    for item in allocations:
        if item["product_form"] == "VALUE_ADDED":
            va_tonnes += D(item["tonnes"])
    va_share = va_tonnes / total
    if va_share < VA_SHARE_TIER1_MAX:
        va_premium = VA_PREMIUM_TIER_LOW
    elif va_share <= VA_SHARE_TIER2_MAX:
        va_premium = VA_PREMIUM_TIER_MID
    else:
        va_premium = VA_PREMIUM_TIER_HIGH
    total_margin = D(0)
    for item in allocations:
        form = item["product_form"]
        margin_t = lme + premium - _CONVERSION[form]
        if form == "VALUE_ADDED":
            margin_t += va_premium
        # Pinned order: round the per-tonne margin first, then multiply, then sum.
        total_margin += round2_dec(margin_t) * D(item["tonnes"])
    for prior in STORE["production_plans"].values():
        if (
            prior["smelter_id"] == smelter_id
            and prior["period_month"] == period_month
            and prior["status"] == "PUBLISHED"
        ):
            prior["status"] = "SUPERSEDED"
            bump(prior)
    bump(smelter)
    rec = stamp_new(
        {
            "id": new_id(),
            "smelter_id": smelter_id,
            "period_month": period_month,
            "allocations": allocations,
            "status": "PUBLISHED",
            "total_tonnes": total,
            "total_margin_usd": total_margin,
        }
    )
    STORE["production_plans"][rec["id"]] = rec
    return ok_object(production_plan_json(rec), 201)

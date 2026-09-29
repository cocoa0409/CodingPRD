"""Bringing units to market: listing, pricing and the markdown cadence
(PRD 3.6)."""

from flask import Blueprint

import access
import constants as C
import serialize
import services
import store
import validators as V
from envelope import list_response, object_response, paginate
from errors import ApiError

bp = Blueprint("market", __name__)


@bp.get("/resale-units/<unit_id>")
def get_resale_unit(unit_id):
    user_id, role = V.guard(
        "ProgramAdmin", "MerchandisingManager", "RefurbTechnician", "Customer"
    )
    unit = store.require("resale_units", unit_id)
    access.require_owner(role, user_id, access.unit_customer_id(unit))
    return object_response(serialize.out(unit))


@bp.get("/resale-units")
def list_resale_units():
    user_id, role = V.guard(
        "ProgramAdmin", "MerchandisingManager", "RefurbTechnician", "Customer"
    )
    limit, offset = V.pagination()
    lifecycle_state = V.enum_query("lifecycle_state", C.LIFECYCLE_STATES)
    accounting_state = V.enum_query("accounting_state", C.ACCOUNTING_STATES)
    product_category = V.enum_query("product_category", C.PRODUCT_CATEGORIES)
    trade_in_id = V.id_query("trade_in_id")
    replacement_for_unit_id = V.id_query("replacement_for_unit_id")
    listed_channel_id = V.id_query("listed_channel_id")
    if trade_in_id is not None:
        trade_in = store.require("trade_ins", trade_in_id)
        access.require_owner(role, user_id, trade_in["customer_id"])
    if replacement_for_unit_id is not None:
        store.require("resale_units", replacement_for_unit_id)
    if listed_channel_id is not None:
        store.require("channels", listed_channel_id)

    rows = store.rows("resale_units")
    if role == "Customer":
        rows = [u for u in rows if access.unit_customer_id(u) == user_id]
    if trade_in_id is not None:
        rows = [u for u in rows if u["trade_in_id"] == trade_in_id]
    if replacement_for_unit_id is not None:
        rows = [u for u in rows if u.get("replacement_for_unit_id") == replacement_for_unit_id]
    if listed_channel_id is not None:
        rows = [u for u in rows if u.get("listed_channel_id") == listed_channel_id]
    if lifecycle_state is not None:
        rows = [u for u in rows if u["lifecycle_state"] == lifecycle_state]
    if accounting_state is not None:
        rows = [u for u in rows if u["accounting_state"] == accounting_state]
    if product_category is not None:
        rows = [u for u in rows if u["product_category"] == product_category]
    page, total = paginate(store.ordered(rows), limit, offset)
    return list_response(serialize.out_list(page), limit, offset, total)


@bp.post("/resale-units/<unit_id>/list")
def list_unit_for_sale(unit_id):
    V.guard("MerchandisingManager")
    payload = V.body()
    channel_id = V.id_field(payload, "channel_id")
    unit = store.require("resale_units", unit_id)
    channel = store.require("channels", channel_id)

    if unit["lifecycle_state"] not in ("READY", "RETURNED"):
        raise ApiError("ERR_UNIT_NOT_READY_FOR_LISTING")
    if channel["status"] != "ACTIVE":
        raise ApiError("ERR_CHANNEL_NOT_ACTIVE")
    grade_policy = services.grade_policy_or_error(
        unit["product_category"], unit["condition_grade"]
    )
    if channel["allowed_assortment"] not in ("RESALE_ONLY", "BOTH"):
        raise ApiError("ERR_ASSORTMENT_NOT_PERMITTED")

    price = services.list_price(unit, channel, grade_policy)
    unit["listed_channel_id"] = channel["id"]
    unit["list_price_minor"] = price
    unit["current_price_minor"] = price
    unit["markdown_step_count"] = 0
    unit["listed_at"] = store.now()
    unit["lifecycle_state"] = "LISTED"
    store.touch(unit)
    return object_response(serialize.out(unit))


@bp.post("/markdown-campaigns")
def create_markdown_campaign():
    V.guard("MerchandisingManager", "ProgramAdmin")
    payload = V.body()
    channel_id = V.id_field(payload, "channel_id")
    product_category = V.enum_field(payload, "product_category", C.PRODUCT_CATEGORIES)
    window_start_at = V.ts_field(payload, "window_start_at")
    window_end_at = V.ts_field(payload, "window_end_at")
    cadence_days = V.int_field(payload, "cadence_days", minimum=1)
    step_bp = V.int_field(payload, "step_bp", minimum=1, maximum=9999)
    floor_pct_bp = V.int_field(payload, "floor_pct_bp", minimum=1, maximum=10000)
    if window_end_at <= window_start_at:
        raise ApiError("ERR_INVALID_TIME_WINDOW")
    if not services.whole_days_apart(window_start_at, window_end_at):
        raise ApiError("ERR_INVALID_TIME_WINDOW")

    channel = store.require("channels", channel_id)
    if channel["status"] != "ACTIVE":
        raise ApiError("ERR_CHANNEL_NOT_ACTIVE")

    live = [
        c
        for c in store.rows("markdown_campaigns")
        if c["channel_id"] == channel["id"] and c["status"] in C.CAMPAIGN_NON_TERMINAL
    ]
    overlapping = [
        c
        for c in live
        if services.half_open_overlap(
            window_start_at, window_end_at, c["window_start_at"], c["window_end_at"]
        )
    ]
    for other in overlapping:
        if other["product_category"] == product_category:
            raise ApiError("ERR_CAMPAIGN_CATEGORY_OVERLAP")
    if len(overlapping) >= C.MAX_CONCURRENT_CAMPAIGNS_PER_CHANNEL:
        raise ApiError("ERR_CAMPAIGN_CAPACITY_EXCEEDED")

    row = store.create(
        "markdown_campaigns",
        {
            "channel_id": channel["id"],
            "product_category": product_category,
            "window_start_at": window_start_at,
            "window_end_at": window_end_at,
            "cadence_days": cadence_days,
            "step_bp": step_bp,
            "floor_pct_bp": floor_pct_bp,
            "status": "SCHEDULED",
            "run_count": 0,
            "last_run_at": None,
        },
    )
    return object_response(serialize.out(row), 201)


@bp.get("/markdown-campaigns/<campaign_id>")
def get_markdown_campaign(campaign_id):
    V.guard("ProgramAdmin", "MerchandisingManager")
    return object_response(serialize.out(store.require("markdown_campaigns", campaign_id)))


@bp.post("/markdown-campaigns/<campaign_id>/cadence-runs")
def run_cadence(campaign_id):
    V.guard("MerchandisingManager", "ProgramAdmin")
    campaign = store.require("markdown_campaigns", campaign_id)
    now = store.now()
    if campaign["status"] == "CLOSED" or now < campaign["window_start_at"]:
        raise ApiError("ERR_CAMPAIGN_NOT_RUNNABLE")

    if now >= campaign["window_end_at"]:
        counters = {
            "evaluated_unit_count": 0,
            "marked_down_unit_count": 0,
            "skipped_at_floor_count": 0,
            "written_down_unit_count": 0,
            "total_markdown_minor": 0,
        }
        campaign["status"] = "CLOSED"
    else:
        counters = services.run_markdown_step(campaign)
        campaign["status"] = "ACTIVE"

    campaign["run_count"] += 1
    campaign["last_run_at"] = now
    store.touch(campaign)
    result = {"run_sequence_no": campaign["run_count"]}
    result.update(counters)
    return object_response(result)

"""Unit mix, placement and closeout (PRD 3.6, 3.8)."""

from flask import Blueprint

from auth import current_user_id, require_roles
from constants import (
    CATEGORY_SEPARATION_DAYS,
    CHANNEL_PLATFORM,
    COMMITTED_BUY_STATUSES,
    DAYPARTS,
    HOLDING_UNIT_STATUSES,
    PLATFORMS,
)
from errors import ApiError
from lookup import get
from response import created, ok
from routes.common import listing, read_one
from serializers import serialize
from services import cascades, derive
from store import store
from timeutil import add_days, sub_days
from validation import body, require_window

bp = Blueprint("buys", __name__)

TERMINAL = ("CLOSED", "CANCELLED")


def guard_terminal(buy):
    if buy["buy_status"] in TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL")


@bp.post("/buys/<buy_id>/units")
@require_roles("AgencyBuyer")
def create_unit(buy_id):
    data = body()
    forecast_id = data.string("forecast_id")
    daypart = data.enum("daypart", DAYPARTS)
    program = data.string("program", max_len=120)
    platform = data.enum("platform", PLATFORMS)
    units = data.integer("units", minimum=1)
    unit_rate_cents = data.integer("unit_rate_cents", minimum=1)
    projected_impressions = data.integer("projected_impressions", minimum=1)
    air_window_start = data.timestamp("air_window_start")
    air_window_end = data.timestamp("air_window_end")
    exclusive = data.boolean("exclusive", required=False, default=False)
    require_window(air_window_start, air_window_end, "air_window")

    buy = get("buys", buy_id)
    forecast = get("forecasts", forecast_id)

    guard_terminal(buy)
    if buy["buy_status"] != "PENDING_PLACEMENT":
        raise ApiError("ERR_BUY_NOT_IN_EXPECTED_STATE")
    if forecast["status"] != "PUBLISHED":
        raise ApiError("ERR_FORECAST_NOT_PUBLISHED")

    # The line is a claim on specific inventory, not a description of it.
    if (
        forecast["seller_id"] != buy["seller_id"]
        or forecast["market"] != buy["market"]
        or forecast["platform"] != CHANNEL_PLATFORM[buy["channel"]]
        or forecast["window_start"] < buy["flight_start"]
        or forecast["window_end"] > buy["flight_end"]
        or forecast["daypart"] != daypart
        or forecast["program"] != program
        or forecast["platform"] != platform
    ):
        raise ApiError("ERR_UNIT_FORECAST_MISMATCH")

    if forecast["exclusivity_mode"] == "EXCLUSIVE":
        for other in derive.units_of_forecast(forecast["id"]):
            if other["buy_id"] == buy["id"]:
                continue
            if other["status"] not in HOLDING_UNIT_STATUSES:
                continue
            # Half-open windows: touching at an instant is not an overlap.
            if (
                air_window_start < other["air_window_end"]
                and other["air_window_start"] < air_window_end
            ):
                raise ApiError("ERR_EXCLUSIVE_AVAIL_CONFLICT")

    if projected_impressions > derive.available_impressions(forecast):
        raise ApiError("ERR_FORECAST_AVAIL_EXCEEDED")

    money = derive.line_money(units, unit_rate_cents, buy["commission_rate"])
    unit = store.new(
        "units",
        dict(
            money,
            buy_id=buy["id"],
            forecast_id=forecast["id"],
            make_good_id=None,
            daypart=daypart,
            program=program,
            platform=platform,
            units=units,
            unit_rate_cents=unit_rate_cents,
            projected_impressions=projected_impressions,
            actual_impressions=0,
            air_window_start=air_window_start,
            air_window_end=air_window_end,
            exclusive=exclusive,
            status="SCHEDULED",
        ),
    )
    cascades.sync_forecast(forecast)
    store.touch(buy)
    return created(serialize("units", unit))


@bp.post("/buys/<buy_id>/place")
@require_roles("AgencyBuyer")
def place_buy(buy_id):
    data = body()
    expected_campaign_version = data.integer("expected_campaign_version", minimum=0)

    buy = get("buys", buy_id)
    campaign = store.campaigns.get(buy["campaign_id"])
    if campaign is None or expected_campaign_version != campaign["version"]:
        raise ApiError("ERR_STALE_CAMPAIGN_VERSION")
    guard_terminal(buy)
    if buy["buy_status"] != "PENDING_PLACEMENT":
        raise ApiError("ERR_BUY_NOT_IN_EXPECTED_STATE")
    if campaign["plan_status"] != "APPROVED":
        raise ApiError("ERR_CAMPAIGN_PLAN_NOT_APPROVED")

    _guard_category_separation(buy, campaign)

    coverage = sum(
        u["projected_impressions"]
        for u in derive.units_of_buy(buy["id"])
        if u["status"] == "SCHEDULED"
    )
    if coverage < buy["guaranteed_impressions"]:
        raise ApiError("ERR_UNIT_COVERAGE_SHORT")

    committed = derive.campaign_view(campaign)["committed_gross_cents"]
    if committed + buy["gross_cost_cents"] > campaign["total_budget_cents"]:
        raise ApiError("ERR_CAMPAIGN_BUDGET_EXCEEDED")

    buy["buy_status"] = "PLACED"
    buy["placed_by_user_id"] = current_user_id()
    store.touch(buy)
    # The four-link overcommitment chain of PRD 3.6.
    cascades.commitment_chain(buy)
    return ok(serialize("buys", buy))


def _guard_category_separation(buy, campaign):
    """Competitive separation: rival brands are kept apart on one seller."""
    advertiser = store.advertisers.get(campaign["advertiser_id"])
    if advertiser is None:
        return
    for other in store.buys.values():
        if other["id"] == buy["id"]:
            continue
        if other["seller_id"] != buy["seller_id"]:
            continue
        if other["buy_status"] not in COMMITTED_BUY_STATUSES:
            continue
        other_campaign = store.campaigns.get(other["campaign_id"])
        if other_campaign is None:
            continue
        if other_campaign["advertiser_id"] == campaign["advertiser_id"]:
            continue
        rival = store.advertisers.get(other_campaign["advertiser_id"])
        if rival is None or rival["category_code"] != advertiser["category_code"]:
            continue
        buffered_start = sub_days(other["flight_start"], CATEGORY_SEPARATION_DAYS)
        buffered_end = add_days(other["flight_end"], CATEGORY_SEPARATION_DAYS)
        # Both intervals are closed, so touching the buffer edge is a conflict.
        if buy["flight_start"] <= buffered_end and buffered_start <= buy["flight_end"]:
            raise ApiError("ERR_CATEGORY_SEPARATION_CONFLICT")


@bp.post("/buys/<buy_id>/close")
@require_roles("AgencyController")
def close_buy(buy_id):
    buy = get("buys", buy_id)
    guard_terminal(buy)
    if buy["buy_status"] != "IN_FLIGHT":
        raise ApiError("ERR_BUY_NOT_IN_EXPECTED_STATE")
    if buy["stewardship_status"] not in ("WITHIN_TOLERANCE", "MADE_GOOD"):
        raise ApiError("ERR_BUY_NOT_IN_EXPECTED_STATE")
    for report in derive.reports_of_buy(buy["id"]):
        if report["status"] == "SUBMITTED":
            raise ApiError("ERR_BUY_NOT_IN_EXPECTED_STATE")

    buy["buy_status"] = "COMPLETED"
    store.touch(buy)
    return ok(serialize("buys", buy))


@bp.get("/buys/<buy_id>")
def get_buy(buy_id):
    return read_one("buys", buy_id)


@bp.get("/buys")
def list_buys():
    return listing(
        "buys",
        {
            "campaign_id": "campaign_id",
            "seller_id": "seller_id",
            "negotiation_id": "negotiation_id",
            "channel_allocation_id": "channel_allocation_id",
            "buy_status": "buy_status",
        },
    )

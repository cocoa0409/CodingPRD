"""The bounded alternating negotiation and the buy it freezes (PRD 3.5)."""

from decimal import Decimal

from flask import Blueprint

from auth import require_roles, require_seller_owner
from constants import (
    CANCEL_WINDOW_1_DAYS,
    CANCEL_WINDOW_2_DAYS,
    CHANNELS,
    MAKE_GOOD_PROVISIONS,
    MARKETS,
    MAX_NEGOTIATION_ROUNDS,
    OPTION_WINDOW_DAYS,
)
from errors import ApiError
from lookup import get
from response import created, ok
from routes.common import listing, read_one
from serializers import serialize
from services import derive
from store import store
from timeutil import sub_days
from validation import body

bp = Blueprint("negotiations", __name__)

TERMINAL = ("ACCEPTED", "WITHDRAWN")


def _guard_terminal(negotiation):
    if negotiation["status"] in TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL")


def _guard_round_cap(negotiation):
    if negotiation["round_number"] + 1 > MAX_NEGOTIATION_ROUNDS:
        raise ApiError("ERR_NEGOTIATION_ROUND_CAP_REACHED")


@bp.post("/negotiations")
@require_roles("AgencyBuyer")
def create_negotiation():
    data = body()
    campaign_id = data.string("campaign_id")
    seller_id = data.string("seller_id")
    channel_allocation_id = data.string("channel_allocation_id")
    market = data.enum("market", MARKETS)
    channel = data.enum("channel", CHANNELS)
    requested_impressions = data.integer("requested_impressions", minimum=1)
    opening_cpm_cents = data.integer("opening_cpm_cents", minimum=1)
    guarantee_pct = data.decimal(
        "guarantee_pct", required=False, exclusive_min=True, default=Decimal("100.00")
    )
    make_good_provision = data.enum(
        "make_good_provision",
        MAKE_GOOD_PROVISIONS,
        required=False,
        default="MAKE_GOOD_UNITS",
    )
    option_pct_ceiling = data.decimal(
        "option_pct_ceiling", required=False, default=Decimal("25.00")
    )

    campaign = get("campaigns", campaign_id)
    seller = get("sellers", seller_id)
    allocation = get("allocations", channel_allocation_id)

    if allocation["campaign_id"] != campaign["id"] or allocation["channel"] != channel:
        raise ApiError("ERR_ALLOCATION_CAMPAIGN_MISMATCH")

    record = store.new(
        "negotiations",
        {
            "campaign_id": campaign["id"],
            "seller_id": seller["id"],
            "channel_allocation_id": allocation["id"],
            "market": market,
            "channel": channel,
            "requested_impressions": requested_impressions,
            "opening_cpm_cents": opening_cpm_cents,
            "guarantee_pct": guarantee_pct,
            "make_good_provision": make_good_provision,
            "option_pct_ceiling": option_pct_ceiling,
            "current_cpm_cents": opening_cpm_cents,
            "current_impressions": requested_impressions,
            "round_number": 1,
            "last_offer_actor": "AGENCY",
            "status": "AGENCY_OFFER",
            "accepted_cpm_cents": None,
            "accepted_impressions": None,
            "withdraw_reason": None,
        },
    )
    return created(serialize("negotiations", record))


@bp.post("/negotiations/<negotiation_id>/counter")
@require_roles("SellerRep")
def counter_negotiation(negotiation_id):
    data = body()
    counter_cpm_cents = data.integer("counter_cpm_cents", minimum=1)
    counter_impressions = data.integer("counter_impressions", minimum=1)
    expected_version = data.integer("expected_negotiation_version", minimum=0)

    negotiation = get("negotiations", negotiation_id)
    require_seller_owner(negotiation["seller_id"])
    if expected_version != negotiation["version"]:
        raise ApiError("ERR_STALE_NEGOTIATION_VERSION")
    _guard_terminal(negotiation)
    if negotiation["status"] != "AGENCY_OFFER":
        raise ApiError("ERR_NEGOTIATION_NOT_IN_EXPECTED_STATE")
    _guard_round_cap(negotiation)

    negotiation["current_cpm_cents"] = counter_cpm_cents
    negotiation["current_impressions"] = counter_impressions
    negotiation["last_offer_actor"] = "SELLER"
    negotiation["round_number"] += 1
    negotiation["status"] = "SELLER_COUNTER"
    store.touch(negotiation)
    return ok(serialize("negotiations", negotiation))


@bp.post("/negotiations/<negotiation_id>/revise")
@require_roles("AgencyBuyer")
def revise_negotiation(negotiation_id):
    data = body()
    offer_cpm_cents = data.integer("offer_cpm_cents", minimum=1)
    offer_impressions = data.integer("offer_impressions", minimum=1)

    negotiation = get("negotiations", negotiation_id)
    _guard_terminal(negotiation)
    if negotiation["status"] != "SELLER_COUNTER":
        raise ApiError("ERR_NEGOTIATION_NOT_IN_EXPECTED_STATE")
    _guard_round_cap(negotiation)

    negotiation["current_cpm_cents"] = offer_cpm_cents
    negotiation["current_impressions"] = offer_impressions
    negotiation["last_offer_actor"] = "AGENCY"
    negotiation["round_number"] += 1
    negotiation["status"] = "AGENCY_OFFER"
    store.touch(negotiation)
    return ok(serialize("negotiations", negotiation))


@bp.post("/negotiations/<negotiation_id>/withdraw")
@require_roles("AgencyBuyer")
def withdraw_negotiation(negotiation_id):
    data = body(required=False)
    withdraw_reason = data.string("withdraw_reason", required=False)

    negotiation = get("negotiations", negotiation_id)
    _guard_terminal(negotiation)
    if negotiation["status"] not in ("AGENCY_OFFER", "SELLER_COUNTER"):
        raise ApiError("ERR_NEGOTIATION_NOT_IN_EXPECTED_STATE")

    negotiation["status"] = "WITHDRAWN"
    if withdraw_reason is not None:
        negotiation["withdraw_reason"] = withdraw_reason
    store.touch(negotiation)
    return ok(serialize("negotiations", negotiation))


@bp.post("/negotiations/<negotiation_id>/accept")
@require_roles("AgencyBuyer")
def accept_negotiation(negotiation_id):
    negotiation = get("negotiations", negotiation_id)
    _guard_terminal(negotiation)
    if negotiation["status"] != "SELLER_COUNTER":
        raise ApiError("ERR_NEGOTIATION_NOT_IN_EXPECTED_STATE")
    campaign = store.campaigns.get(negotiation["campaign_id"])
    if campaign is None or campaign["plan_status"] != "APPROVED":
        raise ApiError("ERR_CAMPAIGN_PLAN_NOT_APPROVED")
    advertiser = store.advertisers.get(campaign["advertiser_id"])
    if advertiser is not None and advertiser["credit_status"] == "HOLD":
        raise ApiError("ERR_ADVERTISER_CREDIT_HOLD")

    negotiation["status"] = "ACCEPTED"
    negotiation["accepted_cpm_cents"] = negotiation["current_cpm_cents"]
    negotiation["accepted_impressions"] = negotiation["current_impressions"]
    store.touch(negotiation)

    flight_start = campaign["flight_start"]
    buy = store.new(
        "buys",
        {
            "campaign_id": campaign["id"],
            "seller_id": negotiation["seller_id"],
            "negotiation_id": negotiation["id"],
            "channel_allocation_id": negotiation["channel_allocation_id"],
            "market": negotiation["market"],
            "channel": negotiation["channel"],
            "guaranteed_impressions": negotiation["accepted_impressions"],
            "agreed_cpm_cents": negotiation["accepted_cpm_cents"],
            "made_good_impressions": 0,
            "waived_impressions": 0,
            "buy_status": "PENDING_PLACEMENT",
            "stewardship_status": "NOT_STARTED",
            "settlement_status": "UNBILLED",
            "flight_start": flight_start,
            "flight_end": campaign["flight_end"],
            "option_window_close": sub_days(flight_start, OPTION_WINDOW_DAYS),
            "cancel_window_1_close": sub_days(flight_start, CANCEL_WINDOW_1_DAYS),
            "cancel_window_2_close": sub_days(flight_start, CANCEL_WINDOW_2_DAYS),
            "option_pct_ceiling": negotiation["option_pct_ceiling"],
            "make_good_provision": negotiation["make_good_provision"],
            "placed_by_user_id": None,
        },
    )
    derive.apply_cost_stack(buy)
    return created(serialize("buys", buy))


@bp.get("/negotiations/<negotiation_id>")
def get_negotiation(negotiation_id):
    return read_one("negotiations", negotiation_id)


@bp.get("/negotiations")
def list_negotiations():
    return listing(
        "negotiations",
        {
            "campaign_id": "campaign_id",
            "seller_id": "seller_id",
            "channel_allocation_id": "channel_allocation_id",
            "status": "status",
        },
    )

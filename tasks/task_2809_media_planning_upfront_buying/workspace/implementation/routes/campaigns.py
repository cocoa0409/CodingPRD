"""Campaign planning, the approval cycle and the funding axis (PRD 3.2, 3.3)."""

import re
from decimal import Decimal

from flask import Blueprint

from auth import require_advertiser_owner, require_roles
from errors import ApiError, bad_request
from lookup import get
from response import created, ok
from routes.common import listing, read_one
from serializers import serialize
from services import cascades, derive
from store import store
from validation import body, require_window

bp = Blueprint("campaigns", __name__)

QUARTER_RE = re.compile(r"^\d{4}Q[1-4]$")
HUNDRED = Decimal("100.00")


def fiscal_quarter(data):
    value = data.string("fiscal_quarter")
    if not QUARTER_RE.match(value):
        raise bad_request("fiscal_quarter must match ^\\d{4}Q[1-4]$")
    return value


@bp.post("/campaigns")
@require_roles("AgencyPlanner")
def create_campaign():
    data = body()
    advertiser_id = data.string("advertiser_id")
    name = data.string("name", max_len=160)
    target_demo = data.string("target_demo", max_len=16)
    universe_thousands = data.integer("universe_thousands", minimum=1)
    reach_goal_pct = data.decimal("reach_goal_pct", exclusive_min=True)
    frequency_goal = data.decimal("frequency_goal", exclusive_min=True, maximum=None)
    total_budget_cents = data.integer("total_budget_cents", minimum=1)
    flight_start = data.timestamp("flight_start")
    flight_end = data.timestamp("flight_end")
    quarter = fiscal_quarter(data)
    require_window(flight_start, flight_end, "flight")

    advertiser = get("advertisers", advertiser_id)

    record = store.new(
        "campaigns",
        {
            "advertiser_id": advertiser["id"],
            "name": name,
            "target_demo": target_demo,
            "universe_thousands": universe_thousands,
            "reach_goal_pct": reach_goal_pct,
            "frequency_goal": frequency_goal,
            "total_budget_cents": total_budget_cents,
            "flight_start": flight_start,
            "flight_end": flight_end,
            "fiscal_quarter": quarter,
            "plan_status": "DRAFT",
            "funding_status": "UNFUNDED",
            "funded_cents": 0,
        },
    )
    return created(serialize("campaigns", record))


@bp.get("/campaigns/<campaign_id>")
def get_campaign(campaign_id):
    return read_one("campaigns", campaign_id)


@bp.get("/campaigns")
def list_campaigns():
    return listing(
        "campaigns",
        {
            "advertiser_id": "advertiser_id",
            "plan_status": "plan_status",
            "fiscal_quarter": "fiscal_quarter",
        },
    )


@bp.post("/campaigns/<campaign_id>/submit-plan")
@require_roles("AgencyPlanner")
def submit_plan(campaign_id):
    campaign = get("campaigns", campaign_id)
    if campaign["plan_status"] not in ("DRAFT", "REVISION_REQUIRED"):
        raise ApiError("ERR_CAMPAIGN_PLAN_NOT_IN_EXPECTED_STATE")
    if campaign["plan_status"] == "REVISION_REQUIRED":
        if derive.campaign_plan_posture(campaign) == "REPLAN_REQUIRED":
            raise ApiError("ERR_PLAN_POSTURE_REPLAN_REQUIRED")
    allocations = derive.plan_allocations(campaign["id"])
    if not allocations or derive.allocation_pct_sum(campaign["id"]) != HUNDRED:
        raise ApiError("ERR_ALLOCATION_PCT_SUM_INVALID")
    advertiser = store.advertisers.get(campaign["advertiser_id"])
    if advertiser is not None and advertiser["credit_status"] == "HOLD":
        raise ApiError("ERR_ADVERTISER_CREDIT_HOLD")

    campaign["plan_status"] = "PENDING_CLIENT_APPROVAL"
    store.touch(campaign)
    return ok(serialize("campaigns", campaign))


@bp.post("/campaigns/<campaign_id>/approve-plan")
@require_roles("AdvertiserClient")
def approve_plan(campaign_id):
    campaign = get("campaigns", campaign_id)
    require_advertiser_owner(campaign["advertiser_id"])
    if campaign["plan_status"] != "PENDING_CLIENT_APPROVAL":
        raise ApiError("ERR_CAMPAIGN_PLAN_NOT_IN_EXPECTED_STATE")
    advertiser = store.advertisers.get(campaign["advertiser_id"])
    if advertiser is not None:
        if advertiser["credit_status"] == "HOLD":
            raise ApiError("ERR_ADVERTISER_CREDIT_HOLD")
        receivable = derive.outstanding_receivable_cents(advertiser)
        if receivable > advertiser["credit_limit_cents"]:
            raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED")

    campaign["plan_status"] = "APPROVED"
    cascades.lock_allocations(campaign)
    store.touch(campaign)
    return ok(serialize("campaigns", campaign))


@bp.post("/campaigns/<campaign_id>/reject-plan")
@require_roles("AdvertiserClient")
def reject_plan(campaign_id):
    data = body()
    data.string("revision_note")
    campaign = get("campaigns", campaign_id)
    require_advertiser_owner(campaign["advertiser_id"])
    if campaign["plan_status"] != "PENDING_CLIENT_APPROVAL":
        raise ApiError("ERR_CAMPAIGN_PLAN_NOT_IN_EXPECTED_STATE")

    campaign["plan_status"] = "DRAFT"
    cascades.unlock_allocations(campaign)
    store.touch(campaign)
    return ok(serialize("campaigns", campaign))


@bp.post("/campaigns/<campaign_id>/fund")
@require_roles("AdvertiserClient")
def fund_campaign(campaign_id):
    data = body()
    amount_cents = data.integer("amount_cents", minimum=1)
    campaign = get("campaigns", campaign_id)
    require_advertiser_owner(campaign["advertiser_id"])
    if campaign["funding_status"] == "FUNDED":
        raise ApiError("ERR_CAMPAIGN_ALREADY_FUNDED")

    campaign["funded_cents"] += amount_cents
    if campaign["funded_cents"] >= campaign["total_budget_cents"]:
        campaign["funding_status"] = "FUNDED"
    else:
        campaign["funding_status"] = "PARTIALLY_FUNDED"
    store.touch(campaign)
    return ok(serialize("campaigns", campaign))

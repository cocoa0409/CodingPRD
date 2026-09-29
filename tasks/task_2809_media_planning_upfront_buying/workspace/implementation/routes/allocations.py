"""Channel allocations: the budget split and its arithmetic (PRD 3.2)."""

from decimal import Decimal

from flask import Blueprint

from auth import require_roles
from constants import CHANNELS, DAYPARTS, MARKETS
from errors import ApiError
from lookup import get
from numeric import D
from response import created
from routes.common import listing, read_one
from serializers import serialize
from services import derive
from store import store
from validation import body

bp = Blueprint("allocations", __name__)

HUNDRED = Decimal("100.00")


@bp.post("/channel-allocations")
@require_roles("AgencyPlanner")
def create_allocation():
    data = body()
    campaign_id = data.string("campaign_id")
    channel = data.enum("channel", CHANNELS)
    allocation_pct = data.decimal("allocation_pct", exclusive_min=True)
    planned_cpm_cents = data.integer("planned_cpm_cents", minimum=1)
    planned_market = data.enum("planned_market", MARKETS)
    primary_daypart = data.enum("primary_daypart", DAYPARTS)

    campaign = get("campaigns", campaign_id)

    for alloc in derive.allocations_of(campaign["id"]):
        if alloc["status"] == "LOCKED":
            raise ApiError("ERR_ALLOCATION_LOCKED")

    if derive.allocation_pct_sum(campaign["id"]) + D(allocation_pct) > HUNDRED:
        raise ApiError("ERR_ALLOCATION_PCT_SUM_INVALID")

    record = store.new(
        "allocations",
        {
            "campaign_id": campaign["id"],
            "channel": channel,
            "allocation_pct": allocation_pct,
            "planned_cpm_cents": planned_cpm_cents,
            "planned_market": planned_market,
            "primary_daypart": primary_daypart,
            "status": "DRAFT",
        },
    )
    # The campaign's planning aggregates moved, so its version increments once.
    store.touch(campaign)
    return created(serialize("allocations", record))


@bp.get("/channel-allocations/<allocation_id>")
def get_allocation(allocation_id):
    return read_one("allocations", allocation_id)


@bp.get("/channel-allocations")
def list_allocations():
    return listing(
        "allocations",
        {"campaign_id": "campaign_id", "channel": "channel", "status": "status"},
    )

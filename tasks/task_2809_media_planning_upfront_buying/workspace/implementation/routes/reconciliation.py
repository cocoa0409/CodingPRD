"""Cross-platform reach reconciliation (PRD 3.9)."""

from decimal import Decimal

from flask import Blueprint

from constants import CHANNEL_GROUP, COMMITTED_BUY_STATUSES, DEDUP_METHODS, GROUP_ORDER
from auth import require_roles
from lookup import get
from numeric import D, q2, q4
from response import created
from routes.common import listing, read_one
from serializers import serialize
from services import derive
from store import store
from validation import body

bp = Blueprint("reconciliation", __name__)

ZERO2 = Decimal("0.00")
ZERO4 = Decimal("0.0000")
CAP = Decimal("100.0000")
HUNDRED = Decimal("100")

# Which pairwise estimate governs a step between two consecutive groups.
PAIRWISE_FIELD = {
    ("LINEAR", "CTV"): "linear_ctv_duplication_pct",
    ("CTV", "DIGITAL"): "ctv_digital_duplication_pct",
    ("LINEAR", "DIGITAL"): "linear_digital_duplication_pct",
}


@bp.post("/reconciliation-runs")
@require_roles("AgencyPlanner", "AgencyController")
def create_run():
    data = body()
    campaign_id = data.string("campaign_id")
    dedup_method = data.enum("dedup_method", DEDUP_METHODS)
    aggregate_pct = data.decimal(
        "aggregate_duplication_pct",
        required=(dedup_method == "AGGREGATE_DEDUP"),
        default=ZERO2,
    )
    pairwise = {
        field: data.decimal(field, required=False, default=ZERO2)
        for field in PAIRWISE_FIELD.values()
    }

    campaign = get("campaigns", campaign_id)

    scope = [
        buy
        for buy in derive.buys_of_campaign(campaign["id"])
        if buy["buy_status"] in COMMITTED_BUY_STATUSES
    ]
    included_report_count = sum(
        1
        for buy in scope
        for report in derive.reports_of_buy(buy["id"])
        if report["status"] == "ACCEPTED"
    )

    group_reach = {}
    gross_total = ZERO4
    if included_report_count > 0:
        for group in GROUP_ORDER:
            impressions = sum(
                derive.delivery_credits(buy)["credited_impressions_final"]
                for buy in scope
                if CHANNEL_GROUP[buy["channel"]] == group
            )
            # A group with no accepted delivery is omitted entirely.
            if impressions <= 0:
                continue
            group_reach[group] = _group_reach_pct(campaign, impressions)
        gross_total = q4(sum(group_reach.values(), ZERO4))

    if included_report_count == 0:
        status = "COMPLETED_NO_DATA"
        unduplicated = ZERO4
        implied_frequency = ZERO2
    else:
        status = "COMPLETED"
        if dedup_method == "SEQUENTIAL_DEDUP":
            unduplicated = _sequential(group_reach, pairwise)
        else:
            unduplicated = q4(gross_total * (Decimal(1) - aggregate_pct / HUNDRED))
        if unduplicated > CAP:
            unduplicated = CAP
        if unduplicated == 0:
            implied_frequency = ZERO2
        else:
            implied_frequency = q2(gross_total / unduplicated)

    record = store.new(
        "runs",
        dict(
            pairwise,
            campaign_id=campaign["id"],
            dedup_method=dedup_method,
            aggregate_duplication_pct=aggregate_pct,
            group_reach_pct=group_reach,
            gross_reach_pct_total=gross_total,
            unduplicated_reach_pct=unduplicated,
            implied_frequency=implied_frequency,
            included_report_count=included_report_count,
            status=status,
            computed_at=store.now(),
        ),
        versioned=False,
    )
    return created(serialize("runs", record))


def _group_reach_pct(campaign, impressions):
    """Impressions -> rating points -> reach percentage against the goal."""
    people = D(campaign["universe_thousands"]) * D(1000)
    if people <= 0:
        return ZERO4
    rating_points = D(impressions) / people * HUNDRED
    goal = D(campaign["frequency_goal"])
    if goal <= 0:
        return ZERO4
    return q4(rating_points / goal)


def _sequential(group_reach, pairwise):
    """Walk the present groups in fixed order, discounting each pairwise step."""
    total = ZERO4
    previous = None
    for group in GROUP_ORDER:
        if group not in group_reach:
            continue
        reach = group_reach[group]
        if previous is None:
            total = reach
        else:
            duplication = pairwise[PAIRWISE_FIELD[(previous, group)]]
            total = total + reach * (Decimal(1) - duplication / HUNDRED)
        previous = group
    return q4(total)


@bp.get("/reconciliation-runs/<reconciliation_run_id>")
def get_run(reconciliation_run_id):
    return read_one("runs", reconciliation_run_id)


@bp.get("/reconciliation-runs")
def list_runs():
    return listing("runs", {"campaign_id": "campaign_id", "dedup_method": "dedup_method"})

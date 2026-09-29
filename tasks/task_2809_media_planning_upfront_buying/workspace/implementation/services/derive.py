"""Every derived number in the system (PRD 2.5, 3.2, 3.5, 3.7, 3.8, 3.9).

Aggregates are computed live from the records they sum over, so a cascade can
never leave a stale total behind.  Only figures the PRD explicitly freezes -
a make-good's shortfall, an invoice's line rollups - are stored.
"""

from decimal import Decimal

from constants import (
    ALLOCATION_STATUSES,
    CANCEL_CEILING_EARLY_PCT,
    CANCEL_CEILING_LATE_PCT,
    COMMISSION_TIER_LARGE_FLOOR_CENTS,
    COMMISSION_TIER_LARGE_RATE,
    COMMISSION_TIER_MID_FLOOR_CENTS,
    COMMISSION_TIER_MID_RATE,
    COMMISSION_TIER_SMALL_RATE,
    COMMITTED_BUY_STATUSES,
    CPM_ABS_CEIL_CENTS,
    CPM_ABS_FLOOR_CENTS,
    CPM_BAND_HIGH,
    CPM_BAND_LOW,
    DAYPART_INDEX,
    HOLDING_UNIT_STATUSES,
    MARKET_MULTIPLIER,
)
from numeric import D, cents, floor_int, half_up, q2, q4
from store import sorted_records, store

ZERO2 = Decimal("0.00")
ZERO4 = Decimal("0.0000")


# ---------------------------------------------------------------------------
# collection helpers
# ---------------------------------------------------------------------------
def allocations_of(campaign_id):
    return sorted_records(
        [a for a in store.allocations.values() if a["campaign_id"] == campaign_id]
    )


def plan_allocations(campaign_id):
    """Allocations that count toward the plan: status DRAFT or LOCKED."""
    return [
        a for a in allocations_of(campaign_id) if a["status"] in ALLOCATION_STATUSES
    ]


def buys_of_campaign(campaign_id):
    return sorted_records(
        [b for b in store.buys.values() if b["campaign_id"] == campaign_id]
    )


def buys_of_allocation(allocation_id):
    return sorted_records(
        [
            b
            for b in store.buys.values()
            if b["channel_allocation_id"] == allocation_id
        ]
    )


def units_of_buy(buy_id):
    return sorted_records([u for u in store.units.values() if u["buy_id"] == buy_id])


def units_of_forecast(forecast_id):
    return sorted_records(
        [u for u in store.units.values() if u["forecast_id"] == forecast_id]
    )


def reports_of_buy(buy_id):
    return sorted_records([r for r in store.reports.values() if r["buy_id"] == buy_id])


def make_goods_of_buy(buy_id):
    return sorted_records(
        [m for m in store.make_goods.values() if m["buy_id"] == buy_id]
    )


def rights_of_buy(buy_id):
    return sorted_records([r for r in store.rights.values() if r["buy_id"] == buy_id])


def invoices_of_buy(buy_id):
    return sorted_records(
        [i for i in store.invoices.values() if i["buy_id"] == buy_id]
    )


# ---------------------------------------------------------------------------
# 3.2 planning arithmetic
# ---------------------------------------------------------------------------
def allocated_cents(campaign, allocation_pct):
    """floor(total_budget_cents * allocation_pct / 100) - never rounded up."""
    return floor_int(D(campaign["total_budget_cents"]) * D(allocation_pct) / D(100))


def effective_planned_cpm_cents(planned_cpm_cents, market, daypart):
    """Market- and daypart-adjusted CPM clamped into the planning band."""
    planned = D(planned_cpm_cents)
    raw = planned * MARKET_MULTIPLIER[market] * DAYPART_INDEX[daypart]
    band_floor = max(D(CPM_ABS_FLOOR_CENTS), half_up(planned * CPM_BAND_LOW))
    band_ceil = min(D(CPM_ABS_CEIL_CENTS), half_up(planned * CPM_BAND_HIGH))
    value = half_up(raw)
    if value < band_floor:
        value = band_floor
    # The ceiling has the final word when the two clamps disagree.
    if value > band_ceil:
        value = band_ceil
    return int(value)


def planned_impressions(alloc_cents, eff_cpm):
    if eff_cpm <= 0:
        return 0
    return floor_int(D(alloc_cents) * D(1000) / D(eff_cpm))


def planned_grp(impressions, universe_thousands):
    people = D(universe_thousands) * D(1000)
    if people <= 0:
        return ZERO2
    return q2(D(impressions) / people * D(100))


def planned_frequency(grp, reach_goal_pct):
    if D(reach_goal_pct) <= 0:
        return ZERO2
    return q2(D(grp) / D(reach_goal_pct))


def allocation_view(alloc):
    """Every computed field of one channel allocation."""
    campaign = store.campaigns.get(alloc["campaign_id"])
    alloc_cents = allocated_cents(campaign, alloc["allocation_pct"])
    eff_cpm = effective_planned_cpm_cents(
        alloc["planned_cpm_cents"], alloc["planned_market"], alloc["primary_daypart"]
    )
    impressions = planned_impressions(alloc_cents, eff_cpm)
    grp = planned_grp(impressions, campaign["universe_thousands"])
    committed = sum(
        b["gross_cost_cents"]
        for b in buys_of_allocation(alloc["id"])
        if b["buy_status"] in COMMITTED_BUY_STATUSES
    )
    return {
        "allocated_cents": alloc_cents,
        "effective_planned_cpm_cents": eff_cpm,
        "planned_impressions": impressions,
        "planned_grp": grp,
        "planned_frequency": planned_frequency(grp, campaign["reach_goal_pct"]),
        "committed_cents": committed,
        "posture": "OVERCOMMITTED" if committed > alloc_cents else "WITHIN_PLAN",
    }


def allocation_posture(alloc):
    return allocation_view(alloc)["posture"]


def campaign_view(campaign):
    """Every computed field of one campaign."""
    allocs = plan_allocations(campaign["id"])
    views = [allocation_view(a) for a in allocs]
    allocated = sum(v["allocated_cents"] for v in views)
    impressions_total = sum(v["planned_impressions"] for v in views)
    grp_total = q2(sum((v["planned_grp"] for v in views), Decimal("0")))
    committed = sum(
        b["gross_cost_cents"]
        for b in buys_of_campaign(campaign["id"])
        if b["buy_status"] in COMMITTED_BUY_STATUSES
    )
    posture = (
        "REPLAN_REQUIRED"
        if any(v["posture"] == "OVERCOMMITTED" for v in views)
        else "WITHIN_PLAN"
    )
    total = campaign["total_budget_cents"]
    return {
        "allocated_budget_cents": allocated,
        "unallocated_budget_cents": total - allocated,
        "committed_gross_cents": committed,
        "uncommitted_budget_cents": total - committed,
        "planned_impressions_total": impressions_total,
        "planned_grp_total": grp_total,
        "plan_posture": posture,
    }


def campaign_plan_posture(campaign):
    return campaign_view(campaign)["plan_posture"]


def allocation_pct_sum(campaign_id):
    """Sum of allocation_pct over the campaign's DRAFT and LOCKED allocations."""
    total = Decimal("0.00")
    for alloc in plan_allocations(campaign_id):
        total += D(alloc["allocation_pct"])
    return q2(total)


# ---------------------------------------------------------------------------
# 3.5 negotiated buy cost - tier selected on the pre-commission net
# ---------------------------------------------------------------------------
def commission_rate_for(net_media_cost_cents):
    if net_media_cost_cents < COMMISSION_TIER_MID_FLOOR_CENTS:
        return COMMISSION_TIER_SMALL_RATE
    if net_media_cost_cents < COMMISSION_TIER_LARGE_FLOOR_CENTS:
        return COMMISSION_TIER_MID_RATE
    return COMMISSION_TIER_LARGE_RATE


def cost_stack(guaranteed_impressions, agreed_cpm_cents):
    """The whole cost stack from the two frozen inputs and nothing else."""
    net = cents(D(guaranteed_impressions) * D(agreed_cpm_cents) / D(1000))
    rate = commission_rate_for(net)
    commission = cents(D(net) * rate)
    return {
        "net_media_cost_cents": net,
        "commission_rate": rate,
        "agency_commission_cents": commission,
        "gross_cost_cents": net + commission,
    }


def apply_cost_stack(buy):
    buy.update(cost_stack(buy["guaranteed_impressions"], buy["agreed_cpm_cents"]))
    return buy


# ---------------------------------------------------------------------------
# 3.6 / 3.8 buy delivery and inventory figures
# ---------------------------------------------------------------------------
def placed_impressions(buy):
    return sum(
        u["projected_impressions"]
        for u in units_of_buy(buy["id"])
        if u["status"] in HOLDING_UNIT_STATUSES
    )


def delivery_credits(buy):
    reports = reports_of_buy(buy["id"])
    provisional = sum(
        r["delivered_impressions"]
        for r in reports
        if r["status"] in ("SUBMITTED", "ACCEPTED")
    )
    final = sum(
        r["delivered_demo_impressions"] for r in reports if r["status"] == "ACCEPTED"
    )
    guaranteed = buy["guaranteed_impressions"]
    if guaranteed > 0:
        provisional_index = q4(D(provisional) / D(guaranteed))
        final_index = q4(D(final) / D(guaranteed))
    else:
        provisional_index = ZERO4
        final_index = ZERO4
    return {
        "credited_impressions_provisional": provisional,
        "credited_impressions_final": final,
        "provisional_delivery_index": provisional_index,
        "final_delivery_index": final_index,
    }


def shortfall(buy):
    """Absolute and percentage shortfall against the guarantee."""
    guaranteed = buy["guaranteed_impressions"]
    final = delivery_credits(buy)["credited_impressions_final"]
    amount = guaranteed - final
    if amount < 0:
        amount = 0
    if guaranteed > 0:
        pct = q4(D(amount) / D(guaranteed) * D(100))
    else:
        pct = ZERO4
    return amount, pct


def open_shortfall_impressions(buy):
    amount, _ = shortfall(buy)
    remaining = amount - buy["made_good_impressions"] - buy["waived_impressions"]
    return remaining if remaining > 0 else 0


def shortfall_value_cents(impressions, agreed_cpm_cents):
    return cents(D(impressions) / D(1000) * D(agreed_cpm_cents))


# ---------------------------------------------------------------------------
# 3.4 avail availability
# ---------------------------------------------------------------------------
def available_impressions(forecast):
    held = sum(
        u["projected_impressions"]
        for u in units_of_forecast(forecast["id"])
        if u["status"] in HOLDING_UNIT_STATUSES
    )
    return forecast["total_impressions"] - held


# ---------------------------------------------------------------------------
# 3.1 counterparty exposure
# ---------------------------------------------------------------------------
def seller_exposure(seller):
    open_total = 0
    scheduled_total = 0
    for mg in store.make_goods.values():
        buy = store.buys.get(mg["buy_id"])
        if buy is None or buy["seller_id"] != seller["id"]:
            continue
        if mg["status"] in ("OPEN", "OFFERED"):
            open_total += mg["shortfall_impressions"]
        elif mg["status"] == "SCHEDULED":
            scheduled_total += mg["offered_impressions"]
    return {
        "open_make_good_impressions": open_total,
        "scheduled_make_good_impressions": scheduled_total,
    }


def advertiser_of_buy(buy):
    campaign = store.campaigns.get(buy["campaign_id"])
    if campaign is None:
        return None
    return store.advertisers.get(campaign["advertiser_id"])


def outstanding_receivable_cents(advertiser):
    total = 0
    for invoice in store.invoices.values():
        if invoice["client_status"] not in ("ISSUED", "PARTIALLY_PAID"):
            continue
        buy = store.buys.get(invoice["buy_id"])
        if buy is None:
            continue
        owner = advertiser_of_buy(buy)
        if owner is None or owner["id"] != advertiser["id"]:
            continue
        total += invoice["net_payable_cents"] - invoice["client_paid_cents"]
    return total


# ---------------------------------------------------------------------------
# 3.9 invoice arithmetic - commission rounded per line before summation
# ---------------------------------------------------------------------------
def billable_lines(buy, period_start, period_end):
    lines = [
        u
        for u in store.units.values()
        if u["buy_id"] == buy["id"]
        and u["status"] in ("AIRED", "MAKE_GOOD_AIRED")
        and period_start <= u["air_window_end"] <= period_end
    ]
    return sorted(lines, key=lambda u: (u["air_window_start"], u["created_at"], u["_seq"]))


def line_money(units, unit_rate_cents, commission_rate):
    net = cents(D(units) * D(unit_rate_cents))
    commission = cents(D(net) * D(commission_rate))
    return {
        "line_net_cents": net,
        "line_commission_cents": commission,
        "line_gross_cents": net + commission,
    }


def invoice_rollups(buy, lines):
    seller_payable = 0
    commission_total = 0
    gross_total = 0
    for line in lines:
        money = line_money(line["units"], line["unit_rate_cents"], buy["commission_rate"])
        seller_payable += money["line_net_cents"]
        commission_total += money["line_commission_cents"]
        gross_total += money["line_gross_cents"]
    return {
        "line_count": len(lines),
        "seller_payable_cents": seller_payable,
        "agency_commission_cents": commission_total,
        "gross_billable_cents": gross_total,
    }


def make_good_credit_cents(buy):
    return sum(
        mg["waived_credit_cents"]
        for mg in make_goods_of_buy(buy["id"])
        if mg["status"] == "WAIVED"
    )


def net_payable_cents(gross_billable, credit):
    value = gross_billable - credit
    return value if value > 0 else 0


def max_remittable_cents(invoice, advertiser):
    """The sequential-liability release ceiling (PRD 3.9)."""
    seller_payable = invoice["seller_payable_cents"]
    net_payable = invoice["net_payable_cents"]
    if net_payable == 0:
        return 0
    if advertiser is not None and not advertiser["sequential_liability_enabled"]:
        return seller_payable
    pro_rata = floor_int(
        D(invoice["client_paid_cents"]) * D(seller_payable) / D(net_payable)
    )
    return min(seller_payable, pro_rata)


# ---------------------------------------------------------------------------
# 3.7 cancellation ceiling tiers
# ---------------------------------------------------------------------------
def cancellation_ceiling_pct(buy, now):
    if now < buy["cancel_window_1_close"]:
        return CANCEL_CEILING_EARLY_PCT
    return CANCEL_CEILING_LATE_PCT


def cumulative_pct(buy, kind):
    total = Decimal("0.00")
    for record in rights_of_buy(buy["id"]):
        if record["kind"] == kind:
            total += D(record["requested_pct"])
    return q2(total)

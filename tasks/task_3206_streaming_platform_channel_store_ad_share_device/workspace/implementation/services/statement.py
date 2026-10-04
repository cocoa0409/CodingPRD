"""Statement calculation service: tier assignment, subscription payout, net."""

from middleware import parse_iso8601, period_bounds
from db import store
from services.common import (
    round_half_up_cents,
    PREMIER_FEE_BPS,
    PREMIER_THRESHOLD_CENTS,
    PROCESSING_FEE_PER_CHARGE_CENTS,
    STANDARD_FEE_BPS,
    STANDING_PENALTY_BPS,
)


def _prior_periods(period, n=3):
    y = int(period[0:4])
    m = int(period[5:7])
    out = []
    for _ in range(n):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
        out.append(f"{y:04d}-{m:02d}")
    return out


def assign_tier_and_fee(publisher, period):
    """Pinned backward-looking tier evaluation (breaks the circularity)."""
    trailing = set(_prior_periods(period, 3))
    trailing_sum = 0
    for s in store.statements.values():
        if (s["publisher_id"] == publisher["id"]
                and s["period"] in trailing
                and s["status"] in ("FINALIZED", "SETTLED", "DISPUTED")):
            trailing_sum += s["net_payout_cents"]
    tier = "PREMIER" if trailing_sum >= PREMIER_THRESHOLD_CENTS else "STANDARD"
    fee = PREMIER_FEE_BPS if tier == "PREMIER" else STANDARD_FEE_BPS
    if publisher["standing"] == "SUSPENDED":
        fee += STANDING_PENALTY_BPS
    return tier, fee


def subscription_payout(sub_base, charge_count, fee_bps, billing_model):
    if billing_model == "GROSS_SHARE":
        return round_half_up_cents(sub_base * (10000 - fee_bps), 10000)
    # NET_OF_FEES
    net_base = sub_base - PROCESSING_FEE_PER_CHARGE_CENTS * charge_count
    return round_half_up_cents(net_base * (10000 - fee_bps), 10000)


def compute_amounts(publisher, period, fee_bps=None):
    """Compute the statement's amount streams from live data.

    When fee_bps is None (provisional generate), subscription payout fields
    are left at their provisional default of 0 (tier/fee unknown until
    finalization). When fee_bps is given (finalize), subscription payout is
    locked per the publisher's billing_model.
    """
    pstart, pend = period_bounds(period)
    channel_ids = {
        c["id"] for c in store.channels.values() if c["publisher_id"] == publisher["id"]
    }
    gross = 0
    refunds = 0
    charge_count = 0
    for s in store.subscriptions.values():
        if s["channel_id"] not in channel_ids:
            continue
        created = parse_iso8601(s["created_at"], "created_at")
        if pstart <= created < pend:
            gross += s["price_cents"]
            charge_count += 1
        if s.get("refunded_at"):
            refunded = parse_iso8601(s["refunded_at"], "refunded_at")
            if pstart <= refunded < pend:
                refunds += s["price_cents"]
    sub_base = gross - refunds

    ad_gross = 0
    ad_payout = 0
    for g in store.ad_slot_grants.values():
        if g["channel_id"] in channel_ids and g["period"] == period:
            ad_gross += g["ad_gross_cents"]
            ad_payout += g["publisher_payout_cents"]

    placement_spend = 0
    for c in store.campaigns.values():
        if c["publisher_id"] != publisher["id"]:
            continue
        fs = parse_iso8601(c["flight_start"], "flight_start")
        if pstart <= fs < pend:
            placement_spend += c["spent_cents"]

    if fee_bps is None:
        sub_payout = 0
        platform_sub_fee = sub_base
    else:
        sub_payout = subscription_payout(sub_base, charge_count, fee_bps,
                                         publisher["billing_model"])
        platform_sub_fee = sub_base - sub_payout

    net = sub_payout + ad_payout - placement_spend
    return {
        "subscription_gross_cents": gross,
        "refund_cents": refunds,
        "charge_count": charge_count,
        "sub_payout_cents": sub_payout,
        "platform_sub_fee_cents": platform_sub_fee,
        "ad_gross_cents": ad_gross,
        "ad_payout_cents": ad_payout,
        "platform_ad_fee_cents": ad_gross - ad_payout,
        "placement_spend_cents": placement_spend,
        "net_payout_cents": net,
    }

"""Calculation rules: closing statement, departure proration, advance recovery,
retention index. All money is integer cents; rates round half-up per line."""
from decimal import Decimal, ROUND_HALF_UP


def rhu_rate(amount_cents, bps):
    """round_half_up(amount * bps / 10000) -> int cents."""
    d = (Decimal(int(amount_cents)) * Decimal(int(bps)) / Decimal(10000))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu_div(numer, denom):
    """round_half_up(numer / denom) -> int."""
    d = Decimal(int(numer)) / Decimal(int(denom))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def closing_statement(txn, schedule, referral_bps, advance_balance):
    """Returns a dict of the computed closing figures (all int cents)."""
    gross = txn["gross_commission_cents"]
    referral_fee = rhu_rate(gross, referral_bps)
    net_gci = gross - referral_fee
    agent_retention = rhu_rate(net_gci, schedule["retention_bps"])
    overhead_share = rhu_rate(net_gci, schedule["overhead_share_bps"])
    office_split = net_gci - agent_retention - overhead_share
    advance_offset = min(agent_retention, max(0, advance_balance))
    agent_disbursed = agent_retention - advance_offset
    return {
        "gross": gross,
        "referral_fee": referral_fee,
        "net_gci": net_gci,
        "agent_retention": agent_retention,
        "overhead_share": overhead_share,
        "office_split": office_split,
        "advance_offset": advance_offset,
        "agent_disbursed": agent_disbursed,
    }


def departure_proration(desk_fee_cents, day_of_month):
    """Returns (owed_cents, refund_cents); owed + refund == desk_fee_cents."""
    owed = rhu_div(desk_fee_cents * day_of_month, 30)
    refund = rhu_div(desk_fee_cents * (30 - day_of_month), 30)
    # reconcile so owed + refund == desk_fee_cents exactly
    refund = desk_fee_cents - owed
    return owed, refund

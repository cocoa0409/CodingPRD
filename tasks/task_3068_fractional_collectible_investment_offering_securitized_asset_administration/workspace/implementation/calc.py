"""Calculation rules (§1.3) — all money is integer cents, all rounding pinned."""
from decimal import Decimal, ROUND_HALF_UP

from catalog import DAYS_PER_YEAR, FEE_BPS_BASE, CADENCE_DUE_DAYS, CADENCE_REQUIRED_DAYS
from store import parse_dt, to_ms, fmt_dt


def div_floor(numerator, denominator):
    """Integer division with floor semantics (never rounds up)."""
    if denominator == 0:
        return 0
    return numerator // denominator


def bps_floor(amount, bps):
    return div_floor(int(amount) * int(bps), FEE_BPS_BASE)


def share_cap(total_shares, registration_cap_pct):
    return div_floor(int(total_shares) * int(registration_cap_pct), FEE_BPS_BASE)


def minimum_secondary_lot(total_shares, liquidity_ratio_bps):
    return div_floor(int(total_shares) * int(liquidity_ratio_bps), FEE_BPS_BASE)


def value_per_share(basis_cents, total_shares):
    return div_floor(int(basis_cents), int(total_shares))


def day_gap(later, earlier):
    """Whole days between two instants (``later - earlier``)."""
    a = parse_dt(later)
    b = parse_dt(earlier)
    if a is None or b is None:
        return None
    return (a - b).days


def cadence_flag(gap_days):
    """gap_days >= 180 -> REQUIRED; gap_days > 90 -> DUE; else CURRENT."""
    if gap_days is None:
        return "CURRENT"
    if gap_days >= CADENCE_REQUIRED_DAYS:
        return "REQUIRED"
    if gap_days > CADENCE_DUE_DAYS:
        return "DUE"
    return "CURRENT"


def management_fee(value_cents, fee_bps, holding_days):
    """floor(value * bps / 10000 * days / 365) using exact rational arithmetic."""
    if holding_days is None:
        return 0
    num = Decimal(int(value_cents)) * Decimal(int(fee_bps)) * Decimal(int(holding_days))
    den = Decimal(FEE_BPS_BASE) * Decimal(DAYS_PER_YEAR)
    return int((num / den).to_integral_value(rounding="ROUND_FLOOR"))


def round_half_up_cents(numerator, denominator):
    """Presentation rounding, half-up to the whole cent."""
    if denominator == 0:
        return 0
    q = (Decimal(int(numerator)) / Decimal(int(denominator))) * Decimal(FEE_BPS_BASE)
    return int(q.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def presentation_amount(basis_cents, fee_bps, holding_days):
    num = Decimal(int(basis_cents)) * Decimal(int(fee_bps)) * Decimal(int(holding_days or 0))
    den = Decimal(FEE_BPS_BASE) * Decimal(DAYS_PER_YEAR)
    return int((num / den).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def preferred_return(acquisition_cost_cents, preferred_return_bps, held_for_days):
    if held_for_days is None:
        return 0
    num = Decimal(int(acquisition_cost_cents)) * Decimal(int(preferred_return_bps)) * Decimal(int(held_for_days))
    den = Decimal(FEE_BPS_BASE) * Decimal(DAYS_PER_YEAR)
    return int((num / den).to_integral_value(rounding="ROUND_FLOOR"))


def waterfall(offering, artwork, executed_gross_cents, held_for_days):
    """The pinned sale distribution waterfall (§3.8). Every step floored before
    subtraction."""
    distributable = int(executed_gross_cents) - int(artwork["acquisition_cost_cents"])
    distributed_cost = bps_floor(offering.get("custody_cost_ledger_cents") or 0,
                                 offering["cost_pass_through_bps"])
    management_fee = bps_floor(artwork["acquisition_cost_cents"],
                               offering["management_fee_bps"])
    pref_return = preferred_return(artwork["acquisition_cost_cents"],
                                   offering["preferred_return_bps"], held_for_days)
    participation = bps_floor(distributable, offering["profit_participation_bps"])
    residual = (distributable - distributed_cost - management_fee
                - pref_return - participation)
    total_shares = int(offering["total_shares"])
    per_share = div_floor(residual, total_shares)
    remainder = residual - per_share * total_shares
    return {
        "sale_gross_cents": int(executed_gross_cents),
        "distributable_cents": distributable,
        "distributed_cost_cents": distributed_cost,
        "management_fee_cents": management_fee,
        "preferred_return_cents": pref_return,
        "profit_participation_cents": participation,
        "investor_residual_cents": residual,
        "per_share_cents": per_share,
        "remainder_cents": remainder,
    }
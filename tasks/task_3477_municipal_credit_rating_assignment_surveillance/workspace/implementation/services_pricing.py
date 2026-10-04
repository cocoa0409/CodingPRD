"""Borrowing cost at sale (PRD §3.7): benchmark 300 bps + per-notch spread;
annual interest rounded half-up to whole cents FIRST, then multiplied by the
maturity (the alternative order is explicitly forbidden)."""
from decimal import Decimal, ROUND_HALF_UP

from constants import BENCHMARK_YIELD_BPS, SPREAD_BPS_BY_NOTCH

_WHOLE_CENT = Decimal("1")


def price(par_amount_cents, maturity_years, notch):
    """Return (effective_yield_bps, annual_interest_cents, total_interest_cents)."""
    effective_yield_bps = BENCHMARK_YIELD_BPS + SPREAD_BPS_BY_NOTCH[notch]
    annual_exact = Decimal(par_amount_cents) * Decimal(effective_yield_bps) / Decimal(10000)
    annual_interest_cents = int(annual_exact.quantize(_WHOLE_CENT, rounding=ROUND_HALF_UP))
    total_interest_cents = maturity_years * annual_interest_cents
    return effective_yield_bps, annual_interest_cents, total_interest_cents

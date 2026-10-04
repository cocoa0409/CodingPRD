"""Calculation rules: tiered pricing, baseline cost, savings verification,
financing payments, blended payback and the subsidy waterfall."""
from decimal import Decimal, ROUND_HALF_UP

HDD_COEF = Decimal("0.05")
CDD_COEF = Decimal("0.08")
REFERENCE_OCCUPANCY = Decimal("0.5")
SHORT_PAYBACK_YEARS = 3
LONG_PAYBACK_YEARS = 7
BOND_FEE_UPLIFT = Decimal("1.02")
TP_SPREAD = Decimal("0.015")

_KWH_Q = Decimal("0.0001")
_CENT_Q = Decimal("1")
_RATIO_Q = Decimal("0.0001")
_PAYBACK_Q = Decimal("0.01")


def _d(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def tiered_price_cents(kwh, rate_schedule):
    """Walk tiers in order; kwh is a Decimal (may carry 4-dp fractions)."""
    remaining = _d(kwh)
    cost = Decimal("0")
    for tier in rate_schedule:
        if remaining <= 0:
            break
        up_to = tier.get("up_to_kwh")
        price = _d(tier["cents_per_kwh"])
        if up_to is None:
            take = remaining
        else:
            take = min(remaining, _d(up_to))
        cost += take * price
        remaining -= take
    return int(cost.quantize(_CENT_Q, rounding=ROUND_HALF_UP))


def baseline_adjusted_cost(annual_energy_kwh, hdd, cdd, occupancy_factor,
                           avg_hdd, avg_cdd, rate_schedule):
    """Weather+occupancy normalize then tiered-price. kwh held at 4 dp."""
    kwh = _d(annual_energy_kwh)
    hdd = _d(hdd)
    cdd = _d(cdd)
    avg_hdd = _d(avg_hdd)
    avg_cdd = _d(avg_cdd)
    occ = _d(occupancy_factor)
    hdd_factor = Decimal(1) + HDD_COEF * (avg_hdd - hdd) / max(Decimal(1), hdd)
    cdd_factor = Decimal(1) + CDD_COEF * (avg_cdd - cdd) / max(Decimal(1), cdd)
    occ_factor = occ / REFERENCE_OCCUPANCY
    norm = (kwh * hdd_factor * cdd_factor * occ_factor).quantize(_KWH_Q)
    return tiered_price_cents(norm, rate_schedule)


def verified_savings(contract, baseline, report, verified_measures_savings):
    """Returns verified_savings_cents per the mv_protocol variant."""
    if contract["mv_protocol"] in ("IPMVP_B", "IPMVP_C"):
        actual = _d(report["actual_energy_kwh"])
        b_hdd = _d(baseline["heating_degree_days"])
        b_cdd = _d(baseline["cooling_degree_days"])
        p_hdd = _d(report["period_hdd"])
        p_cdd = _d(report["period_cdd"])
        hdd_factor = Decimal(1) - HDD_COEF * (p_hdd - b_hdd) / max(Decimal(1), b_hdd)
        cdd_factor = Decimal(1) - CDD_COEF * (p_cdd - b_cdd) / max(Decimal(1), b_cdd)
        occ_factor = _d(baseline["occupancy_factor"]) / _d(report["period_occupancy_factor"])
        norm = (actual * hdd_factor * cdd_factor * occ_factor).quantize(_KWH_Q)
        period_cost = tiered_price_cents(norm, baseline["rate_schedule"])
        raw = Decimal(baseline["adjusted_annual_cost_cents"]) - Decimal(period_cost)
        return int(raw.quantize(_CENT_Q, rounding=ROUND_HALF_UP))
    # stipulated: IPMVP_A / IPMVP_D
    raw = Decimal("0.95") * Decimal(verified_measures_savings)
    return int(raw.quantize(_CENT_Q, rounding=ROUND_HALF_UP))


def financing_payment(facility_type, principal_cents, annual_rate_pct, term_years):
    """Level annual payment in integer cents, per facility type.

    PRD §3.3: BOND computes the plain annuity and then multiplies by the
    BOND_FEE_UPLIFT (so a zero-rate bond pays (P/n) * 1.02); THIRD_PARTY
    computes the annuity at (rate + TP_SPREAD); LEASE is the plain annuity,
    with P/n when the rate is exactly zero."""
    P = Decimal(principal_cents)
    r = _d(annual_rate_pct) / Decimal(100)
    n = int(term_years)
    if facility_type == "THIRD_PARTY":
        r = r + TP_SPREAD
        payment = P * r / (Decimal(1) - (Decimal(1) + r) ** (-n))
    else:
        if r == 0:
            payment = P / Decimal(n)
        else:
            payment = P * r / (Decimal(1) - (Decimal(1) + r) ** (-n))
        if facility_type == "BOND":
            payment = payment * BOND_FEE_UPLIFT
    return int(payment.quantize(_CENT_Q, rounding=ROUND_HALF_UP))


def coverage_ratio(guaranteed_annual_savings_cents, annual_payment_cents):
    ratio = Decimal(guaranteed_annual_savings_cents) / Decimal(annual_payment_cents)
    return float(ratio.quantize(_RATIO_Q, rounding=ROUND_HALF_UP))


def simple_payback(installed_cost_cents, annual_savings_cents):
    if annual_savings_cents == 0:
        return None
    return Decimal(installed_cost_cents) / Decimal(annual_savings_cents)


def blended_payback(counted_measures):
    cost_sum = sum(m["installed_cost_cents"] for m in counted_measures)
    savings_sum = sum(m["annual_savings_cents"] for m in counted_measures)
    if savings_sum == 0:
        return None
    ratio = Decimal(cost_sum) / Decimal(savings_sum)
    return float(ratio.quantize(_PAYBACK_Q, rounding=ROUND_HALF_UP))


def subsidy_pool(counted_measures):
    pool = 0
    for m in counted_measures:
        sp = m.get("simple_payback_years")
        if sp is not None and _d(sp) <= Decimal(SHORT_PAYBACK_YEARS):
            pool += max(0, m["annual_savings_cents"] * SHORT_PAYBACK_YEARS - m["installed_cost_cents"])
    return pool


def subsidy_waterfall(included_measures, pool):
    """Assign subsidy_draw_cents over INCLUDED measures; returns nothing (mutates)."""
    eligible = [m for m in included_measures if m.get("simple_payback_years") is not None]
    eligible.sort(key=lambda m: (_d(m["simple_payback_years"]), m["created_at"], m["id"]))
    remaining = int(pool)
    for m in eligible:
        if _d(m["simple_payback_years"]) > Decimal(LONG_PAYBACK_YEARS):
            need = m["installed_cost_cents"] - m["annual_savings_cents"] * LONG_PAYBACK_YEARS
            draw = min(need, remaining)
            if draw < 0:
                draw = 0
            m["subsidy_draw_cents"] = draw
            remaining -= draw
        else:
            m["subsidy_draw_cents"] = 0
    for m in included_measures:
        if m.get("simple_payback_years") is None:
            m["subsidy_draw_cents"] = 0

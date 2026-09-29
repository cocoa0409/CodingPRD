"""Deterministic calculations (PRD 3 worked examples)."""
import calendar
import math
from decimal import Decimal

from money import D, ZERO, q2, pct_of

HUNDRED = Decimal(100)


def rate_variance_pct(contracted, standard):
    """Signed percentage deviation from rack rate, two decimals."""
    standard = D(standard)
    if standard == 0:
        return ZERO
    return q2((D(contracted) - standard) * HUNDRED / standard)


def occupancy_tax_provisional(line_amount, tax_pct):
    """Per-line tax, rounded once per line."""
    return pct_of(line_amount, tax_pct)


def occupancy_tax_final(net_base, tax_pct):
    """One rounding over the netted base."""
    return pct_of(net_base, tax_pct)


def true_up_delta(final_tax, provisional_sum):
    return q2(D(final_tax) - D(provisional_sum))


def late_checkout_charge(scheduled_at, actual_at, grace_minutes, contracted_rate):
    """Tiered late-departure fee: round, then floor at 25.00, then cap at rate."""
    overdue_minutes = int(math.floor(
        (actual_at - scheduled_at).total_seconds() / 60.0
    ))
    if overdue_minutes <= int(grace_minutes):
        return ZERO, overdue_minutes
    if overdue_minutes <= 180:
        tier = Decimal("0.25")
    elif overdue_minutes <= 360:
        tier = Decimal("0.50")
    else:
        tier = Decimal("1.00")
    rate = D(contracted_rate)
    tiered = q2(rate * tier)
    floored = tiered if tiered >= Decimal("25.00") else Decimal("25.00")
    capped = floored if floored <= rate else rate
    return q2(capped), overdue_minutes


def ticket_figures(gross, service_charge_pct, fb_tax_rate_pct,
                   large_ticket_threshold, large_party_discount_pct):
    """Service charge compounds into the tax base; the discount never does."""
    gross = D(gross)
    service_charge = pct_of(gross, service_charge_pct)
    taxable_base = q2(gross + service_charge)
    tax = pct_of(taxable_base, fb_tax_rate_pct)
    if taxable_base >= D(large_ticket_threshold):
        discount = pct_of(gross, large_party_discount_pct)
    else:
        discount = ZERO
    total = q2(taxable_base + tax - discount)
    return {
        "service_charge_amount": service_charge,
        "taxable_base_amount": taxable_base,
        "tax_amount": tax,
        "large_party_discount_amount": discount,
        "total_amount": total,
    }


def city_ledger_fee(balance, fee_pct):
    return pct_of(balance, fee_pct)


def settlement_variance(declared, system):
    return q2(D(declared) - D(system))


def occupancy_pct(rooms_occupied, rooms_available):
    if not rooms_available:
        return ZERO
    return q2(D(rooms_occupied) * HUNDRED / D(rooms_available))


def adr(room_night_revenue, rooms_occupied):
    if not rooms_occupied:
        return ZERO
    return q2(D(room_night_revenue) / D(rooms_occupied))


def revpar(room_night_revenue, rooms_available):
    if not rooms_available:
        return ZERO
    return q2(D(room_night_revenue) / D(rooms_available))


def pace_index_pct(room_revenue, benchmark):
    benchmark = D(benchmark)
    if benchmark == 0:
        return ZERO
    return q2(D(room_revenue) * HUNDRED / benchmark)


def aging_days(obtained_at, now_at):
    return int(math.floor((now_at - obtained_at).total_seconds() / 86400.0))


def required_approval_role(requested_amount, manager_threshold, controller_threshold):
    amount = D(requested_amount)
    if amount >= D(controller_threshold):
        return "Controller"
    if amount >= D(manager_threshold):
        return "RevenueManager"
    return "NightAuditor"


APPROVAL_RANK = {"NightAuditor": 1, "RevenueManager": 2, "Controller": 3}


def role_clears_tier(actor_role, required_role):
    return APPROVAL_RANK.get(actor_role, 0) >= APPROVAL_RANK.get(required_role, 0)


def retention_until(period_month):
    """Last calendar day of the period month, plus seven years."""
    year, month = int(period_month[0:4]), int(period_month[5:7])
    last_day = calendar.monthrange(year, month)[1]
    target_year = year + 7
    target_last = calendar.monthrange(target_year, month)[1]
    day = last_day if last_day <= target_last else target_last
    return "%04d-%02d-%02d" % (target_year, month, day)

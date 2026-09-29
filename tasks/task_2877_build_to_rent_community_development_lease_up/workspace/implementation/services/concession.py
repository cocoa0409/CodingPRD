"""Concession amortization, credits and revocation (PRD section 3.8)."""
from __future__ import annotations

from decimal import Decimal

from calc import rhu_int
from db import set_field

WEEKS_PER_MONTH_NUMERATOR = 12
WEEKS_PER_YEAR = 52


def total_concession_cents(gross_monthly_charge_cents, free_weeks):
    """gross * free_weeks * 12 / 52, rounded half up. The concession is rounded
    exactly once, here at the total."""
    return rhu_int(
        Decimal(gross_monthly_charge_cents) * Decimal(free_weeks)
        * Decimal(WEEKS_PER_MONTH_NUMERATOR) / Decimal(WEEKS_PER_YEAR)
    )


def straight_line_schedule(total, term_months):
    """Per-period credit rounded half up, repeated for one fewer period than the
    term; the final period absorbs the entire rounding residual."""
    per_period = rhu_int(Decimal(total) / Decimal(term_months))
    earlier = term_months - 1
    credits = [per_period] * earlier
    credits.append(total - per_period * earlier)
    return credits


def upfront_schedule(total, gross_monthly_charge_cents):
    """Consume the concession in whole months of gross charge; the last period
    carries whatever is left."""
    credits = []
    remaining = total
    while remaining > 0:
        take = gross_monthly_charge_cents if gross_monthly_charge_cents < remaining else remaining
        if take <= 0:
            break
        credits.append(take)
        remaining -= take
    return credits


def net_effective_rent_cents(gross_monthly_charge_cents, term_months, total):
    """Mode independent: (gross * term - total) / term, rounded half up."""
    return rhu_int(
        (Decimal(gross_monthly_charge_cents) * Decimal(term_months) - Decimal(total))
        / Decimal(term_months)
    )


def build_amortization(lease, program):
    """Recompute the lease's concession arithmetic from the attached program."""
    gross = lease["gross_monthly_charge_cents"]
    total = total_concession_cents(gross, program["free_weeks"])
    if program["amortization_mode"] == "STRAIGHT_LINE_NET_EFFECTIVE":
        credits = straight_line_schedule(total, lease["term_months"])
    else:
        credits = upfront_schedule(total, gross)
    schedule = [{"period_index": index + 1, "credit_cents": credit}
                for index, credit in enumerate(credits)]
    first_credit = schedule[0]["credit_cents"] if schedule else 0
    first_period_charge = gross - first_credit
    if first_period_charge < 0:
        first_period_charge = 0
    set_field(lease, "total_concession_cents", total)
    set_field(lease, "concession_schedule", schedule)
    set_field(lease, "monthly_concession_credit_cents", first_credit)
    set_field(lease, "first_period_charge_cents", first_period_charge)
    set_field(lease, "net_effective_rent_cents",
              net_effective_rent_cents(gross, lease["term_months"], total))
    set_field(lease, "concession_remaining_cents", total)
    set_field(lease, "concession_applied_cents", 0)
    set_field(lease, "credits_applied_count", 0)


def wind_back_on_rejection(lease):
    """A REJECT winds the concession arithmetic back; net_effective_rent_cents is
    not listed among the fields that reset (PRD section 3.8)."""
    set_field(lease, "total_concession_cents", 0)
    set_field(lease, "monthly_concession_credit_cents", 0)
    set_field(lease, "first_period_charge_cents", 0)
    set_field(lease, "concession_remaining_cents", 0)
    set_field(lease, "concession_schedule", [])


def revoke(lease):
    """The compensating exit. Money already applied stays applied, so
    concession_applied_cents and concession_remaining_cents are left alone; the
    ledgers shed this lease because REVOKED is outside the committed statuses."""
    if lease["concession_status"] in ("REQUESTED", "APPROVED", "AMORTIZING"):
        set_field(lease, "concession_status", "REVOKED")
        return True
    return False

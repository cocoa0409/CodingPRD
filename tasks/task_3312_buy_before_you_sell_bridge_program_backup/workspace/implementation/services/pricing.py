"""Offer pricing floor and the program's dual cost view.

**Backup-offer price floor (PRD 3.6).**  The floor begins from the departing
property's appraised value reduced by 1200 basis points -- the appraisal less a
twelve per cent discount -- with the division flooring.  That discounted figure
is then reduced again by a condition modifier: none at all for a home graded
``A``, 200 basis points for ``B``, 450 for ``C`` and 600 for ``D``, again
flooring.  The result is compared against a regulatory floor set at 8500 basis
points of the appraised value, and whichever of the two is greater becomes the
binding ``price_basis_cents``.  In practice a well-conditioned ``A`` or ``B``
home is bound by its discounted floor, while a distressed ``C`` or ``D`` home has
been pushed by the condition modifier below the regulatory line and is bound by
the regulatory floor instead.

**Dual carrying-cost view (PRD 3.9).**  The *true* cost counts what has actually
happened: outstanding carrying costs plus interest on the loan's
``outstanding_principal_cents`` at the loan's rate over the whole calendar months
that have actually elapsed between origination and the logical clock.  The
*amortized* cost counts what was planned: the same outstanding carrying costs
plus interest on the full ``principal_cents`` over the program's
``projected_carry_months``.  The variance is true minus amortized and may
legitimately be negative.  Which of the two the summary emphasizes follows the
program's advance axis -- a program in ``FUNDED`` is read on the actual elapsed
months, while a program still in ``PENDING`` or ``FUNDING`` is read on the
projected horizon.
"""

from constants import (
    BPS_DENOMINATOR,
    OFFER_CONDITION_MODIFIER_BPS,
    OFFER_DISCOUNT_BPS,
    REGULATORY_MIN_RATIO_BPS,
)
from services import current_time
from services.lookup import lookup
from timeutil import whole_months_between

# Interest on a monthly horizon divides by 10000 * 100 (bps -> fraction, year ->
# months), matching the scaffold's dual_carrying_cost_view expression.
_MONTH_DENOMINATOR = BPS_DENOMINATOR * 100


def price_floor_cents(departing_property):
    """The ``backup_offer_price_floor`` calculation."""
    appraised = int(departing_property.get("appraised_value_cents") or 0)
    base = (appraised * (BPS_DENOMINATOR - OFFER_DISCOUNT_BPS)) // BPS_DENOMINATOR
    modifier = OFFER_CONDITION_MODIFIER_BPS.get(departing_property.get("condition_grade"), 0)
    discounted_floor = (base * (BPS_DENOMINATOR - modifier)) // BPS_DENOMINATOR
    regulatory_floor = (appraised * REGULATORY_MIN_RATIO_BPS) // BPS_DENOMINATOR
    return max(discounted_floor, regulatory_floor)


def offer_bounds_apply(offer):
    """Only offers in these statuses are bounded by the floor (PRD 3.6)."""
    return offer.get("status") in ("DRAFT", "ISSUED", "EXPIRED", "EXTENDED", "EXERCISED")


def dual_cost_view(program):
    """The ``dual_carrying_cost_view`` calculation for the summary endpoint."""
    loan = None
    for candidate in _loans_for(program["id"]):
        loan = candidate
        break

    outstanding_carrying = int(program.get("outstanding_carrying_cost_cents") or 0)
    projected_months = int(program.get("projected_carry_months") or 0)

    if loan is None:
        return {
            "outstanding_carrying_cost_cents": outstanding_carrying,
            "true_cost_cents": outstanding_carrying,
            "amortized_cost_cents": outstanding_carrying,
            "variance_cents": 0,
        }

    rate = int(loan.get("interest_rate_bps") or 0)
    outstanding_principal = int(loan.get("outstanding_principal_cents") or 0)
    principal = int(loan.get("principal_cents") or 0)

    elapsed_months = whole_months_between(_as_dt(loan.get("originated_at")), current_time())
    drawn_interest = (outstanding_principal * rate * elapsed_months) // _MONTH_DENOMINATOR
    planned_interest = (principal * rate * projected_months) // _MONTH_DENOMINATOR

    true_cost = outstanding_carrying + drawn_interest
    amortized_cost = outstanding_carrying + planned_interest

    return {
        "outstanding_carrying_cost_cents": outstanding_carrying,
        "true_cost_cents": true_cost,
        "amortized_cost_cents": amortized_cost,
        "variance_cents": true_cost - amortized_cost,
    }


def _loans_for(program_id):
    from store import db

    return db.by_field("interim_loans", "bridge_program_id", program_id)


def _as_dt(value):
    """Parse a stored ISO-8601 instant back into an aware datetime."""
    from timeutil import parse_iso

    return parse_iso(value) if isinstance(value, str) else value
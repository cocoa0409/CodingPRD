"""Purchase capacity -- the two readings of the same equity (PRD 3.2).

Both readings begin from the same equity figure -- the departing property's
appraised value minus its mortgage payoff -- apply a base ratio crediting 7000
basis points, and add a condition credit earned by the departing home's state of
repair.  The credit is zero for a home graded ``D`` and grows by 500 basis points
for each grade above the worst: ``C`` earns 500, ``B`` earns 1000 and ``A`` earns
1500.  The conservative reading stops there; the optimistic reading adds a
further 1000 basis points of market appreciation before applying the ratio.

The PRD states this ladder in prose and pins the numbers, so it supersedes the
scaffold's ``CONDITION_CREDIT_BASE_BPS * (rank - 3)`` expression (the two agree
on every grade, and the PRD is the contract either way).

Either reading is then clamped against income: the capacity may not exceed
``household_income_cents * 50000 // 10000`` -- five times annual income -- and a
floor raises any negative result to zero.  Each division floors and no
intermediate value is rounded.

The ``equity_ratio`` reported alongside the capacity is the net departing equity
divided by the appraised value of the departing home, carried to four decimal
places.
"""

from constants import (
    BASE_EQUITY_RATIO_BPS,
    BPS_DENOMINATOR,
    CONDITION_CREDIT_BPS,
    MARKET_APPRECIATION_BPS,
    PMI_MAX_MULTIPLE,
)
from errors import ERR_INVALID_REQUEST, ApiError


def condition_credit_bps(grade):
    """The per-grade credit ladder: D=0, C=500, B=1000, A=1500."""
    if grade not in CONDITION_CREDIT_BPS:
        raise ApiError(ERR_INVALID_REQUEST, "Unknown condition grade '%s'." % grade)
    return CONDITION_CREDIT_BPS[grade]


def net_equity_cents(property_record):
    """Appraised value less the mortgage payoff owed against the property."""
    return int(property_record.get("appraised_value_cents") or 0) - int(
        property_record.get("mortgage_payoff_cents") or 0
    )


def compute_capacity_cents(homeowner, departing_property, variant_used):
    """The ``purchase_capacity`` calculation."""
    equity = net_equity_cents(departing_property)
    ratio_bps = BASE_EQUITY_RATIO_BPS + condition_credit_bps(departing_property["condition_grade"])
    if variant_used == "OPTIMISTIC":
        ratio_bps += MARKET_APPRECIATION_BPS

    capacity = (equity * ratio_bps) // BPS_DENOMINATOR

    ceiling = (int(homeowner.get("household_income_cents") or 0) * PMI_MAX_MULTIPLE) // BPS_DENOMINATOR
    if capacity > ceiling:
        capacity = ceiling
    return max(capacity, 0)


def compute_equity_ratio(departing_property):
    """Net departing equity over appraised value, to four decimal places."""
    appraised = int(departing_property.get("appraised_value_cents") or 0)
    if appraised == 0:
        return 0.0
    equity = net_equity_cents(departing_property)
    return round(equity / appraised, 4)


def household_net_equity(homeowner):
    """Net equity across every ``DEPARTING`` property the household holds.

    Used to recompute ``Homeowner.departing_equity_cents`` on qualification
    approval: the PRD says equity is recomputed from the approved qualification,
    so this sums the household's departing homes rather than its appraised
    values at large.
    """
    from store import db

    total = 0
    for record in db.all("properties"):
        if record.get("homeowner_id") == homeowner["id"] and record.get("kind") == "DEPARTING":
            total += net_equity_cents(record)
    return total
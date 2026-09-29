"""Rent schedule selection, the community-services fee and indexed repricing (PRD 3.5, 3.7)."""
from __future__ import annotations

import repo
from calc import bps_of, rhu_int
from decimal import Decimal

# Step two of the fee computation picks the rate from base_rent_cents alone, on
# brackets inclusive at the bottom and exclusive at the top (PRD section 3.7).
FEE_RATE_BREAK_LOW_CENTS = 200000
FEE_RATE_BREAK_HIGH_CENTS = 320000
FEE_RATE_BPS_LOW_BAND = 350
FEE_RATE_BPS_MID_BAND = 300
FEE_RATE_BPS_HIGH_BAND = 250

PRODUCT_SURCHARGE_CENTS = {
    "DETACHED": 4500,
    "COTTAGE": 3000,
    "TOWNHOME": 2000,
}

# The indexed step never moves the rent by more than 200 dollars in either direction.
RENT_STEP_CLAMP_CENTS = 20000


def fee_rate_bps(base_rent_cents):
    if base_rent_cents < FEE_RATE_BREAK_LOW_CENTS:
        return FEE_RATE_BPS_LOW_BAND
    if base_rent_cents < FEE_RATE_BREAK_HIGH_CENTS:
        return FEE_RATE_BPS_MID_BAND
    return FEE_RATE_BPS_HIGH_BAND


def community_services_fee_cents(base_rent_cents, product_type):
    """base_rent * rate / 10000 rounded half up, plus the flat product surcharge."""
    return bps_of(base_rent_cents, fee_rate_bps(base_rent_cents)) \
        + PRODUCT_SURCHARGE_CENTS[product_type]


def _schedule_rank(schedule):
    """effective_from descending, then created_at descending."""
    return (schedule["_effective_from"], schedule["_created"], schedule["_seq"])


def select_pricing_schedule(community, product_type, start_date):
    """The candidate set for a draft: PUBLISHED, same product type, effective at or
    before the lease start_date; ranked effective_from then created_at descending."""
    candidates = [
        s for s in repo.schedules_of_community(community)
        if s["product_type"] == product_type
        and s["status"] == "PUBLISHED"
        and s["_effective_from"] <= start_date
    ]
    if not candidates:
        return None
    return max(candidates, key=_schedule_rank)


def published_schedule(community, product_type):
    """The community's currently PUBLISHED schedule for one product type."""
    matches = [s for s in repo.schedules_of_community(community)
               if s["product_type"] == product_type and s["status"] == "PUBLISHED"]
    if not matches:
        return None
    return max(matches, key=_schedule_rank)


def baseline_schedule(community, product_type):
    """The indexing baseline: every schedule for the pair, ranked effective_from
    descending and then created_at descending, regardless of status."""
    matches = [s for s in repo.schedules_of_community(community)
               if s["product_type"] == product_type]
    if not matches:
        return None
    return max(matches, key=_schedule_rank)


def latest_review(community, product_type):
    """The most recent absorption review for the pair, ranked window_end descending
    and then created_at descending."""
    matches = [r for r in repo.reviews_of_community(community)
               if r["product_type"] == product_type]
    if not matches:
        return None
    return max(matches, key=lambda r: (r["_window_end"], r["_created"], r["_seq"]))


def repricing_step_cents(baseline_rent_cents, growth_bps):
    """Rounded first, clamped second -- the order is part of the specification."""
    step = rhu_int(Decimal(baseline_rent_cents) * Decimal(growth_bps) / Decimal(10000))
    if step > RENT_STEP_CLAMP_CENTS:
        return RENT_STEP_CLAMP_CENTS
    if step < -RENT_STEP_CLAMP_CENTS:
        return -RENT_STEP_CLAMP_CENTS
    return step

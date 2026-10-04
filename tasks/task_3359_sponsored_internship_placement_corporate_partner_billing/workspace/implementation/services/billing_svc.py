"""Placement fee calculation (PRD 3.7, scaffold `placement_fee`).

Pinned evaluation order, both variants:
  1. supervision_credit_cents = min(supervision_hours_per_week * 2500, 50000)
  2. base_cents               = 200000 + supervision_credit_cents
  3. tiered_cents             = round_half_up(base_cents * TIER_MULTIPLIER[tier])
  4. duration_factor          = window_days / 180        (exact-day window)
  5. placement_fee_cents      = round_half_up(tiered_cents * duration_factor)
"""

import db
from services.rounding import Decimal, round_cents, round_half_up

TIER_MULTIPLIER = {
    "TIER_A": Decimal("1.25"),
    "TIER_B": Decimal("1.10"),
    "TIER_C": Decimal("1.00"),
}

BASE_CENTS = 200000
SUPERVISION_CREDIT_PER_HOUR_CENTS = 2500
SUPERVISION_CREDIT_MAX_CENTS = 50000
FULL_DURATION_MIN_DAYS = 168
SCHEDULED_DURATION_DAYS = 180


def supervision_credit_cents(supervision_hours_per_week):
    raw = Decimal(int(supervision_hours_per_week)) * Decimal(SUPERVISION_CREDIT_PER_HOUR_CENTS)
    return min(raw, Decimal(SUPERVISION_CREDIT_MAX_CENTS))


def tiered_base_cents(agreement):
    base = Decimal(BASE_CENTS) + supervision_credit_cents(agreement["supervision_hours_per_week"])
    multiplier = TIER_MULTIPLIER.get(agreement["fee_tier"], TIER_MULTIPLIER["TIER_C"])
    return round_half_up(base * multiplier, 0)


def placement_fee_cents(agreement, window_start, window_end):
    """Exact-day-window variant: the fee is strictly proportional to the window."""
    tiered = tiered_base_cents(agreement)
    window_days = (window_end.date() - window_start.date()).days
    duration_factor = Decimal(window_days) / Decimal(SCHEDULED_DURATION_DAYS)
    return round_cents(tiered * duration_factor)


def fee_for_agreement_window(agreement):
    return placement_fee_cents(agreement, agreement["start_date"], agreement["end_date"])


def partner_of_agreement(agreement):
    if agreement is None:
        return None
    return db.get("partners", agreement["partner_id"])


def partner_of_placement(placement):
    if placement is None:
        return None
    return partner_of_agreement(db.get("agreements", placement["agreement_id"]))

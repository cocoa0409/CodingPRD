"""Cascade chains (PRD 2.7).

Every link of a chain fires inside the request that triggered it, and each
secondary resource it mutates has its `updated_at` refreshed and its `version`
incremented exactly as if it had been written directly.
"""

from services import derive
from store import store


# ---------------------------------------------------------------------------
# avail inventory cycle (PRD 3.4)
# ---------------------------------------------------------------------------
def sync_forecast(forecast):
    """Called whenever an avail's held inventory changed.

    Availability is a live subtraction, so this only has to settle the
    PUBLISHED <-> EXHAUSTED cycle and stamp the mutation.
    """
    available = derive.available_impressions(forecast)
    if forecast["status"] == "PUBLISHED" and available <= 0:
        forecast["status"] = "EXHAUSTED"
    elif forecast["status"] == "EXHAUSTED" and available > 0:
        forecast["status"] = "PUBLISHED"
    store.touch(forecast)
    return forecast


# ---------------------------------------------------------------------------
# plan structure (PRD 3.3, 3.6)
# ---------------------------------------------------------------------------
def lock_allocations(campaign):
    """DRAFT -> LOCKED on client approval; already-locked lines untouched."""
    for alloc in derive.allocations_of(campaign["id"]):
        if alloc["status"] == "DRAFT":
            alloc["status"] = "LOCKED"
            store.touch(alloc)


def unlock_allocations(campaign):
    """LOCKED -> DRAFT; allocations already at DRAFT are left completely alone."""
    for alloc in derive.allocations_of(campaign["id"]):
        if alloc["status"] == "LOCKED":
            alloc["status"] = "DRAFT"
            store.touch(alloc)


def touch_allocation_of_buy(buy):
    """Link 1: the buy's channel allocation had its committed total recomputed."""
    alloc = store.allocations.get(buy["channel_allocation_id"])
    if alloc is not None:
        store.touch(alloc)
    return alloc


def recompute_plan_posture(campaign):
    """Links 3 and 4: posture recompute, and the automatic replan pushdown."""
    posture = derive.campaign_plan_posture(campaign)
    if posture == "REPLAN_REQUIRED" and campaign["plan_status"] == "APPROVED":
        campaign["plan_status"] = "REVISION_REQUIRED"
        unlock_allocations(campaign)
    store.touch(campaign)
    return posture


def commitment_chain(buy):
    """The full plan-side chain a placement or a rights exercise triggers."""
    touch_allocation_of_buy(buy)
    campaign = store.campaigns.get(buy["campaign_id"])
    if campaign is not None:
        recompute_plan_posture(campaign)
    return campaign


# ---------------------------------------------------------------------------
# stewardship (PRD 3.8)
# ---------------------------------------------------------------------------
def settle_open_shortfall(buy):
    """After a make-good is scheduled or waived the buy may be made good."""
    if (
        derive.open_shortfall_impressions(buy) == 0
        and buy["stewardship_status"] == "UNDER_DELIVERED"
    ):
        buy["stewardship_status"] = "MADE_GOOD"
    store.touch(buy)


# ---------------------------------------------------------------------------
# settlement (PRD 3.9)
# ---------------------------------------------------------------------------
def advance_settlement(buy, target):
    """One settlement-axis hop; every hop increments the buy's version."""
    buy["settlement_status"] = target
    if target == "REMITTED" and buy["buy_status"] == "COMPLETED":
        buy["buy_status"] = "CLOSED"
    store.touch(buy)

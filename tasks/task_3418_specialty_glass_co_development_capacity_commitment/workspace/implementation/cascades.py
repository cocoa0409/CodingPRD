"""Cascade helpers (PRD 2.9): ordered multi-hop side effects across entities.

Every entity mutated by any hop gets its version incremented and updated_at
refreshed, exactly as if mutated directly.
"""
from datetime import timedelta

import clock
import constants as C
import store
from calculations import (
    supply_coverage_value,
    campaign_days,
    changeover_total_cents,
    unit_cost_cents,
    realized_yield_value,
)

_DEMOTION = {"STRATEGIC": "STANDARD", "STANDARD": "PROBATION", "PROBATION": "PROBATION"}


def demote_maker(maker):
    """One standing step down; PROBATION unchanged (PRD 3.1)."""
    new_tier = _DEMOTION[maker["standing_tier"]]
    if new_tier != maker["standing_tier"]:
        maker["standing_tier"] = new_tier
        store.touch(maker)


def breach_check_commitments(commitment_ids):
    """Cascade hop: recompute supply_coverage for still-SECURED commitments;
    below CONST.SUPPLY_COVERAGE_MIN -> BREACH_WATCH with deadline and demotion."""
    for cid in commitment_ids:
        c = store.commitments.get(cid)
        if c is None or c["status"] != "SECURED":
            continue
        c["supply_coverage"] = supply_coverage_value(c, store.allocations.values())
        store.touch(c)
        if c["supply_coverage"] < C.SUPPLY_COVERAGE_MIN:
            c["status"] = "BREACH_WATCH"
            c["breach_deadline"] = clock.now() + timedelta(days=C.BREACH_GRACE_DAYS)
            maker = store.device_makers.get(c["device_maker_id"])
            if maker is not None:
                demote_maker(maker)


def release_reserved_allocations(campaign):
    """Release every RESERVED allocation of a campaign, restoring its
    unallocated_units. Returns affected commitment ids (deduped)."""
    affected = []
    released_any = False
    for a in list(store.allocations.values()):
        if a["campaign_id"] == campaign["id"] and a["status"] == "RESERVED":
            a["status"] = "RELEASED"
            store.touch(a)
            campaign["unallocated_units"] += a["units"]
            released_any = True
            if a["commitment_id"] not in affected:
                affected.append(a["commitment_id"])
    if released_any:
        store.touch(campaign)
    return affected


def cancel_campaigns_batched(campaigns_to_cancel):
    """Campaign cancellation cascade (retire / terminate / checkpoint):
    hop 1 cancels all SCHEDULED campaigns, hop 2 releases their RESERVED
    allocations restoring headroom, hops 3-4 breach-watch + demotion."""
    affected = []
    for camp in campaigns_to_cancel:
        camp["status"] = "CANCELLED"
        store.touch(camp)
    for camp in campaigns_to_cancel:
        for cid in release_reserved_allocations(camp):
            if cid not in affected:
                affected.append(cid)
    breach_check_commitments(affected)


def release_commitment(commitment, release_allocations=True):
    """Commitment release: status RELEASED, refund remaining prepayment into
    the refunded bucket, and (optionally) release its RESERVED allocations
    restoring each affected campaign's unallocated_units."""
    commitment["status"] = "RELEASED"
    commitment["prepayment_refunded_cents"] += commitment["prepayment_remaining_cents"]
    commitment["prepayment_remaining_cents"] = 0
    store.touch(commitment)
    if not release_allocations:
        return
    touched_campaigns = []
    for a in list(store.allocations.values()):
        if a["commitment_id"] == commitment["id"] and a["status"] == "RESERVED":
            a["status"] = "RELEASED"
            store.touch(a)
            camp = store.campaigns[a["campaign_id"]]
            camp["unallocated_units"] += a["units"]
            if camp["id"] not in touched_campaigns:
                touched_campaigns.append(camp["id"])
    for cid in touched_campaigns:
        store.touch(store.campaigns[cid])


def prior_campaign(campaign):
    """The campaign on the same tank with the latest end_date <= this one's
    start_date among SCHEDULED/RUNNING/COMPLETED/ABORTED (changeover basis)."""
    best = None
    for c in store.campaigns.values():
        if c["id"] == campaign["id"] or c["tank_id"] != campaign["tank_id"]:
            continue
        if c["status"] not in ("SCHEDULED", "RUNNING", "COMPLETED", "ABORTED"):
            continue
        if c["end_date"] <= campaign["start_date"]:
            if best is None or c["end_date"] > best["end_date"]:
                best = c
    return best


def finalize_campaign(campaign):
    """Completion/abort bookkeeping: recompute realized_yield from production
    records and compute final_unit_cost_cents per the final cost variant.
    final_unit_cost_cents stays null when no production records exist."""
    good = campaign["cumulative_good_units"]
    scrap = campaign["cumulative_scrap_units"]
    campaign["realized_yield"] = realized_yield_value(good, scrap)
    if good + scrap <= 0:
        campaign["final_unit_cost_cents"] = None
        return
    composition = store.compositions[campaign["composition_id"]]
    days = campaign_days(campaign["start_date"], campaign["end_date"])
    changeover = changeover_total_cents(
        prior_campaign(campaign), campaign["composition_id"], days
    )
    campaign["final_unit_cost_cents"] = unit_cost_cents(
        composition["complexity_multiplier"],
        good,
        campaign["realized_yield"],
        changeover,
    )

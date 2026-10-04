"""Cascading side effects, settlement, and the logical-clock sweep."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import DB
from common import base_resource, touch, parse_dt, iso_now, dt_to_iso
import calc


def cancel_booking(booking):
    if booking["status"] == "HELD":
        booking["refund_cents"] = 0
        booking["status"] = "CANCELLED"
        touch(booking)
    elif booking["status"] == "CONFIRMED":
        booking["refund_cents"] = booking["line_total_cents"]
        booking["status"] = "CANCELLED"
        touch(booking)


def cancel_show(show):
    if show["status"] in ("COMPLETED", "CANCELLED"):
        return
    show["status"] = "CANCELLED"
    touch(show)
    for b in DB.bookings.values():
        if b["show_id"] == show["id"] and b["status"] in ("HELD", "CONFIRMED"):
            cancel_booking(b)


def recompute_tech_readiness():
    """tech_readiness = DEGRADED if any required system kind is DEGRADED/OFFLINE."""
    degraded_kinds = {s["kind"] for s in DB.venue_systems.values() if s["status"] in ("DEGRADED", "OFFLINE")}
    for show in DB.shows.values():
        if show["status"] in ("COMPLETED", "CANCELLED"):
            continue
        # every show requires all three system kinds to be healthy
        show["tech_readiness"] = "DEGRADED" if degraded_kinds else "READY"


def system_health_cascade(system):
    """Apply DEGRADED/OFFLINE transitions based on consecutive_failed_windows."""
    cfw = system["consecutive_failed_windows"]
    if cfw >= 3 and system["status"] != "OFFLINE":
        system["status"] = "OFFLINE"
        touch(system)
        # abort any RENDERING batch
        for batch in DB.render_batches.values():
            if batch["status"] == "RENDERING":
                fail_batch(batch)
        recompute_tech_readiness()
    elif cfw >= 2 and system["status"] in ("ONLINE", "MAINTENANCE"):
        system["status"] = "DEGRADED"
        touch(system)
        recompute_tech_readiness()


def fail_batch(batch):
    if batch["status"] in ("OPEN", "RENDERING", "SETTLING"):
        batch["status"] = "FAILED"
        touch(batch)
        for aid in batch["submitted_asset_ids"]:
            asset = DB.assets.get(aid)
            if asset and asset["status"] == "RENDERING":
                asset["status"] = "QC_FAILED"
                touch(asset)


def run_settlement(show):
    """Create the Settlement record and accrue impressions."""
    gross = sum(Decimal(str(b["line_total_cents"])) for b in DB.bookings.values()
                if b["show_id"] == show["id"] and b["status"] == "CONFIRMED")
    refunds = sum(Decimal(str(b["refund_cents"])) for b in DB.bookings.values()
                  if b["show_id"] == show["id"] and b["status"] == "CANCELLED")
    net = gross - refunds
    campaigns = calc.overlapping_active_campaigns(show)
    n = max(1, len(campaigns))
    payout = Decimal(0)
    for c in campaigns:
        share = (net * calc.SPONSOR_POOL_PCT / n).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        payout += share
    if payout > net:
        payout = net
    settlement = base_resource()
    settlement.update({
        "show_id": show["id"],
        "gross_cents": float(gross),
        "refunds_cents": float(refunds),
        "net_cents": float(net),
        "sponsor_payout_cents": float(payout),
        "venue_retain_cents": float(net - payout),
        "status": "FINAL",
    })
    DB.settlements[settlement["id"]] = settlement
    show["settlement_snapshot_id"] = settlement["id"]
    # accrue impressions
    for c in campaigns:
        c["delivered_impressions"] += calc.calc_impressions_for_show(c, show)
        touch(c)
    return settlement


def complete_show(show):
    show["status"] = "COMPLETED"
    touch(show)
    run_settlement(show)


def complete_campaign(campaign):
    campaign["status"] = "COMPLETED"
    under = max(0, campaign["contracted_impressions"] - campaign["delivered_impressions"])
    campaign["under_delivery"] = under
    campaign["make_good_credits"] = calc.MAKE_GOOD_MULTIPLIER * under
    touch(campaign)
    sponsor = DB.sponsors.get(campaign["sponsor_id"])
    if sponsor:
        sponsor["active_campaign_count"] = max(0, sponsor["active_campaign_count"] - 1)
        touch(sponsor)


def sweep_clock():
    """Apply all pending time-based transitions at the current logical clock."""
    now = DB.clock

    # Render batches RENDERING -> SETTLING when render_minutes elapsed
    for batch in list(DB.render_batches.values()):
        if batch["status"] == "RENDERING" and batch.get("render_started_at"):
            started = parse_dt(batch["render_started_at"])
            if now >= started + timedelta(minutes=batch.get("render_minutes", 0)):
                batch["status"] = "SETTLING"
                touch(batch)

    # Confirmed shows -> COMPLETED when clock >= start + length
    for show in list(DB.shows.values()):
        if show["status"] == "CONFIRMED":
            end = parse_dt(show["start_time"]) + timedelta(minutes=show["length_minutes"])
            if now >= end:
                complete_show(show)

    # ACTIVE campaigns -> COMPLETED when clock >= end_time
    for campaign in list(DB.campaigns.values()):
        if campaign["status"] == "ACTIVE" and now >= parse_dt(campaign["end_time"]):
            complete_campaign(campaign)

    # Expire HELD bookings past 15-minute hold
    for booking in list(DB.bookings.values()):
        if booking["status"] == "HELD":
            held_at = parse_dt(booking["held_at"])
            if now >= held_at + timedelta(minutes=calc.HOLD_MINUTES):
                booking["status"] = "CANCELLED"
                booking["refund_cents"] = 0
                touch(booking)

    # SCHEDULED maintenance windows -> ACTIVE when start reached
    for window in list(DB.maintenance_windows.values()):
        if window["status"] == "SCHEDULED" and now >= parse_dt(window["start_time"]):
            window["status"] = "ACTIVE"
            touch(window)
            system = DB.venue_systems.get(window["venue_system_id"])
            if system and system["status"] == "ONLINE":
                system["status"] = "MAINTENANCE"
                touch(system)

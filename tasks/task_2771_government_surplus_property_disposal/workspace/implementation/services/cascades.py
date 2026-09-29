"""Multi-hop atomic cascades (PRD sections 2.9, 3.7, 3.8)."""
import db as store
from db import db
from services import rollups


def cancel_open_cycles(asset, ctx):
    """Destruction hop: OPEN ScreeningCycle -> CANCELLED and its open requests
    -> DENIED with denial_reason CYCLE_CANCELLED."""
    for cycle in rollups.cycles_of_asset(asset["id"]):
        if cycle["status"] != "OPEN":
            continue
        cycle["status"] = "CANCELLED"
        for req in rollups.requests_of_cycle(cycle["id"]):
            if req["status"] in ("SUBMITTED", "INFO_REQUESTED"):
                req["status"] = "DENIED"
                req["denial_reason"] = "CYCLE_CANCELLED"
                ctx.touch(req)
        rollups.recompute_cycle_open_requests(cycle, ctx)
        ctx.touch(cycle)


def cancel_live_lots(asset, ctx):
    """Destruction hop: DRAFT/OPEN lots -> CANCELLED, their ACTIVE/WINNING bids
    -> RETRACTED, venue active_lot_count recomputed."""
    for lot in rollups.lots_of_asset(asset["id"]):
        if lot["status"] not in ("DRAFT", "OPEN"):
            continue
        lot["status"] = "CANCELLED"
        for bid in rollups.bids_of_lot(lot["id"]):
            if bid["status"] in ("ACTIVE", "WINNING"):
                bid["status"] = "RETRACTED"
                ctx.touch(bid)
                bidder = db.bidders.get(bid["bidder_id"])
                if bidder is not None:
                    rollups.recompute_bidder_wins(bidder, ctx)
        rollups.recompute_lot(lot, ctx)
        ctx.touch(lot)
        venue = db.venues.get(lot["venue_id"])
        if venue is not None:
            rollups.recompute_venue(venue, ctx)


def destroy_asset(asset, ctx):
    """Destruction cascade driven by a DEMILITARIZATION/DESTROY certificate."""
    asset["disposition_status"] = "DESTROYED"
    asset["clearance_status"] = "CLEARED"
    ctx.touch(asset)
    cancel_open_cycles(asset, ctx)
    cancel_live_lots(asset, ctx)
    rollups.bubble_up_turn_in(db.turn_ins.get(asset["turn_in_id"]), ctx)


def debar_bidder(bidder, ctx):
    """Five-hop debarment cascade."""
    bidder["status"] = "DEBARRED"
    ctx.touch(bidder)
    lost_winning = []
    affected_lots = []
    for bid in rollups.bids_of_bidder(bidder["id"]):
        if bid["status"] not in ("ACTIVE", "WINNING"):
            continue
        was_winning = bid["status"] == "WINNING"
        bid["status"] = "RETRACTED"
        ctx.touch(bid)
        lot = db.lots.get(bid["auction_lot_id"])
        if lot is None:
            continue
        if lot not in affected_lots:
            affected_lots.append(lot)
        if was_winning and lot not in lost_winning:
            lost_winning.append(lot)
    rollups.recompute_bidder_wins(bidder, ctx)
    for lot in sorted(affected_lots, key=store.sort_key):
        if lot in lost_winning and lot["status"] == "CLOSED_MET":
            lot["status"] = "CLOSED_NO_SALE"
            asset = db.assets.get(lot["asset_id"])
            for invoice in rollups.invoices_of_lot(lot["id"]):
                if invoice["status"] not in ("ISSUED", "PARTIALLY_PAID"):
                    continue
                invoice["status"] = "VOIDED"
                invoice["void_reason"] = "WINNER_DEBARRED"
                returned = invoice["deposit_applied_cents"]
                if returned:
                    holder = db.bidders.get(invoice["bidder_id"])
                    if holder is not None:
                        holder["deposit_applied_cents"] -= returned
                        holder["deposit_held_cents"] += returned
                        ctx.touch(holder)
                invoice["deposit_applied_cents"] = 0
                invoice["amount_paid_cents"] = 0
                rollups.refresh_invoice_balance(invoice)
                ctx.touch(invoice)
            if asset is not None and asset["disposition_status"] == "SOLD":
                asset["disposition_status"] = "AUCTION_ELIGIBLE"
                ctx.touch(asset)
        rollups.recompute_lot(lot, ctx)
        ctx.touch(lot)

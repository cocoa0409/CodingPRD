"""Derived-field recomputation and shared lookups.

Every roll-up is a full recompute over the current row set, never an
incremental delta (PRD section 2.9).
"""
import db as store
from db import db, by_created
from errors import ApiError
from services import calc

TERMINAL_DISPOSITIONS = ("RELEASED", "RETAINED", "DESTROYED")


def fetch(collection, row_id, error_id):
    row = collection.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(error_id)
    return row


# ---------------------------------------------------------------------------
# child selectors
# ---------------------------------------------------------------------------

def assets_of_turn_in(turn_in_id):
    return by_created([a for a in db.assets.values() if a["turn_in_id"] == turn_in_id])


def assessments_of_asset(asset_id):
    return [a for a in db.assessments.values() if a["asset_id"] == asset_id]


def certificates_of_asset(asset_id):
    return by_created([c for c in db.certificates.values() if c["asset_id"] == asset_id])


def lots_of_asset(asset_id):
    return by_created([l for l in db.lots.values() if l["asset_id"] == asset_id])


def lots_of_venue(venue_id):
    return by_created([l for l in db.lots.values() if l["venue_id"] == venue_id])


def bids_of_lot(lot_id):
    return by_created([b for b in db.bids.values() if b["auction_lot_id"] == lot_id])


def bids_of_bidder(bidder_id):
    return by_created([b for b in db.bids.values() if b["bidder_id"] == bidder_id])


def requests_of_cycle(cycle_id):
    return by_created([r for r in db.requests.values()
                       if r["screening_cycle_id"] == cycle_id])


def cycles_of_asset(asset_id):
    return by_created([c for c in db.cycles.values() if c["asset_id"] == asset_id])


def live_invoice_of_lot(lot_id):
    """The lot's single non-VOIDED SaleInvoice, if any."""
    rows = by_created([i for i in db.invoices.values()
                       if i["auction_lot_id"] == lot_id and i["status"] != "VOIDED"])
    return rows[-1] if rows else None


def invoices_of_lot(lot_id):
    return by_created([i for i in db.invoices.values() if i["auction_lot_id"] == lot_id])


def distributions_of_lot(lot_id):
    return by_created([d for d in db.distributions.values()
                       if d["auction_lot_id"] == lot_id])


# ---------------------------------------------------------------------------
# recomputation
# ---------------------------------------------------------------------------

def recompute_turn_in(turn_in, ctx):
    children = assets_of_turn_in(turn_in["id"])
    turn_in["asset_count"] = len(children)
    total = 0
    for asset in children:
        if asset["fair_market_value_cents"] is not None:
            total += asset["fair_market_value_cents"]
    turn_in["appraised_total_cents"] = total
    ctx.touch(turn_in)


def revalue_asset(asset, ctx):
    """Re-runs calculations.asset_fair_market_value and stamps superseded flags."""
    governing, ordered = calc.governing_assessment(asset["id"])
    for row in ordered:
        row["superseded"] = row is not governing
    if governing is None:
        return
    if asset["disposition_status"] in ("RETAINED", "DESTROYED"):
        return
    asset["condition_code"] = governing["condition_code"]
    asset["fair_market_value_cents"] = calc.fair_market_value(asset, governing)
    ctx.touch(asset)


def recompute_lot(lot, ctx):
    rows = bids_of_lot(lot["id"])
    high = 0
    count = 0
    for bid in rows:
        if bid["status"] in ("ACTIVE", "WINNING") and bid["amount_cents"] > high:
            high = bid["amount_cents"]
        if bid["status"] in ("ACTIVE", "WINNING", "OUTBID"):
            count += 1
    lot["high_bid_cents"] = high
    lot["bid_count"] = count
    ctx.touch(lot)


def recompute_venue(venue, ctx):
    active = 0
    for lot in lots_of_venue(venue["id"]):
        if lot["status"] in ("DRAFT", "OPEN"):
            active += 1
    venue["active_lot_count"] = active
    ctx.touch(venue)


def recompute_bidder_wins(bidder, ctx):
    wins = 0
    for bid in bids_of_bidder(bidder["id"]):
        if bid["status"] == "WINNING":
            wins += 1
    bidder["winning_lot_count"] = wins
    ctx.touch(bidder)


def count_open_requests(cycle_id):
    open_count = 0
    for req in requests_of_cycle(cycle_id):
        if req["status"] in ("SUBMITTED", "INFO_REQUESTED"):
            open_count += 1
    return open_count


def recompute_cycle_open_requests(cycle, ctx):
    open_count = 0
    for req in requests_of_cycle(cycle["id"]):
        if req["status"] in ("SUBMITTED", "INFO_REQUESTED"):
            open_count += 1
    cycle["open_request_count"] = open_count
    ctx.touch(cycle)


def recompute_agency_ledger(agency, ctx):
    rows = by_created([d for d in db.distributions.values()
                       if d["beneficiary_agency_id"] == agency["id"]
                       and d["status"] == "POSTED"])
    total = 0
    for row in rows:
        total += row["net_to_agency_cents"]
    agency["proceeds_account_balance_cents"] = total
    agency["posted_distribution_count"] = len(rows)
    ctx.touch(agency)


def refresh_invoice_balance(invoice):
    invoice["balance_due_cents"] = invoice["total_due_cents"] - invoice["amount_paid_cents"]


def bubble_up_turn_in(turn_in, ctx):
    """TurnIn ACCEPTED -> CLOSED once every child asset is terminal."""
    if turn_in is None or turn_in["status"] != "ACCEPTED":
        return
    children = assets_of_turn_in(turn_in["id"])
    for asset in children:
        if asset["disposition_status"] not in TERMINAL_DISPOSITIONS:
            return
    turn_in["status"] = "CLOSED"
    ctx.touch(turn_in)


def evaluate_clearance(asset, ctx):
    """Recomputes the clearance axis from the certificates on file."""
    if asset["clearance_status"] == "NOT_REQUIRED":
        return
    verified = set()
    for cert in certificates_of_asset(asset["id"]):
        if cert["serials_verified"]:
            verified.add(cert["cert_type"])
    complete = True
    if asset["is_data_bearing"] and "DATA_SANITIZATION" not in verified:
        complete = False
    if asset["is_restricted"] and "DEMILITARIZATION" not in verified:
        complete = False
    if complete:
        asset["clearance_status"] = "CLEARED"
        ctx.touch(asset)

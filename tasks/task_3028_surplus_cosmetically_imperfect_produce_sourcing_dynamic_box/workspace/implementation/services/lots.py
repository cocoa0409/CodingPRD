"""§3.1 Sourcing, make-ready and §3.2 Bidding / Award fork-join."""

import clock
import rules
import store
from common import ApiError
from services import suppliers

# §3.1's award shelf-life matrix. The scaffold names the matrix and the
# recomputation trigger but pins no figures; these are the values in force.
AWARD_SHELF_LIFE_DAYS = {
    "FRUIT": 14,
    "VEGETABLE": 14,
    "DAIRY": 21,
    "BAKERY": 5,
    "PANTRY": 180,
    "BEVERAGE": 120,
}

# §3.2's subscription shelf-life floor.
SUBSCRIPTION_MIN_SHELF_LIFE_DAYS = 7


def lot_of(lot_id):
    lot = store.SUPPLY_LOTS.get(lot_id)
    if lot is None:
        raise ApiError("ERR_SUPPLY_LOT_NOT_FOUND", 404,
                       "No SupplyLot exists with the given id.")
    return lot


def supplier_of(supplier_id):
    supplier = store.SUPPLIERS.get(supplier_id)
    if supplier is None:
        raise ApiError("ERR_SUPPLIER_NOT_FOUND", 404,
                       "No Supplier exists with the given id.")
    return supplier


def recompute_shelf_life(lot):
    """§3.1: whole days from harvest_date to expiry_date, neither boundary."""
    try:
        harvest = clock.parse_date(lot["harvest_date"])
        expiry = clock.parse_date(lot["expiry_date"])
    except ValueError:
        return lot.get("shelf_life_days", 0)
    lot["shelf_life_days"] = max(0, (expiry - harvest).days)
    return lot["shelf_life_days"]


def recompute_expiry_from_award_matrix(lot):
    """The award rewrite of the supplier's declared expiry (§3.2)."""
    days = AWARD_SHELF_LIFE_DAYS[lot["category"]]
    harvest = clock.parse_date(lot["harvest_date"])
    lot["expiry_date"] = clock.plus_days(harvest, days).isoformat()
    lot["shelf_life_days"] = days
    return days


def derived_lot(lot):
    """Refresh the computed fields that are read on every response."""
    recompute_shelf_life(lot)
    lot["preference_eligible"] = bool(lot.get("preference_tags"))
    lot["billing_weight_grams"] = rules.billing_weight_grams(lot)
    lot["display_price_cents"] = rules.display_price_cents(lot)
    return lot


def refresh_all_lot_derivations():
    rules.rebuild_primary_quotes()
    for lot in store.SUPPLY_LOTS.values():
        derived_lot(lot)


# --- make-ready (§3.1) -------------------------------------------------------

def make_ready(lot, quality_outcome, arrived_at):
    """Move a lot through make-ready quality inspection."""
    supplier = store.SUPPLIERS.get(lot["supplier_id"])
    if supplier is None or supplier.get("status") != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an ACTIVE supplier's lot can clear make-ready.")
    if lane_has_under_review_claim(lot["fulfillment_center_id"]):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "An open investigation at this lane blocks new throughput.")
    if lot["status"] in ("EXPIRED", "DEPLETED", "COMMITTED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "The lot is not in a state that admits make-ready.")
    # §3.1 / §3.9 rung 5: make-ready is the PENDING_INSPECTION quality gate.
    # A lot whose quality dimension has already left PENDING_INSPECTION — a
    # REJECTED lot, or one under INVESTIGATION — is not in a state that admits
    # another inspection.
    if lot.get("quality_status") != "PENDING_INSPECTION":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "The lot's quality status does not admit make-ready.")

    if quality_outcome == "PASS":
        assert_substantiated(lot)
        lot["quality_status"] = "PASS"
        lot["status"] = "READY"
        lot["_accepted"] = True
        lot["_on_time"] = _arrived_on_time(lot)
    else:
        lot["quality_status"] = "REJECTED"

    derived_lot(lot)
    store.touch(lot)
    suppliers.recompute_for_lot(lot)
    return lot


def _arrived_on_time(lot):
    """§3.1: on-time exactly when arrived_at is not after the promised ready_date."""
    arrived = lot.get("arrived_at")
    if not arrived:
        return False
    return clock.parse_instant(arrived).date() <= clock.parse_date(lot["ready_date"])


def assert_substantiated(lot):
    """§2.9 / §3.9 rung 10: a quote on file must actually substantiate."""
    has_quote = any(q["supply_lot_id"] == lot["id"]
                    for q in store.CONVENTIONAL_QUOTES.values())
    if not has_quote:
        return
    if rules.substantiation_status_for(lot) != "SUBSTANTIATED":
        raise ApiError("ERR_SUBSTANTIATION_REQUIRED", 422,
                       "The lot's conventional-quote evidence does not substantiate.")


def lane_has_under_review_claim(center_id):
    for claim in store.QUALITY_CLAIMS.values():
        if claim["status"] != "UNDER_REVIEW":
            continue
        lot = store.SUPPLY_LOTS.get(claim.get("supply_lot_id"))
        if lot is not None and lot["fulfillment_center_id"] == center_id:
            return True
    return False


# --- bidding -----------------------------------------------------------------

def withdraw_bid(bid):
    if bid["status"] not in ("PENDING", "SHORTLISTED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "A bid in this state cannot be withdrawn.")
    if bid["status"] == "SHORTLISTED" and bid["_award_executed"]:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "The award has already run; the shortlist is frozen.")
    bid["status"] = "WITHDRAWN"
    store.touch(bid)
    return bid


# --- award (§3.2) ------------------------------------------------------------

def award(lot, bidder_quota):
    """The fork-join. Returns the lot."""
    bids = [b for b in store.SOURCING_BIDS.values()
            if b["supply_lot_id"] == lot["id"]]

    if lot["status"] != "AWARDED":
        # The erroneous attempt is recorded as a non-selected outcome; the lot
        # itself is left with no mutation whatsoever.
        for bid in bids:
            if bid["status"] == "PENDING":
                bid["status"] = "NOT_SELECTED"
                store.touch(bid)
        return lot

    if bidder_quota == 1:
        return award_single(lot, bids)
    return award_ranked(lot, bids, bidder_quota)


def award_single(lot, bids):
    pending = [b for b in bids if b["status"] == "PENDING"
               and supplier_is_active(b)]
    if pending:
        chosen = sorted(pending, key=lambda b: (b["created_at"], b["_seq"]))[0]
        chosen["status"] = "SHORTLISTED"
        store.touch(chosen)
        # A shortlist with exactly one member is immediately joined through.
        chosen["status"] = "SELECTED"
        store.touch(chosen)
        lot["status"] = "READY"
    finish_award(lot, bids)
    return lot


def award_ranked(lot, bids, bidder_quota):
    """Up to ``bidder_quota`` bids are shortlisted, then the shortlist resolves.

    The shortlist is ranked by the §2.8 selector ordering: preference-tag
    specificity descending, then the source lot's shelf life descending, then
    the offered unit cost ascending, then first-created. The highest-ranked
    member joins to SELECTED and the tie-break that settles equal bidders is
    their own created_at ascending, so no identifier participates.
    """
    pending = [b for b in bids if b["status"] == "PENDING"
               and supplier_is_active(b)]
    ordered = rank_bids(pending)
    shortlist = ordered[:bidder_quota]
    for bid in shortlist:
        bid["status"] = "SHORTLISTED"
        store.touch(bid)
    if shortlist:
        winner = rank_bids(shortlist)[0]
        winner["status"] = "SELECTED"
        store.touch(winner)
        lot["status"] = "READY"
        for bid in shortlist:
            if bid is winner:
                continue
            bid["status"] = "NOT_SELECTED"
            store.touch(bid)
    finish_award(lot, bids)
    return lot


def rank_bids(bids):
    """§2.8: specificity DESC, shelf life DESC, bid cost ASC, created_at ASC."""
    def key(bid):
        lot = store.SUPPLY_LOTS.get(bid["supply_lot_id"])
        specificity = len(lot.get("preference_tags") or []) if lot else 0
        shelf_life = lot["shelf_life_days"] if lot else 0
        return (-specificity, -shelf_life, bid["bid_unit_cost_cents"],
                bid["created_at"], bid["_seq"])
    return sorted(bids, key=key)


def finish_award(lot, bids):
    """Every remaining PENDING bid is NOT_SELECTED; the shortlist is frozen.

    A shortlisted bid that lost the join is also NOT_SELECTED — the fork-join
    resolves the shortlist rather than leaving it open. Only the shortlisted
    losers are touched here, since the ranked branch already moved them.
    """
    for bid in bids:
        if bid["status"] == "PENDING":
            bid["status"] = "NOT_SELECTED"
        bid["_award_executed"] = True
        store.touch(bid)
    lot["_award_executed"] = True
    store.touch(lot)


def supplier_is_active(bid):
    supplier = store.SUPPLIERS.get(bid["supplier_id"])
    return supplier is not None and supplier.get("status") == "ACTIVE"


def create_bid(lot, supplier, unit_cost_cents, quantity_offered):
    """Record a bid. §3.1: a lot is always born out of a relationship."""
    bid = store.new_row({
        "supply_lot_id": lot["id"],
        "supplier_id": supplier["id"],
        "bid_unit_cost_cents": unit_cost_cents,
        "quantity_offered": quantity_offered,
        "status": "PENDING",
        "_award_executed": False,
    })
    store.SOURCING_BIDS[bid["id"]] = bid
    return bid


def open_for_bids(lot):
    """QUOTED -> AWARDED: the act of opening a lot to bids (§3.2)."""
    pending = [b for b in store.SOURCING_BIDS.values()
               if b["supply_lot_id"] == lot["id"] and b["status"] == "PENDING"]
    if not pending:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "At least one PENDING bid is required to open a lot.")
    lot["status"] = "AWARDED"
    lot["_status_awarded"] = True
    recompute_expiry_from_award_matrix(lot)
    derived_lot(lot)
    store.touch(lot)
    suppliers.recompute_for_lot(lot)
    return lot


def subscription_shelf_life_cascade(lot):
    """§3.2: a short-shelf awarded lot auto-skips its lane's ACTIVE rows."""
    if lot["shelf_life_days"] >= SUBSCRIPTION_MIN_SHELF_LIFE_DAYS:
        return
    for subscription in store.SUBSCRIPTIONS.values():
        if subscription["home_fulfillment_center_id"] != lot["fulfillment_center_id"]:
            continue
        if subscription["status"] != "ACTIVE":
            continue
        subscription["status"] = "AUTO_SKIPPED"
        subscription["skipped_cycle_index"] = subscription["serving_cycle_index"] + 1
        store.touch(subscription)


def expiring_cascade(lot):
    """§3.1: REJECTED quality expires same-supplier same-lane open lots."""
    affected = []
    for other in store.SUPPLY_LOTS.values():
        if other["supplier_id"] != lot["supplier_id"]:
            continue
        if other["fulfillment_center_id"] != lot["fulfillment_center_id"]:
            continue
        if other["status"] in ("QUOTED", "AWARDED"):
            other["status"] = "EXPIRED"
            store.touch(other)
            affected.append(other)
    if affected:
        suppliers.recompute_for_lot(lot)
    return affected
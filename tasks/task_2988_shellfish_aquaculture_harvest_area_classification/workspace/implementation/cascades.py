"""Cascades (PRD 2.10): the four-hop area-closure cascade, the three-hop seed
rejection cascade, the dealer-suspension shipment hold and the four-hop recall
cascade.  Every cascade runs to completion inside the triggering request and
every row it touches has updated_at refreshed and version advanced.
"""

from datetime import timedelta

from calc import (
    area_authorizations,
    authorization_lots,
    dealer_shipments,
    recompute_lease_gear,
    recompute_open_authorization_count,
    recompute_seed_allocation,
    seed_lot_units,
    unit_authorizations,
)
from core import (
    DEALER_SUSPENSION_STRIKE_THRESHOLD,
    apply_changes,
    db,
)


def _ordered(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["id"]))


def _release_vessel(authorization):
    vessel = db.vessels.get(authorization["vessel_id"])
    if vessel is None:
        return
    apply_changes(
        vessel,
        {"active_authorization_count": vessel["active_authorization_count"] - 1},
    )


def area_closure_cascade(area):
    """Hops 1-4 of PRD 3.1.  Returns the number of authorizations voided."""
    # Hop 1 — void every live authorization snapshotted against this area.
    voided = []
    for auth in _ordered(area_authorizations(area["id"])):
        if auth["status"] in ("ISSUED", "ACTIVE"):
            apply_changes(auth, {"status": "VOIDED", "void_reason": "AREA_CLOSURE"})
            voided.append(auth)

    # Hop 2 — release each voided authorization's vessel and return its gear.
    for auth in voided:
        _release_vessel(auth)
        unit = db.growout_units.get(auth["growout_unit_id"])
        if unit is not None and unit["status"] == "HARVESTING":
            apply_changes(unit, {"status": "DEPLOYED"})

    # Hop 3 — embargo the landed lots of each voided authorization.
    embargoed = []
    for auth in voided:
        for lot in _ordered(authorization_lots(auth["id"])):
            if lot["status"] in ("HARVESTED", "TAGGED"):
                apply_changes(
                    lot, {"status": "EMBARGOED", "embargo_reason": "AREA_CLOSURE"}
                )
                embargoed.append(lot)

    # Hop 4 — drag any CREATED shipment carrying an embargoed lot to HELD.
    for lot in embargoed:
        if lot["shipment_id"] is None:
            continue
        shipment = db.shipments.get(lot["shipment_id"])
        if shipment is not None and shipment["status"] == "CREATED":
            apply_changes(
                shipment, {"status": "HELD", "held_reason": "LOT_EMBARGO"}
            )

    recompute_open_authorization_count(area)
    return len(voided)


def close_area_for_sample_failure(area, eligible_classification, moment):
    """The sweep's own downgrade (PRD 3.2) — classification and harvest_status
    move together, then the area-closure cascade runs."""
    apply_changes(
        area,
        {
            "classification": eligible_classification,
            "harvest_status": "CLOSED_SAMPLE_FAILURE",
            "last_closure_started_at": moment,
            "closure_reopen_eligible_at": moment
            + timedelta(hours=area["rainfall_closure_hours"]),
            "consecutive_clean_samples": 0,
        },
    )
    return area_closure_cascade(area)


def seed_rejection_cascade(seed_lot):
    """Hops 1-3 of PRD 3.5."""
    voided_units = []
    for unit in _ordered(seed_lot_units(seed_lot["id"])):
        if unit["status"] in ("DEPLOYED", "HARVESTING"):
            apply_changes(
                unit, {"status": "VOIDED", "void_reason": "SEED_LOT_REJECTED"}
            )
            voided_units.append(unit)

    # Hop 2 — the voided units give back their gear units and their seed.
    touched_leases = set()
    for unit in voided_units:
        touched_leases.add(unit["lease_id"])
    for lease_id in sorted(touched_leases):
        lease = db.leases.get(lease_id)
        if lease is not None:
            recompute_lease_gear(lease)
    if voided_units:
        recompute_seed_allocation(seed_lot)

    # Hop 3 — void each voided unit's live authorizations.
    touched_areas = set()
    for unit in voided_units:
        for auth in _ordered(unit_authorizations(unit["id"])):
            if auth["status"] in ("ISSUED", "ACTIVE"):
                apply_changes(
                    auth, {"status": "VOIDED", "void_reason": "SEED_LOT_REJECTED"}
                )
                _release_vessel(auth)
                touched_areas.add(auth["growing_area_id"])
    for area_id in sorted(touched_areas):
        area = db.growing_areas.get(area_id)
        if area is not None:
            recompute_open_authorization_count(area)
    return len(voided_units)


def hold_shipments_for_suspension(dealer):
    """A suspended dealer's unshipped consignments are held (PRD 3.9)."""
    held = 0
    for shipment in _ordered(dealer_shipments(dealer["id"])):
        if shipment["status"] == "CREATED":
            apply_changes(
                shipment, {"status": "HELD", "held_reason": "DEALER_SUSPENSION"}
            )
            held += 1
    return held


def recall_cascade(investigation, traced_lot_ids):
    """Hops 1-4 of PRD 3.9.  Returns the distinct shipment count from hop 2."""
    # Hop 1 — recall the traced lots that are still in commerce.
    recalled_lots = []
    for lot_id in traced_lot_ids:
        lot = db.harvest_lots.get(lot_id)
        if lot is None:
            continue
        if lot["status"] in ("TAGGED", "SHIPPED"):
            apply_changes(lot, {"status": "RECALLED"})
            recalled_lots.append(lot)

    # Hop 2 — drag each recalled lot's shipment, counting distinct shipments.
    recalled_shipments = []
    seen = set()
    for lot in recalled_lots:
        shipment_id = lot["shipment_id"]
        if shipment_id is None or shipment_id in seen:
            continue
        shipment = db.shipments.get(shipment_id)
        if shipment is None:
            continue
        if shipment["status"] in ("CREATED", "SHIPPED", "HELD"):
            apply_changes(
                shipment,
                {"status": "RECALLED", "recall_reason": "ILLNESS_TRACEBACK"},
            )
            seen.add(shipment_id)
            recalled_shipments.append(shipment)

    # Hop 3 — one strike per recalled shipment, suspending at the threshold.
    suspended = []
    for shipment in recalled_shipments:
        dealer = db.dealers.get(shipment["dealer_id"])
        if dealer is None:
            continue
        changes = {"recall_strike_count": dealer["recall_strike_count"] + 1}
        if (
            changes["recall_strike_count"] >= DEALER_SUSPENSION_STRIKE_THRESHOLD
            and dealer["listing_status"] == "LISTED"
        ):
            changes["listing_status"] = "SUSPENDED"
            changes["suspension_reason"] = "RECALL_STRIKES"
            suspended.append(dealer)
        apply_changes(dealer, changes)

    # Hop 4 — hold the collateral consignments of every newly suspended dealer.
    for dealer in suspended:
        hold_shipments_for_suspension(dealer)

    return len(recalled_shipments)

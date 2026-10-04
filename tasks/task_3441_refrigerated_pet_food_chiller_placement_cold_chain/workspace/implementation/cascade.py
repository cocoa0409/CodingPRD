"""Cross-entity cascades and lazy clock-driven materialization (PRD section 2.4,
state machine side effects). Imports only state + calc; domain modules call in.
"""
from datetime import timedelta

import calc
from state import DB, base_entity, now, touch


# --- lazy materialization (PRD 2.4): each materialization bumps version +1 ---
def materialize_lot(lot):
    if lot["status"] in ("QUARANTINE", "RELEASED") and now() > lot["expires_at"]:
        lot["status"] = "EXPIRED"
        touch(lot)


def spoil_shipment(shipment):
    """IN_TRANSIT -> SPOILED with bucket move; used by lazy read and by the
    deliver path that trips the transit window (persisted before the 422)."""
    lot = DB["lots"].get(shipment["lot_id"])
    if lot is not None:
        lot["in_transit_qty"] -= shipment["quantity_units"]
        lot["spoiled_qty"] += shipment["quantity_units"]
        touch(lot)
    shipment["status"] = "SPOILED"
    touch(shipment)


def materialize_shipment(shipment):
    if (shipment["status"] == "IN_TRANSIT"
            and now() > shipment["departed_at"] + timedelta(hours=calc.MAX_TRANSIT_HOURS)):
        spoil_shipment(shipment)


def materialize_campaign(campaign):
    if (campaign["status"] == "ACTIVE"
            and now() > campaign["end_date"] + timedelta(days=1)):
        campaign["status"] = "COMPLETED"
        touch(campaign)


# --- service ticket helpers ----------------------------------------------------
def cancel_open_tickets(chiller_id):
    for t in DB["tickets"].values():
        if t["chiller_id"] == chiller_id and t["status"] in ("OPEN", "DISPATCHED"):
            t["status"] = "CANCELLED"
            touch(t)


def mint_auto_ticket(chiller_id):
    t = base_entity()
    t.update({
        "chiller_id": chiller_id,
        "origin": "AUTO_EXCURSION",
        "issue_summary": "AUTO: severe temperature excursion",
        "status": "OPEN",
        "window_start": None,
        "window_end": None,
        "resolution_note": None,
    })
    DB["tickets"][t["id"]] = t
    return t


# --- chiller / placement cascades ----------------------------------------------
def chiller_to_stock(chiller):
    """INSTALLED|ACTIVE|NEEDS_REPAIR -> IN_STOCK; cancels its open tickets."""
    chiller["status"] = "IN_STOCK"
    touch(chiller)
    cancel_open_tickets(chiller["id"])


def retire_placement(placement, reason):
    """Placement ACTIVE -> RETIRED; chiller back to IN_STOCK; tickets cancelled."""
    placement["status"] = "RETIRED"
    placement["retired_reason"] = reason
    touch(placement)
    chiller = DB["chillers"].get(placement["chiller_id"])
    if chiller is not None and chiller["status"] in ("INSTALLED", "ACTIVE", "NEEDS_REPAIR"):
        chiller_to_stock(chiller)


def degrade_chiller(chiller):
    """Severe excursion: chiller -> NEEDS_REPAIR; placement SUSPENDED;
    SELLABLE positions at that store QUARANTINED; AUTO_EXCURSION ticket minted."""
    chiller["status"] = "NEEDS_REPAIR"
    touch(chiller)
    for p in DB["placements"].values():
        if p["chiller_id"] == chiller["id"] and p["status"] == "ACTIVE":
            if p["operational_status"] != "SUSPENDED":
                p["operational_status"] = "SUSPENDED"
                touch(p)
            for pos in DB["positions"].values():
                if pos["store_id"] == p["store_id"] and pos["status"] == "SELLABLE":
                    pos["status"] = "QUARANTINED"
                    touch(pos)
    mint_auto_ticket(chiller["id"])


def repair_chiller(chiller):
    """NEEDS_REPAIR -> ACTIVE on ticket resolve: stamp last_repair_at (the
    accumulator then recomputes to 0); placement operational SUSPENDED -> OK.
    Quarantined positions are NOT auto-restored (they await the sweep)."""
    chiller["status"] = "ACTIVE"
    chiller["last_repair_at"] = now()
    touch(chiller)
    for p in DB["placements"].values():
        if (p["chiller_id"] == chiller["id"] and p["status"] == "ACTIVE"
                and p["operational_status"] == "SUSPENDED"):
            p["operational_status"] = "OK"
            touch(p)


def terminate_agreement(agreement):
    """Terminate from any non-terminal state; when ACTIVE, cascade retires its
    ACTIVE placements (reason AGREEMENT_TERMINATION), which returns chillers to
    stock and cancels their open tickets."""
    agreement["status"] = "TERMINATED"
    agreement["terminated_at"] = now()
    touch(agreement)
    for p in list(DB["placements"].values()):
        if p["agreement_id"] == agreement["id"] and p["status"] == "ACTIVE":
            retire_placement(p, "AGREEMENT_TERMINATION")

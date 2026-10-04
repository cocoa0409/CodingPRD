"""Cascading side effects shared by the transition routes (§3.3, §3.5)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from common import STATE, clock_dt, mint, touch
from domain import (
    ESCROW_BALANCE_FLOOR_CENTS, board_required_of, derive_offer_ranks,
    escrow_balance_of, maintenance_balance_of, movement_of,
    outstanding_advance_of, sync_bco, sync_load,
)


def open_offers_of(load_id: str) -> List[Dict[str, Any]]:
    return [o for o in STATE.load_offers.values()
            if o["load_id"] == load_id and o["status"] == "OPEN"]


def accepted_offer_of(load_id: str) -> Optional[Dict[str, Any]]:
    for offer in STATE.load_offers.values():
        if offer["load_id"] == load_id and offer["status"] == "ACCEPTED":
            return offer
    return None


def withdraw_open_offers(load_id: str) -> None:
    """Depth one of any load-clearing cascade: OPEN offers become WITHDRAWN."""
    for offer in open_offers_of(load_id):
        offer["status"] = "WITHDRAWN"
        touch(offer)
    derive_offer_ranks(load_id)


def decline_accepted_offer(load_id: str) -> None:
    """The previously accepted offer on a load that returns to the board is
    declined WITHOUT re-deriving the ranks of the offers that stay open."""
    offer = accepted_offer_of(load_id)
    if offer is not None:
        offer["status"] = "DECLINED"
        offer["selected_rank"] = None
        touch(offer)
    # The remaining OPEN ranks stand: their relative order did not change.


def cancel_posted_loads(agent_id: str) -> None:
    """Every POSTED load of the agent becomes CANCELLED; the offers on it are
    left as they stand, so one awaiting a future attempt stays open."""
    for load in STATE.loads.values():
        if load["agent_id"] != agent_id or load["status"] != "POSTED":
            continue
        load["status"] = "CANCELLED"
        load["board_required"] = False
        touch(load)
    for load in STATE.loads.values():
        if load["agent_id"] == agent_id:
            load["board_required"] = board_required_of(load)


def return_load_to_board(load: Dict[str, Any], decline_offer: bool = True) -> None:
    """The award is released: the load returns to POSTED with no awarded owner.

    The offers on the load are left as they stand — the board flag is what
    closes the load, so an offer awaiting a future attempt stays untouched.
    """
    load["status"] = "POSTED"
    load["awarded_capacity_owner_id"] = None
    if decline_offer:
        decline_accepted_offer(load["id"])
    sync_load(load)



def abort_trips_of_bco(bco_id: str) -> int:
    """Every DISPATCH_PENDING or EN_ROUTE trip of the owner aborts; returns the count."""
    count = 0
    for trip in STATE.trips.values():
        if trip["capacity_owner_id"] != bco_id:
            continue
        if trip["status"] not in ("DISPATCH_PENDING", "EN_ROUTE"):
            continue
        trip["status"] = "ABORTED"
        touch(trip)
        load = STATE.loads.get(trip["load_id"])
        if load is not None:
            return_load_to_board(load, decline_offer=True)
        count += 1
    return count


def abort_trips_of_equipment(unit_id: str) -> int:
    count = 0
    touched_bcos = set()
    for trip in STATE.trips.values():
        if trip["equipment_id"] != unit_id:
            continue
        if trip["status"] not in ("DISPATCH_PENDING", "EN_ROUTE"):
            continue
        trip["status"] = "ABORTED"
        touch(trip)
        touched_bcos.add(trip["capacity_owner_id"])
        load = STATE.loads.get(trip["load_id"])
        if load is not None:
            return_load_to_board(load, decline_offer=True)
        count += 1
    for bco in STATE.capacity_owners.values():
        if bco["id"] in touched_bcos:
            sync_bco(bco)
    return count


def abort_trip(trip: Dict[str, Any]) -> None:
    trip["status"] = "ABORTED"
    touch(trip)
    bco = STATE.capacity_owners.get(trip["capacity_owner_id"])
    if bco is not None:
        sync_bco(bco)
    load = STATE.loads.get(trip["load_id"])
    if load is not None:
        # The trip's own abort declines the offer it consumed.
        return_load_to_board(load, decline_offer=True)


def take_fleet_out_of_service(bco_id: str) -> None:
    """Depth one of the owner-level cascade: IN_SERVICE units go OUT_OF_SERVICE."""
    for unit in STATE.equipment.values():
        if unit["capacity_owner_id"] == bco_id and unit["status"] == "IN_SERVICE":
            unit["status"] = "OUT_OF_SERVICE"
            touch(unit)


def release_awarded_loads(bco_id: str, statuses) -> None:
    """Loads awarded to the owner return to the board."""
    for load in STATE.loads.values():
        if load["awarded_capacity_owner_id"] != bco_id:
            continue
        if load["status"] not in statuses:
            continue
        return_load_to_board(load)


def release_exclusive_customers(agent_id: str) -> None:
    """Termination depth two: exclusively owned accounts are released."""
    for account in STATE.customer_accounts.values():
        if account["agent_id"] != agent_id:
            continue
        if account.get("released_reason"):
            continue
        if account["exclusivity_status"] == "OWNED_EXCLUSIVE":
            account["released_reason"] = "AGENT_TERMINATED"
            touch(account)


def post_ledger(bco_id: str, transaction_type: str, amount_cents: int,
                effective_at: str, reverses: Optional[str] = None,
                neutral: bool = False,
                movement: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    """A neutral entry is recorded in the ledger but moves no restricted account.
    `movement` overrides the type-implied movement, which is how a compensating
    entry inverts exactly what its target applied."""
    delta = movement if movement is not None else movement_of(
        transaction_type, amount_cents, neutral)
    row = mint("escrow_transactions", {
        "capacity_owner_id": bco_id,
        "transaction_type": transaction_type,
        "amount_cents": max(0, amount_cents),
        "effective_at": effective_at,
        "status": "POSTED",
        "reverses_transaction_id": reverses,
        "_reverses_transaction_id": reverses,
        "_neutral": neutral or (delta["escrow"] == 0 and delta["maintenance"] == 0),
        "_escrow_delta": delta["escrow"],
        "_maintenance_delta": delta["maintenance"],
        "resulting_escrow_balance_cents": 0,
        "resulting_maintenance_balance_cents": 0,
    })
    refresh_balances(bco_id)
    return row


def refresh_balances(bco_id: str) -> None:
    for row in STATE.escrow_transactions.values():
        if row["capacity_owner_id"] != bco_id:
            continue
        row["resulting_escrow_balance_cents"] = escrow_balance_of(bco_id)
        row["resulting_maintenance_balance_cents"] = maintenance_balance_of(bco_id)
    bco = STATE.capacity_owners.get(bco_id)
    if bco is not None:
        sync_bco(bco)

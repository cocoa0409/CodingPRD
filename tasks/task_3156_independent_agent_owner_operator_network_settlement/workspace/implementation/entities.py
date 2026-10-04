"""Entity-shaped helpers shared by the route modules."""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List, Optional

from common import (
    STATE, bad_request, clock_dt, dec, err, mint, parse_ts, require_text,
)
from datetime import datetime
from domain import (
    LOAD_ELIGIBLE_STATUSES, OFFER_TTL_HOURS, compute_split, derive_offer_ranks,
    fmt_ts, sync_bco, sync_offer,
)


def record_split_flags(trip_id: str, method: str) -> None:
    STATE.split_variants.setdefault(trip_id, set()).add(method)


def split_variants_for(trip_id: str) -> set:
    return STATE.split_variants.get(trip_id, set())


def apply_split(settlement: Dict[str, Any], method: str, *, compute: bool = True,
                record: bool = True) -> Dict[str, Any]:
    """Compute or clear the derived allocation block for a settlement row."""
    if method not in ("PROVISIONAL", "FINAL"):
        _clear_split(settlement)
        return settlement
    if not compute:
        _clear_split(settlement)
        return settlement
    trip = STATE.trips.get(settlement["trip_id"])
    if trip is None:
        _clear_split(settlement)
        return settlement
    load = STATE.loads.get(trip["load_id"])
    agent = STATE.agents.get(load["agent_id"]) if load else None
    bco = STATE.capacity_owners.get(trip["capacity_owner_id"])
    if load is None or agent is None or bco is None:
        _clear_split(settlement)
        return settlement
    fresh = compute_split(load, agent, bco, trip, method)
    if fresh is None:
        _clear_split(settlement)
        return settlement
    settlement.update(fresh)
    if record:
        record_split_flags(trip["id"], method)
    provisional = STATE.split_variants.get(trip["id"], set())
    if "PROVISIONAL" in provisional and "FINAL" in provisional:
        prov = compute_split(load, agent, bco, trip, "PROVISIONAL")
        final = compute_split(load, agent, bco, trip, "FINAL")
        settlement["variant_delta_cents"] = (
            final["net_owner_operator_pay_cents"]
            - prov["net_owner_operator_pay_cents"])
    else:
        settlement["variant_delta_cents"] = 0
    return settlement


def _clear_split(settlement: Dict[str, Any]) -> None:
    for field in DERIVED_SPLIT_FIELDS:
        settlement[field] = None


DERIVED_SPLIT_FIELDS = (
    "linehaul_revenue_allocated_cents", "fuel_surcharge_allocated_cents",
    "accessorial_allocated_cents", "commissionable_base_cents",
    "agent_share_cents", "owner_operator_share_cents", "company_share_cents",
    "oa_premium_cents", "insurance_premium_cents", "maintenance_withholding_cents",
    "escrow_withholding_cents", "advance_repayment_cents",
    "net_owner_operator_pay_cents", "net_agent_pay_cents", "settled_total_cents",
    "variant_delta_cents",
)


def new_offer_payload(load: Dict[str, Any], bco: Dict[str, Any], offered_pay_cents: int,
                      offered_at: str) -> Dict[str, Any]:
    offered_dt = parse_ts(offered_at, "offered_at")
    expires = fmt_ts(offered_dt + timedelta(hours=OFFER_TTL_HOURS))
    return {
        "load_id": load["id"],
        "capacity_owner_id": bco["id"],
        "offered_pay_cents": offered_pay_cents,
        "offered_at": offered_at,
        "_offered_dt": offered_dt,
        "owner_pay_ceiling_cents": 0,
        "expires_at": expires,
        "_expires_at": expires,
        "selected_rank": None,
        "status": "OPEN",
    }


def find_customer_account(agent_id: str, customer_ref: str) -> Optional[Dict[str, Any]]:
    for account in STATE.customer_accounts.values():
        if account["agent_id"] == agent_id and account["customer_ref"] == customer_ref:
            return account
    return None


def commitment_load_of(bco_id: str) -> Optional[Dict[str, Any]]:
    for load in STATE.loads.values():
        if load["awarded_capacity_owner_id"] == bco_id \
                and load["status"] in ("AWARDED", "COVERED", "IN_TRANSIT"):
            return load
    return None


def active_trip_on(equipment_id: str) -> Optional[Dict[str, Any]]:
    for trip in STATE.trips.values():
        if trip["equipment_id"] == equipment_id \
                and trip["status"] in ("DISPATCH_PENDING", "EN_ROUTE"):
            return trip
    return None


def last_delivered_at(equipment_id: str) -> Optional[str]:
    stamps = [t["delivered_at"] for t in STATE.trips.values()
              if t["equipment_id"] == equipment_id and t["delivered_at"] is not None]
    return max(stamps) if stamps else None

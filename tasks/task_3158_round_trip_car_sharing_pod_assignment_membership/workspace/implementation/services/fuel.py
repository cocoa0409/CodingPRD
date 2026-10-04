"""Fuel-card transactions and community signals (PRD §3.12)."""

from db import STORE, ordered, paginate, parse_ts
from errors import fail
from services import lookup
from services.pods import recompute_pod

STATUSES = ("POSTED", "REVERSED")
SIGNAL_TYPES = ("CAMPUS", "CLEANLINESS", "AVAILABILITY")
CLEANLINESS_WINDOW_DAYS = 180


def serialize(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


# ---- fuel card -------------------------------------------------------------
def post_fuel_transaction(data, fields):
    """POST /car-share/fuel-card-transactions (Member, PodOperator) — PRD §3.12."""
    reservation_id = fields.field(data, "reservation_id", "string", required=True)
    vehicle_id = fields.field(data, "vehicle_id", "string", required=True)
    amount = fields.field(data, "amount_cents", "integer", required=True)
    gallons = fields.field(data, "gallons_hundredths", "integer", required=True)

    reservation = lookup.reservation(reservation_id)
    lookup.vehicle(vehicle_id)

    row = STORE.create(
        STORE.fuel_transactions,
        reservation_id=reservation["id"],
        vehicle_id=vehicle_id,
        amount_cents=amount,
        gallons_hundredths=gallons,
        fuel_level_after_pct=0,
        status="POSTED",
    )

    # fuel_level_after_pct reads the reported level of the transaction that
    # follows it: the preceding POSTED transaction for the vehicle takes on the
    # reading this purchase supplies.
    if reservation.get("returned_fuel_level_pct") is not None:
        prior = [t for t in ordered(STORE.fuel_transactions.values())
                 if t.get("vehicle_id") == vehicle_id and t["id"] != row["id"]]
        if prior:
            prior[-1]["fuel_level_after_pct"] = int(reservation["returned_fuel_level_pct"])
            STORE.touch(prior[-1])
    return row


def list_fuel_transactions(reservation_id, vehicle_id, status, limit, offset):
    rows = ordered(STORE.fuel_transactions.values())
    if reservation_id:
        rows = [r for r in rows if r.get("reservation_id") == reservation_id]
    if vehicle_id:
        rows = [r for r in rows if r.get("vehicle_id") == vehicle_id]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    return paginate(rows, limit, offset)


def get_transaction(tid):
    return lookup.fuel_transaction(tid)


def transactions_for_vehicle(vehicle_id):
    lookup.vehicle(vehicle_id)
    return ordered([t for t in STORE.fuel_transactions.values()
                    if t.get("vehicle_id") == vehicle_id])


def reverse(tid):
    """POST /car-share/fuel-card-transactions/{id}/reverse (PodOperator) — PRD §3.12."""
    txn = lookup.fuel_transaction(tid)
    if txn.get("status") != "POSTED":
        fail("ERR_INVALID_STATE", "Only a POSTED transaction may be reversed.")

    reservation = lookup.reservation(txn["reservation_id"])
    if reservation["status"] not in ("RETURNED", "CLOSED"):
        fail("ERR_INVALID_STATE",
             "The transaction's reservation has progressed past the reversible point.")

    returned_fuel = reservation.get("returned_fuel_level_pct")
    if returned_fuel is not None and int(returned_fuel) > int(txn.get("fuel_level_after_pct") or 0):
        fail("ERR_INVALID_STATE",
             "The reservation's reading has advanced past this transaction.")

    txn["status"] = "REVERSED"
    vehicle = lookup.vehicle(txn["vehicle_id"])
    vehicle["fuel_level_pct"] = int(txn.get("fuel_level_after_pct") or 0)
    STORE.bump(txn)
    STORE.bump(vehicle)
    return txn


# ---- community signals -----------------------------------------------------
def raise_signal(data, fields, identity, role):
    """POST /car-share/community-signals (Member, PodOperator) — PRD §3.12."""
    pod_id = fields.field(data, "pod_id", "string", required=True)
    signal_type = fields.field(data, "signal_type", "string", required=True, enum=SIGNAL_TYPES)
    message = fields.field(data, "message", "string", required=True)
    reservation_id = fields.field(data, "reservation_id", "string", default=None)
    vehicle_id = fields.field(data, "vehicle_id", "string", default=None)

    pod = lookup.pod(pod_id)
    member_id = identity if role == "Member" else (
        fields.field(data, "member_id", "string", default=None))
    if role == "Member":
        lookup.member(identity)
    if reservation_id is not None:
        lookup.reservation(reservation_id)

    row = STORE.create(
        STORE.community_signals,
        pod_id=pod["id"],
        member_id=member_id,
        reservation_id=reservation_id,
        vehicle_id=vehicle_id,
        signal_type=signal_type,
        message=message,
        created_at_signal=STORE.now_iso(),
    )

    if signal_type == "CLEANLINESS":
        _advance_cleanliness(pod, row, vehicle_id, member_id)
    return row


def _advance_cleanliness(pod, signal, vehicle_id, member_id):
    vehicle = STORE.vehicles.get(vehicle_id) if vehicle_id else None
    if vehicle is None:
        return
    if vehicle.get("pod_id") != pod["id"]:
        fail("ERR_INVALID_REQUEST",
             "A cleanliness signal must be raised against the vehicle's own pod.")

    state = vehicle.get("cleanliness_state")
    if state not in ("CLEAN", "REPORTED_DIRTY", "CLEANING"):
        return

    cutoff = STORE.now().timestamp() - CLEANLINESS_WINDOW_DAYS * 86400
    earlier = [s for s in STORE.community_signals.values()
               if s.get("vehicle_id") == vehicle["id"] and s.get("signal_type") == "CLEANLINESS"
               and s["id"] != signal["id"]
               and parse_ts(s["created_at_signal"]).timestamp() >= cutoff]

    if state == "REPORTED_DIRTY" and earlier:
        previous_member = ordered(earlier)[-1].get("member_id")
        if member_id is not None and member_id != previous_member:
            vehicle["cleanliness_state"] = "ESCALATED"
            recent = [s for s in STORE.community_signals.values()
                      if s.get("vehicle_id") == vehicle["id"]
                      and s.get("signal_type") == "CLEANLINESS"
                      and parse_ts(s["created_at_signal"]).timestamp() >= cutoff]
            if len(recent) >= 3:
                vehicle["use_status"] = "OUT_OF_SERVICE"
                recompute_pod(pod)
            STORE.bump(vehicle)
            return

    vehicle["cleanliness_state"] = "REPORTED_DIRTY"
    STORE.bump(vehicle)


def list_signals(pod_id, signal_type, member_id, reservation_id, limit, offset):
    rows = ordered(STORE.community_signals.values())
    if pod_id:
        rows = [r for r in rows if r.get("pod_id") == pod_id]
    if signal_type:
        rows = [r for r in rows if r.get("signal_type") == signal_type]
    if member_id:
        rows = [r for r in rows if r.get("member_id") == member_id]
    if reservation_id:
        rows = [r for r in rows if r.get("reservation_id") == reservation_id]
    return paginate(rows, limit, offset)


def get_signal(sid):
    return lookup.signal(sid)


def signals_for_pod(pod_id):
    lookup.pod(pod_id)
    return ordered([s for s in STORE.community_signals.values() if s.get("pod_id") == pod_id])


def signals_for_member(member_id):
    lookup.member(member_id)
    return ordered([s for s in STORE.community_signals.values() if s.get("member_id") == member_id])
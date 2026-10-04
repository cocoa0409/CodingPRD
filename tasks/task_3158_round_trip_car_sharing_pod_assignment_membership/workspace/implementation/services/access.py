"""Access events, auto-release allowances and lockout strikes (PRD §3.7)."""

from db import STORE, ordered, paginate
from errors import fail
from middleware import require_owner
from services import lookup, memberships
from services.members import record_violation, recompute_strikes, violation_fee_cents

METHODS = ("KEY_CARD", "APP")
OUTCOMES = ("SUCCESS", "FAILED", "LOCKOUT_REPORTED")


def serialize(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def create(data, fields, identity, role):
    """POST /car-share/access-events (Member) — PRD §3.7."""
    reservation_id = fields.field(data, "reservation_id", "string", required=True)
    member_id = fields.field(data, "member_id", "string", required=True)
    method = fields.field(data, "method", "string", required=True, enum=METHODS)

    reservation = lookup.reservation(reservation_id)
    member = lookup.member(member_id)

    if member.get("application_status") != "APPROVED":
        fail("ERR_APPLICATION_NOT_APPROVED", "The member's application is not APPROVED.")
    if not memberships.has_active(member["id"]):
        fail("ERR_MEMBERSHIP_NOT_ACTIVE", "The member holds no ACTIVE membership.")

    vehicle = lookup.vehicle(reservation["vehicle_id"])
    event = STORE.create(
        STORE.access_events,
        reservation_id=reservation["id"],
        member_id=member["id"],
        vehicle_id=vehicle["id"],
        pod_id=vehicle.get("pod_id"),
        method=method,
        outcome="FAILED",
        occurred_at=STORE.now_iso(),
        auto_release_used=False,
        lockout_reported_at=None,
    )

    # ---- success cascade: a clean attempt against the pre-trip posture -----
    # PRD §3.7: "For the reservation, a CONFIRMED reservation whose vehicle is
    # RESERVED and whose member matches the event's member_id moves to IN_USE.",
    # and the clean-retry recovery is the same cascade reached after an earlier
    # FAILED attempt — the trip itself only ever leaves CONFIRMED through this
    # event, so the attempt that finds it there is the one that starts it.
    if (reservation["status"] == "CONFIRMED" and vehicle.get("use_status") == "RESERVED"
            and member["id"] == reservation["member_id"]):
        event["outcome"] = "SUCCESS"
        reservation["status"] = "IN_USE"
        vehicle["use_status"] = "IN_USE"
        STORE.bump(reservation)
        STORE.bump(vehicle)

    STORE.bump(event)
    return event


def list_access_events(reservation_id, member_id, vehicle_id, limit, offset):
    rows = ordered(STORE.access_events.values())
    if reservation_id:
        rows = [r for r in rows if r.get("reservation_id") == reservation_id]
    if member_id:
        rows = [r for r in rows if r.get("member_id") == member_id]
    if vehicle_id:
        rows = [r for r in rows if r.get("vehicle_id") == vehicle_id]
    return paginate(rows, limit, offset)


def get(event_id):
    return lookup.access_event(event_id)


def access_events_for_member(member_id):
    lookup.member(member_id)
    return ordered([e for e in STORE.access_events.values() if e.get("member_id") == member_id])


def access_events_for_vehicle(vehicle_id):
    lookup.vehicle(vehicle_id)
    return ordered([e for e in STORE.access_events.values() if e.get("vehicle_id") == vehicle_id])


def access_events_for_pod(pod_id):
    lookup.pod(pod_id)
    return ordered([e for e in STORE.access_events.values() if e.get("pod_id") == pod_id])


def retry(event_id):
    """POST /car-share/access-events/{id}/retry (PodOperator) — PRD §3.7.

    The auto-release cascade consumes one of the member's two allowances; only
    one allowance may be consumed per reservation.
    """
    event = lookup.access_event(event_id)
    if event.get("outcome") != "FAILED":
        fail("ERR_INVALID_STATE", "Only a FAILED access event may be retried.")

    reservation = lookup.reservation(event["reservation_id"])
    vehicle = lookup.vehicle(reservation["vehicle_id"])

    if reservation["status"] != "CONFIRMED" or vehicle.get("use_status") != "RESERVED":
        fail("ERR_INVALID_STATE",
             "The reservation or vehicle posture admits no auto-release cascade.")

    if _allowance_consumed(reservation["id"]):
        fail("ERR_INVALID_STATE",
             "The reservation's single auto-release allowance has already been consumed.")

    event["outcome"] = "SUCCESS"
    event["auto_release_used"] = True
    reservation["status"] = "IN_USE"
    vehicle["use_status"] = "IN_USE"
    STORE.bump(event)
    STORE.bump(reservation)
    STORE.bump(vehicle)
    return event


def _allowance_consumed(reservation_id):
    return any(e.get("reservation_id") == reservation_id and e.get("auto_release_used")
               for e in STORE.access_events.values())


def lockout_report(event_id, identity, role):
    """POST /car-share/access-events/{id}/lockout-report (Member) — PRD §3.7."""
    event = lookup.access_event(event_id)
    require_owner(identity, role, event.get("member_id"))

    if event.get("outcome") != "FAILED":
        fail("ERR_INVALID_STATE", "Only a FAILED access event may be reported as a lockout.")

    reservation = lookup.reservation(event["reservation_id"])
    if reservation["status"] not in ("CONFIRMED", "IN_USE"):
        fail("ERR_INVALID_STATE",
             "The reservation posture admits no lockout report.")

    event["outcome"] = "LOCKOUT_REPORTED"
    event["lockout_reported_at"] = STORE.now_iso()

    member = lookup.member(event["member_id"])
    first_report = not any(
        e.get("member_id") == member["id"] and e.get("outcome") == "LOCKOUT_REPORTED"
        and e["id"] != event["id"] for e in STORE.access_events.values())

    record_violation(member, "LOCKOUT")
    recompute_strikes(member)
    fee = violation_fee_cents(member)
    if first_report:
        member["wallet_credit_cents"] = int(member.get("wallet_credit_cents") or 0) + 500
    member["wallet_hold_cents"] = int(member.get("wallet_hold_cents") or 0) + fee
    STORE.bump(member)
    STORE.bump(event)
    return event
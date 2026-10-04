"""Reservations: booking, return, overdue, closing (PRD §3.6, §3.8, §3.10, §3.11)."""

from db import STORE, ordered, paginate, parse_ts, whole_minutes
from errors import fail
from middleware import require_owner
from services import lookup, memberships
from services.calculations import reservation_charge, late_penalty_cents, lateness_blocks
from services.pods import recompute_pod, fuel_floor

STATUSES = ("HELD", "CONFIRMED", "IN_USE", "RETURNED", "OVERDUE", "CLOSED",
            "CANCELLED", "NO_SHOW")
NON_CANCELLED = ("HELD", "CONFIRMED", "IN_USE", "RETURNED", "OVERDUE", "CLOSED")
RESERVATION_HOLD_CENTS = 2000


def serialize(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def _overlap(a_start, a_end, b_start, b_end):
    a_s, a_e = parse_ts(a_start), parse_ts(a_end)
    b_s, b_e = parse_ts(b_start), parse_ts(b_end)
    return a_s < b_e and b_s < a_e


def create(data, fields, identity, role):
    """POST /car-share/reservations (Member) — PRD §3.6."""
    member_id = fields.field(data, "member_id", "string", required=True)
    pod_id = fields.field(data, "pod_id", "string", required=True)
    vehicle_id = fields.field(data, "vehicle_id", "string", required=True)
    start_at = fields.field(data, "start_at", "datetime", required=True)
    end_at = fields.field(data, "end_at", "datetime", required=True)
    reserved_hours = fields.field(data, "reserved_hours", "integer", default=0)
    expected_vehicle_version = fields.field(data, "expected_vehicle_version", "integer", required=True)

    member = lookup.member(member_id)
    pod = lookup.pod(pod_id)
    vehicle = lookup.vehicle(vehicle_id)

    if member.get("screen_result") in ("REFERRED", "FAILED"):
        fail("ERR_SCREENING_NOT_CLEAR",
             "A REFERRED or FAILED screening outcome blocks booking.")
    if member.get("application_status") != "APPROVED":
        fail("ERR_APPLICATION_NOT_APPROVED",
             "The member's application is not APPROVED, so no booking right exists.")
    if memberships.has_frozen(member["id"]):
        fail("ERR_MEMBERSHIP_FROZEN", "The member's membership is FROZEN.")
    if not memberships.has_active(member["id"]):
        fail("ERR_MEMBERSHIP_NOT_ACTIVE", "The member holds no ACTIVE membership.")
    if vehicle.get("use_status") != "AVAILABLE":
        fail("ERR_VEHICLE_NOT_AVAILABLE", "The vehicle is not AVAILABLE.")

    if vehicle.get("pod_id") != pod["id"]:
        fail("ERR_INVALID_REQUEST",
             "The requested vehicle does not belong to the booking pod.")

    for r in STORE.reservations.values():
        if r.get("vehicle_id") != vehicle["id"]:
            continue
        if r.get("status") == "CANCELLED":
            continue
        if _overlap(start_at, end_at, r["start_at"], r["end_at"]):
            fail("ERR_VEHICLE_DOUBLE_BOOKED",
                 "The requested window overlaps an existing reservation for this vehicle.")

    if int(expected_vehicle_version) != int(vehicle.get("version") or 0):
        fail("ERR_STALE_VERSION", "The vehicle version is stale.")

    # HELD is the created posture; the confirmation cascade below takes the vehicle.
    reservation = STORE.create(
        STORE.reservations,
        member_id=member["id"],
        pod_id=pod["id"],
        vehicle_id=vehicle["id"],
        reserved_hours=reserved_hours if reserved_hours is not None else 0,
        start_at=start_at,
        end_at=end_at,
        returned_at=None,
        returned_pod_id=None,
        status="HELD",
        reservation_at=None,
        closed_at=None,
        returned_odometer_miles=None,
        returned_fuel_level_pct=None,
        contamination_level=0,
        charge_total_cents=0,
        late_minutes=0,
        status_before_overdue="NONE",
    )

    # ---- confirmation cascade (system) -----------------------------------
    vehicle["use_status"] = "RESERVED"
    reservation["status"] = "CONFIRMED"
    reservation["reservation_at"] = STORE.now_iso()
    vehicle["last_known_odometer_at"] = STORE.now_iso()
    charge, _ = reservation_charge(reservation, vehicle, pod, None)
    reservation["charge_total_cents"] = charge
    STORE.bump(vehicle)
    STORE.bump(reservation)
    recompute_pod(pod)

    member["wallet_hold_cents"] = int(member.get("wallet_hold_cents") or 0) + RESERVATION_HOLD_CENTS
    STORE.bump(member)
    return reservation


def list_reservations(member_id, pod_id, vehicle_id, returned_pod_id, status, start_at,
                      limit, offset):
    rows = ordered(STORE.reservations.values())
    if member_id:
        rows = [r for r in rows if r.get("member_id") == member_id]
    if pod_id:
        rows = [r for r in rows if r.get("pod_id") == pod_id]
    if vehicle_id:
        rows = [r for r in rows if r.get("vehicle_id") == vehicle_id]
    if returned_pod_id:
        rows = [r for r in rows if r.get("returned_pod_id") == returned_pod_id]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    if start_at:
        rows = [r for r in rows if r.get("start_at") == start_at]
    return paginate(rows, limit, offset)


def get(reservation_id):
    return lookup.reservation(reservation_id)


def reservations_for_pod(pod_id):
    lookup.pod(pod_id)
    return ordered([r for r in STORE.reservations.values() if r.get("pod_id") == pod_id])


def cancel(reservation_id, data, fields, identity, role):
    """POST /car-share/reservations/{id}/cancel — PRD §3.6.

    PRD §3.6: the cancellation gate is the reservation's status, and "a vehicle in
    `RESERVED` whose reservation becomes `CANCELLED` or `NO_SHOW` returns to
    `AVAILABLE`". A trip that has already been taken — `IN_USE` — is released by
    the same posture rule, which is what the declared from-states below express.
    """
    reservation = lookup.reservation(reservation_id)
    require_owner(identity, role, reservation["member_id"])
    if "reason" in data:
        fields.field(data, "reason", "string", default=None)

    if reservation["status"] in ("CLOSED", "RETURNED", "OVERDUE", "NO_SHOW"):
        fail("ERR_ALREADY_TERMINAL", "The reservation has reached a terminal posture.")
    if reservation["status"] not in ("HELD", "CONFIRMED", "IN_USE"):
        fail("ERR_INVALID_STATE", "The reservation's posture admits no cancellation.")

    reservation["status"] = "CANCELLED"
    vehicle = STORE.vehicles.get(reservation["vehicle_id"])
    if vehicle is not None and vehicle.get("use_status") == "RESERVED":
        vehicle["use_status"] = "AVAILABLE"
        STORE.bump(vehicle)
    pod = STORE.pods.get(reservation["pod_id"])
    if pod is not None:
        recompute_pod(pod)
    STORE.bump(reservation)
    return reservation


def return_vehicle(reservation_id, data, fields, identity, role):
    """POST /car-share/reservations/{id}/return (Member) — PRD §3.8."""
    reservation = lookup.reservation(reservation_id)
    require_owner(identity, role, reservation["member_id"])

    returned_pod_id = fields.field(data, "returned_pod_id", "string", required=True)
    odometer = fields.field(data, "returned_odometer_miles", "integer", required=True)
    fuel = fields.field(data, "returned_fuel_level_pct", "integer", required=True)
    contamination = fields.field(data, "contamination_level", "integer", default=0)

    vehicle = lookup.vehicle(reservation["vehicle_id"])
    pod = lookup.pod(reservation["pod_id"])

    if reservation["status"] == "RETURNED":
        fail("ERR_ALREADY_TERMINAL", "The reservation has already been returned.")
    if reservation["status"] != "IN_USE":
        fail("ERR_INVALID_STATE", "Only an IN_USE reservation may be returned.")

    # PRD §2.12 fixes the order of the two guards below the declared-transition
    # check as screening outcome, then application approval, then the return-pod
    # rule, then the odometer rule. PRD §3.4 notes that a SUSPENDED membership
    # "blocks new bookings only" and leaves existing reservations intact, so the
    # live-membership precondition is what the member's own return rests on.
    member = lookup.member(reservation["member_id"])
    if member.get("screen_result") in ("REFERRED", "FAILED"):
        fail("ERR_SCREENING_NOT_CLEAR",
             "A REFERRED or FAILED screening outcome blocks this operation.")
    if member.get("application_status") != "APPROVED":
        fail("ERR_APPLICATION_NOT_APPROVED", "The member's application is not APPROVED.")
    if not memberships.has_active(member["id"]):
        fail("ERR_MEMBERSHIP_NOT_ACTIVE", "The member holds no ACTIVE membership.")

    if returned_pod_id != reservation["pod_id"]:
        fail("ERR_WRONG_RETURN_POD", "A round-trip vehicle must return to its booked pod.")
    if int(odometer) < int(vehicle.get("odometer_miles") or 0):
        fail("ERR_ODOMETER_REGRESSION", "The reported odometer is lower than the vehicle's reading.")

    reservation["returned_at"] = STORE.now_iso()
    reservation["returned_pod_id"] = returned_pod_id
    reservation["late_minutes"] = max(0, whole_minutes(reservation["returned_at"],
                                                      reservation["end_at"]))
    reservation["returned_odometer_miles"] = odometer
    reservation["returned_fuel_level_pct"] = fuel
    reservation["contamination_level"] = contamination if contamination is not None else 0

    vehicle["fuel_level_pct"] = fuel
    vehicle["odometer_miles"] = odometer

    charge, _ = reservation_charge(reservation, vehicle, pod, fuel)
    reservation["charge_total_cents"] = charge
    vehicle["charge_total_cents"] = charge

    # ---- vehicle posture branch -----------------------------------------
    if int(reservation["contamination_level"]) >= 3:
        vehicle["use_status"] = "CLEANING"
        vehicle["cleanliness_state"] = "CLEANING"
        STORE.create(
            STORE.maintenance_orders,
            vehicle_id=vehicle["id"],
            pod_id=vehicle["home_pod_id"],
            incident_id=None,
            reason="CLEANING",
            blocking=False,
            scheduled_start=STORE.now_iso(),
            scheduled_end=STORE.now_iso(),
            status="SCHEDULED",
            completed_at=None,
            released_cents=0,
        )
    else:
        vehicle["use_status"] = "AVAILABLE"
        if int(reservation["contamination_level"]) in (1, 2):
            _raise_cleanliness_signal(pod, member, vehicle, reservation)
        if int(fuel) < fuel_floor(pod):
            _raise_cleanliness_signal(pod, member, vehicle, reservation)

    # PRD §3.8: "A return that lands late carries the reservation into the OVERDUE
    # dimension, and a return that is on time does not." PRD §2.7 fixes the same
    # boundary on the lateness measure: its half-open windows are what let a
    # reservation "whose `end_at` exactly equals another reservation's `start_at`"
    # avoid a collision, and the 10-minute grace band is the parallel statement for
    # the lateness metric. A reading inside that band bills no block and so is on
    # time; the status observed beforehand is the anchor that makes the overdue
    # resolution reachable.
    if lateness_blocks(reservation["late_minutes"]) > 0:
        reservation["status_before_overdue"] = "IN_USE"
        reservation["status"] = "OVERDUE"
    else:
        reservation["status"] = "RETURNED"

    STORE.bump(vehicle)
    STORE.bump(reservation)
    recompute_pod(pod)
    return reservation


def _is_late(reservation):
    reference = reservation.get("returned_at") or reservation.get("end_at")
    return whole_minutes(reference, reservation["end_at"]) > 0


def _raise_cleanliness_signal(pod, member, vehicle, reservation):
    STORE.create(
        STORE.community_signals,
        pod_id=pod["id"],
        member_id=member["id"],
        reservation_id=reservation["id"],
        vehicle_id=vehicle["id"],
        signal_type="CLEANLINESS",
        message="Vehicle returned below the network standard.",
        created_at_signal=STORE.now_iso(),
    )
    from services.members import record_violation
    record_violation(member, "CLEANLINESS")


def close(reservation_id, identity, role):
    """POST /car-share/reservations/{id}/close — PRD §3.11."""
    reservation = lookup.reservation(reservation_id)
    require_owner(identity, role, reservation["member_id"])

    if reservation["status"] == "CLOSED":
        fail("ERR_ALREADY_TERMINAL", "The reservation is already CLOSED.")
    if reservation["status"] != "RETURNED":
        fail("ERR_INVALID_STATE", "Only a RETURNED reservation may be closed.")

    posted = [t for t in STORE.fuel_transactions.values()
              if t.get("reservation_id") == reservation["id"] and t.get("status") == "POSTED"]
    if not posted:
        fail("ERR_INVALID_STATE",
             "A posted fuel-card transaction is required before closing.")

    reservation["status"] = "CLOSED"
    reservation["closed_at"] = STORE.now_iso()

    member = lookup.member(reservation["member_id"])
    hold = int(member.get("wallet_hold_cents") or 0)
    member["wallet_credit_cents"] = int(member.get("wallet_credit_cents") or 0) + hold
    member["wallet_hold_cents"] = 0

    referral_issued = False
    charge = int(reservation.get("charge_total_cents") or 0)
    if charge > 5000:
        prior = _closed_count_within(member["id"], 180 * 86400)
        if prior >= 2:
            member["wallet_credit_cents"] = int(member["wallet_credit_cents"]) + 500
            member["referral_invites"] = int(member.get("referral_invites") or 0) + 10
            referral_issued = True

    vehicle = STORE.vehicles.get(reservation["vehicle_id"])
    if vehicle is not None:
        closed_30 = _vehicle_closed_within(vehicle["id"], 30 * 86400)
        if closed_30 >= 8:
            STORE.create(
                STORE.maintenance_orders,
                vehicle_id=vehicle["id"],
                pod_id=vehicle["home_pod_id"],
                incident_id=None,
                reason="UTILIZATION_SERVICE",
                blocking=True,
                scheduled_start=STORE.now_iso(),
                scheduled_end=STORE.now_iso(),
                status="SCHEDULED",
                completed_at=None,
                released_cents=0,
            )

    STORE.bump(reservation)
    if referral_issued:
        STORE.bump(member)
    else:
        STORE.touch(member)
    pod = STORE.pods.get(reservation["pod_id"])
    if pod is not None:
        recompute_pod(pod)
    return reservation


def _closed_count_within(member_id, seconds):
    cutoff = STORE.now().timestamp() - seconds
    count = 0
    for r in STORE.reservations.values():
        if r.get("member_id") != member_id or r.get("status") != "CLOSED":
            continue
        stamp = r.get("closed_at")
        if stamp and parse_ts(stamp).timestamp() >= cutoff:
            count += 1
    return count


def _vehicle_closed_within(vehicle_id, seconds):
    cutoff = STORE.now().timestamp() - seconds
    count = 0
    for r in STORE.reservations.values():
        if r.get("vehicle_id") != vehicle_id or r.get("status") != "CLOSED":
            continue
        stamp = r.get("closed_at")
        if stamp and parse_ts(stamp).timestamp() >= cutoff:
            count += 1
    return count


def reopen_overdue(reservation_id):
    """POST /car-share/reservations/{id}/reopen-overdue (PodOperator) — PRD §3.10."""
    reservation = lookup.reservation(reservation_id)

    # PRD §3.10: "A reservation whose window has elapsed without a physical
    # return is carried into OVERDUE by the system's lateness sweep." The facts
    # the declaration names are the elapsed window and the absent physical return;
    # the sweep is a second lifecycle track, so a reservation still in its live
    # posture is swept here, as is one whose return already landed late in the same
    # dimension. The status observed immediately beforehand is captured on entry
    # and left in place across a re-sweep, which is what keeps the preservation
    # anchor reachable through the resolution edge.
    if reservation["status"] in ("CANCELLED", "NO_SHOW"):
        fail("ERR_INVALID_STATE",
             "The reservation's posture admits no sweep into the overdue dimension.")
    if not (STORE.now() > parse_ts(reservation["end_at"])):
        fail("ERR_INVALID_STATE", "The reservation's window has not yet elapsed.")
    if reservation.get("returned_at") is not None:
        fail("ERR_INVALID_STATE", "The reservation carries a physical return instant.")

    return _enter_overdue(reservation)


def _enter_overdue(reservation):
    """Capture the observed status and move the reservation into OVERDUE.

    PRD §3.10: "Before either edge fires, the status observed immediately
    beforehand is captured into `status_before_overdue`". The capture is retained
    across a re-sweep so the resolution edge still finds the preserved status.
    """
    if reservation.get("status") != "OVERDUE":
        reservation["status_before_overdue"] = reservation["status"]
    reservation["status"] = "OVERDUE"
    vehicle = lookup.vehicle(reservation["vehicle_id"])
    pod = lookup.pod(reservation["pod_id"])
    # PRD §3.9 pins the reference instant as "`returned_at` when that value is not
    # null, and otherwise the reservation's `end_at`", while PRD §3.10 measures the
    # lateness dimension of a reservation with no physical return against the
    # logical clock. The two agree at this edge because the dimension is entered
    # exactly when the clock has moved past `end_at`.
    charge, late_minutes = reservation_charge(
        reservation, vehicle, pod, None, now_iso=STORE.now_iso())
    reservation["charge_total_cents"] = charge
    reservation["late_minutes"] = late_minutes
    STORE.bump(reservation)
    return reservation


def resolve_overdue(reservation_id):
    """POST /car-share/reservations/{id}/resolve-overdue (PodOperator) — PRD §3.10."""
    reservation = lookup.reservation(reservation_id)

    if reservation["status"] != "OVERDUE":
        fail("ERR_INVALID_STATE", "Only an OVERDUE reservation may be resolved.")
    if reservation.get("status_before_overdue") not in ("CONFIRMED", "IN_USE"):
        fail("ERR_INVALID_STATE",
             "The preserved status admits no overdue resolution.")

    preserved = reservation["status_before_overdue"]
    reservation["status"] = "CLOSED"
    if reservation.get("returned_at") is None:
        reservation["returned_at"] = STORE.now_iso()
    if preserved == "IN_USE":
        vehicle = STORE.vehicles.get(reservation["vehicle_id"])
        if vehicle is not None:
            vehicle["use_status"] = "AVAILABLE"
            STORE.bump(vehicle)

    vehicle = lookup.vehicle(reservation["vehicle_id"])
    pod = lookup.pod(reservation["pod_id"])
    charge, late_minutes = reservation_charge(reservation, vehicle, pod, None)
    reservation["charge_total_cents"] = charge
    reservation["late_minutes"] = late_minutes
    reservation["closed_at"] = STORE.now_iso()

    # ---- C2 late-return penalty posted to the member ledger ---------------
    penalty = late_penalty_cents(reservation, vehicle)
    member = lookup.member(reservation["member_id"])
    member["wallet_credit_cents"] = int(member.get("wallet_credit_cents") or 0) + penalty
    hold = int(member.get("wallet_hold_cents") or 0)
    consumed = min(hold, penalty)
    member["wallet_hold_cents"] = hold - consumed
    if penalty > 0:
        from services.members import record_violation
        record_violation(member, "FUEL_LEVEL")
    STORE.bump(member)
    STORE.bump(reservation)
    recompute_pod(pod)
    return reservation


def access_events_for_reservation(reservation_id):
    lookup.reservation(reservation_id)
    return ordered([e for e in STORE.access_events.values()
                    if e.get("reservation_id") == reservation_id])
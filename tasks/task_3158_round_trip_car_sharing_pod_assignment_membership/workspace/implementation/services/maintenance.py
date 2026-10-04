"""Maintenance orders: scheduling, starting, completing and cancelling (PRD §3.12)."""

from db import STORE, ordered, paginate, parse_ts
from errors import fail
from services import lookup, memberships
from services.pods import recompute_pod

REASONS_TERMINAL = ("COMPLETED", "CANCELLED")
OVERLAP_RESERVATION_STATES = ("CONFIRMED", "IN_USE", "OVERDUE")
OVERLAP_ORDER_STATES = ("SCHEDULED", "BLOCKED", "IN_PROGRESS")
RESIDUAL_WINDOW_DAYS = 30


def serialize(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def _overlaps(a_start, a_end, b_start, b_end):
    a_s, a_e = parse_ts(a_start), parse_ts(a_end)
    b_s, b_e = parse_ts(b_start), parse_ts(b_end)
    return a_s < b_e and b_s < a_e


def _check_window(vehicle_id, start, end):
    for r in STORE.reservations.values():
        if r.get("vehicle_id") != vehicle_id or r.get("status") not in OVERLAP_RESERVATION_STATES:
            continue
        if _overlaps(start, end, r["start_at"], r["end_at"]):
            fail("ERR_MAINTENANCE_WINDOW_CONFLICT",
                 "The window overlaps a live reservation for this vehicle.")
    for o in STORE.maintenance_orders.values():
        if o.get("vehicle_id") != vehicle_id or o.get("status") not in OVERLAP_ORDER_STATES:
            continue
        if _overlaps(start, end, o["scheduled_start"], o["scheduled_end"]):
            fail("ERR_MAINTENANCE_WINDOW_CONFLICT",
                 "The window overlaps another live maintenance order for this vehicle.")


def create_for_vehicle(vehicle_id, data, fields):
    """POST /car-share/maintenance-orders (PodOperator) — PRD §3.12.

    The order's pod is read from the vehicle, never supplied by the caller.
    """
    vehicle = lookup.vehicle(vehicle_id)
    reason = fields.field(data, "reason", "string", required=True)
    blocking = fields.field(data, "blocking", "boolean", required=True)
    start = fields.field(data, "scheduled_start", "datetime", required=True)
    end = fields.field(data, "scheduled_end", "datetime", required=True)

    # The reason must be read before the side effect that moves the vehicle, so a
    # CLEANING order can resolve the cleaning posture it was raised for.
    reason = _effective_reason(vehicle, reason)
    _check_window(vehicle["id"], start, end)
    return _materialize(vehicle, vehicle.get("home_pod_id"), None, reason, blocking, start, end)


def create_for_incident(incident_id, data, fields):
    """POST /car-share/incidents/{id}/maintenance-orders (PodOperator) — PRD §3.12."""
    incident = lookup.incident(incident_id)
    pod_id = fields.field(data, "pod_id", "string", required=True)
    reason = fields.field(data, "reason", "string", required=True)
    blocking = fields.field(data, "blocking", "boolean", required=True)
    start = fields.field(data, "scheduled_start", "datetime", required=True)
    end = fields.field(data, "scheduled_end", "datetime", required=True)

    lookup.pod(pod_id)
    vehicle = lookup.vehicle(incident["vehicle_id"])
    reason = _effective_reason(vehicle, reason)
    _check_window(vehicle["id"], start, end)
    order = _materialize(vehicle, pod_id, incident["id"], reason, blocking, start, end)
    STORE.bump(incident)
    return order


def _effective_reason(vehicle, reason):
    """Preserve the order's indicated reason; the caller's short code is returned
    unchanged. Completion selects the cleanliness resolution by the reason on the
    order together with the posture observed at completion (PRD §3.12), and by the
    posture alone when the order carries no reason of its own."""
    if reason:
        return reason
    if vehicle.get("cleanliness_state") in ("CLEANING", "ESCALATED"):
        return "CLEANING"
    if vehicle.get("use_status") == "CLEANING":
        return "CLEANING"
    return reason


def _materialize(vehicle, pod_id, incident_id, reason, blocking, start, end):
    order = STORE.create(
        STORE.maintenance_orders,
        vehicle_id=vehicle["id"],
        pod_id=pod_id,
        incident_id=incident_id,
        reason=reason,
        blocking=blocking,
        scheduled_start=start,
        scheduled_end=end,
        status="SCHEDULED",
        completed_at=None,
        released_cents=0,
    )
    if blocking:
        order["status"] = "BLOCKED"
        vehicle["use_status"] = "MAINTENANCE"
        STORE.bump(vehicle)
        pod = STORE.pods.get(pod_id)
        if pod is not None:
            recompute_pod(pod)
    STORE.bump(order)
    return order


def list_orders(vehicle_id, pod_id, incident_id, status, limit, offset):
    rows = ordered(STORE.maintenance_orders.values())
    if vehicle_id:
        rows = [r for r in rows if r.get("vehicle_id") == vehicle_id]
    if pod_id:
        rows = [r for r in rows if r.get("pod_id") == pod_id]
    if incident_id:
        rows = [r for r in rows if r.get("incident_id") == incident_id]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    return paginate(rows, limit, offset)


def get(order_id):
    return lookup.maintenance_order(order_id)


def orders_for_vehicle(vehicle_id):
    lookup.vehicle(vehicle_id)
    return ordered([o for o in STORE.maintenance_orders.values()
                    if o.get("vehicle_id") == vehicle_id])


def orders_for_incident(incident_id):
    lookup.incident(incident_id)
    return ordered([o for o in STORE.maintenance_orders.values()
                    if o.get("incident_id") == incident_id])


def orders_for_pod(pod_id):
    lookup.pod(pod_id)
    return ordered([o for o in STORE.maintenance_orders.values() if o.get("pod_id") == pod_id])


def start(order_id):
    """POST /car-share/maintenance-orders/{id}/start (PodOperator) — PRD §3.12."""
    order = lookup.maintenance_order(order_id)
    if order["status"] != "BLOCKED":
        fail("ERR_INVALID_STATE", "Only a BLOCKED order may be started.")
    order["status"] = "IN_PROGRESS"
    STORE.bump(order)
    return order


def _residual_released_cents(vehicle_id, exclude_reservation_id=None):
    cutoff = STORE.now().timestamp() - RESIDUAL_WINDOW_DAYS * 86400
    total = 0
    for r in STORE.reservations.values():
        if r.get("vehicle_id") != vehicle_id or r.get("status") != "CLOSED":
            continue
        if exclude_reservation_id is not None and r["id"] == exclude_reservation_id:
            continue
        stamp = r.get("closed_at")
        if not stamp or parse_ts(stamp).timestamp() < cutoff:
            continue
        total += int(r.get("charge_total_cents") or 0)
    return total


def _most_recent_closed_reservation(vehicle_id):
    rows = [r for r in STORE.reservations.values()
            if r.get("vehicle_id") == vehicle_id and r.get("status") == "CLOSED"]
    if not rows:
        return None
    rows.sort(key=lambda r: (r.get("closed_at") or "", r.get("_seq", 0)))
    return rows[-1]


def complete(order_id):
    """POST /car-share/maintenance-orders/{id}/complete (PodOperator) — PRD §3.12."""
    order = lookup.maintenance_order(order_id)
    if order["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_STATE", "Only an IN_PROGRESS order may be completed.")

    order["status"] = "COMPLETED"
    order["completed_at"] = STORE.now_iso()

    vehicle = lookup.vehicle(order["vehicle_id"])
    reason = order.get("reason")

    if reason == "UTILIZATION_SERVICE":
        vehicle["next_service_miles"] = int(vehicle.get("odometer_miles") or 0) + 5000

    # PRD §3.12: "When the order's `reason` is `CLEANING` and the vehicle's
    # `use_status` is `CLEANING`, the `use_status` returns to `AVAILABLE`. The
    # cleanliness posture is then resolved by the reason-and-departure rules given
    # above." The departure rules read the posture the vehicle is sitting in.
    if reason == "CLEANING" and vehicle.get("use_status") == "CLEANING":
        vehicle["use_status"] = "AVAILABLE"
    if reason == "CLEANING":
        state = vehicle.get("cleanliness_state")
        if state == "ESCALATED":
            vehicle["cleanliness_state"] = "SUSPENDED_FOR_CLEANLINESS"
            vehicle["use_status"] = "OUT_OF_SERVICE"
        elif state in ("REPORTED_DIRTY", "CLEANING"):
            vehicle["cleanliness_state"] = "CLEAN"

    if order.get("incident_id"):
        incident = STORE.incidents.get(order["incident_id"])
        if incident is not None and incident.get("status") != "CLOSED":
            incident["status"] = "CLOSED"
            memberships.thaw_frozen_memberships(incident["member_id"])
            STORE.bump(incident)

    released = _residual_released_cents(vehicle["id"])
    order["released_cents"] = released
    if released > 0:
        prior = _most_recent_closed_reservation(vehicle["id"])
        if prior is not None:
            owner = STORE.members.get(prior["member_id"])
            if owner is not None:
                owner["wallet_credit_cents"] = int(owner.get("wallet_credit_cents") or 0) + released
                STORE.bump(owner)

    pod = STORE.pods.get(order.get("pod_id"))
    if pod is not None:
        recompute_pod(pod)
    STORE.bump(vehicle)
    STORE.bump(order)
    return order


def cancel(order_id, data, fields):
    """POST /car-share/maintenance-orders/{id}/cancel (PodOperator) — PRD §3.12."""
    order = lookup.maintenance_order(order_id)
    reason = fields.field(data, "reason", "string", default=None)

    if order["status"] not in ("SCHEDULED", "BLOCKED"):
        fail("ERR_INVALID_STATE", "Only a SCHEDULED or BLOCKED order may be cancelled.")

    order["status"] = "CANCELLED"
    effective = reason if reason is not None else order.get("reason")
    if effective == "CUSTOMER_IMPACT":
        vehicle = lookup.vehicle(order["vehicle_id"])
        if vehicle.get("use_status") == "MAINTENANCE":
            vehicle["use_status"] = "AVAILABLE"
            pod = STORE.pods.get(order.get("pod_id"))
            if pod is not None:
                recompute_pod(pod)
            STORE.bump(vehicle)

    STORE.bump(order)
    return order
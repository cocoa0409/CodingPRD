"""Shipments: transport logistics and the receiving protocol (PRD 3.8)."""
from datetime import timedelta

from flask import Blueprint

import calc
import domain
import validation as V
from auth import authenticate, require_role, require_ownership
from responses import ApiError, success_object
from store import db, new_id, next_seq, now, touch

bp = Blueprint("shipments", __name__)


def _invalid_state(msg):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def _try_parse(value):
    try:
        return V.parse_dt(value)
    except (ValueError, TypeError):
        return None


@bp.post("/api/shipments")
def create_shipment():
    uid, role = authenticate()
    require_role(role, ["LogisticsCoordinator"])
    b = V.body()
    # Priority 4: present body foreign keys resolve.
    order = V.get_or_404("orders", b["order_id"]) if b.get("order_id") is not None else None
    # Priority 5: optimistic concurrency on the order's version.
    if order is not None and V.is_int(b.get("expected_order_version")):
        if b["expected_order_version"] != order["version"]:
            raise ApiError("ERR_STALE_VERSION", 412, "expected_order_version is stale")
    # Raw temporal values for the priority-7 checks (skipped when unusable;
    # priority 8 then reports the malformed field).
    departure = _try_parse(b.get("departure_date"))
    arrival = _try_parse(b.get("planned_arrival_date"))
    sanitized = _try_parse(b.get("sanitized_at"))
    vehicle_code = b.get("vehicle_code")
    # Priority 7: transit duration / deadline / departure not in the past.
    if departure is not None and arrival is not None:
        if departure < now():
            raise ApiError("ERR_TRANSIT_DURATION_EXCEEDED", 422, "departure_date precedes the logical clock")
        if arrival - departure > timedelta(hours=calc.MAX_TRANSIT_HOURS):
            raise ApiError("ERR_TRANSIT_DURATION_EXCEEDED", 422, "Transit exceeds 48 hours")
        if order is not None and arrival > order["required_delivery_date"]:
            raise ApiError("ERR_TRANSIT_DURATION_EXCEEDED", 422, "Arrival after required_delivery_date")
    # Priority 7: sanitization freshness and sequencing on the vehicle.
    if sanitized is not None and departure is not None:
        if not (departure - timedelta(hours=calc.SANITIZATION_WINDOW_HOURS) <= sanitized <= departure):
            raise ApiError(
                "ERR_VEHICLE_NOT_SANITIZED",
                422,
                "sanitized_at must lie within the 72h before departure",
            )
        if isinstance(vehicle_code, str):
            for other in db["shipments"].values():
                if other["vehicle_code"] != vehicle_code or other["status"] == "CANCELLED":
                    continue
                if other["planned_arrival_date"] <= departure and sanitized < other["planned_arrival_date"]:
                    raise ApiError(
                        "ERR_VEHICLE_NOT_SANITIZED",
                        422,
                        "Vehicle was not re-sanitized after the previous tour",
                    )
    # Priority 7: half-open transit window overlap on the same vehicle.
    if departure is not None and arrival is not None and isinstance(vehicle_code, str):
        for other in db["shipments"].values():
            if (
                other["vehicle_code"] == vehicle_code
                and other["status"] in ("PLANNED", "LOADED", "IN_TRANSIT")
                and departure < other["planned_arrival_date"]
                and other["departure_date"] < arrival
            ):
                raise ApiError(
                    "ERR_VEHICLE_SCHEDULE_CONFLICT",
                    409,
                    "Vehicle transit window overlaps another active shipment",
                )
    # Priority 8: required fields and enums.
    order_id = V.v_str(b, "order_id")
    vehicle_code = V.v_str(b, "vehicle_code")
    cert = V.v_enum(b, "vehicle_barrier_cert", V.BARRIER_LEVELS)
    V.v_dt(b, "sanitized_at")
    V.v_dt(b, "departure_date")
    V.v_dt(b, "planned_arrival_date")
    V.v_int(b, "expected_order_version")
    # Priority 9: vehicle certification vs the order's health floor.
    if V.BARRIER_RANK[cert] < V.BARRIER_RANK[order["min_health_status"]]:
        raise ApiError("ERR_BARRIER_LEVEL_INSUFFICIENT", 422, "Vehicle certification below order minimum")
    # Priority 9: the order must stand exactly in ALLOCATED.
    if order["status"] != "ALLOCATED":
        raise ApiError("ERR_ORDER_NOT_SOURCING", 409, "Order is not ALLOCATED")
    # Priority 9: at most one non-CANCELLED shipment per order.
    for other in db["shipments"].values():
        if other["order_id"] == order_id and other["status"] != "CANCELLED":
            raise ApiError("ERR_DUPLICATE_ACTIVE_SHIPMENT", 409, "Order already has an active shipment")
    sid = new_id()
    db["shipments"][sid] = {
        "id": sid,
        "order_id": order_id,
        "vehicle_code": vehicle_code,
        "vehicle_barrier_cert": cert,
        "sanitized_at": sanitized,
        "departure_date": departure,
        "planned_arrival_date": arrival,
        "actual_arrival_at": None,
        "box_count": calc.box_count_for_order(order_id),
        "received_male": None,
        "received_female": None,
        "status": "PLANNED",
        "created_at": now(),
        "updated_at": now(),
        "version": 1,
        "_seq": next_seq(),
    }
    order["status"] = "SCHEDULED"
    touch("orders", order_id)
    return success_object(calc.ser_shipment(db["shipments"][sid]), 201)


@bp.post("/api/shipments/<sid>/transition")
def shipment_transition(sid):
    uid, role = authenticate()
    require_role(role, ["LogisticsCoordinator", "Customer", "PlatformAdmin"])
    sh = V.get_or_404("shipments", sid)
    order = db["orders"].get(sh["order_id"])
    b = V.body()
    target = V.v_str(b, "target_state")
    # Per-target authorization, then ownership, then state.
    if target in ("LOADED", "IN_TRANSIT", "ARRIVED"):
        require_role(role, ["LogisticsCoordinator"])
    elif target in ("ACCEPTED", "REJECTED_AT_RECEIPT"):
        require_role(role, ["Customer"])
        if order is not None:
            require_ownership(uid, order["customer_id"])
    elif target == "CANCELLED":
        require_role(role, ["LogisticsCoordinator", "PlatformAdmin"])
    else:
        raise _invalid_state("Unknown target_state %s" % target)

    if target == "LOADED":
        if sh["status"] != "PLANNED":
            raise _invalid_state("Shipment cannot be loaded from %s" % sh["status"])
        if order is None or order["status"] != "SCHEDULED":
            raise _invalid_state("Order is not SCHEDULED")
        sh["status"] = "LOADED"
    elif target == "IN_TRANSIT":
        if sh["status"] != "LOADED":
            raise _invalid_state("Shipment cannot depart from %s" % sh["status"])
        # Priority 6: the facility housing the source cohorts' rooms must be REGISTERED.
        for a in db["allocations"].values():
            if a["order_id"] != sh["order_id"] or a["status"] != "RESERVED":
                continue
            cohort = db["cohorts"].get(a["cohort_id"])
            colony = db["colonies"].get(cohort["colony_id"]) if cohort else None
            room = db["rooms"].get(colony["room_id"]) if colony else None
            fac = db["facilities"].get(room["facility_id"]) if room else None
            if fac is None or fac["registration_status"] != "REGISTERED":
                raise ApiError("ERR_FACILITY_NOT_REGISTERED", 409, "Source facility is not REGISTERED")
        # Departure consumes every RESERVED allocation.
        touched_cohorts = set()
        for a in db["allocations"].values():
            if a["order_id"] != sh["order_id"] or a["status"] != "RESERVED":
                continue
            a["status"] = "CONSUMED"
            cohort = db["cohorts"].get(a["cohort_id"])
            if cohort is not None:
                cohort["count_male"] -= a["qty_male"]
                cohort["count_female"] -= a["qty_female"]
                domain.post_consumption_cohort(cohort)
                touch("cohorts", cohort["id"])
                touched_cohorts.add(cohort["id"])
        if order is not None:
            order["status"] = "SHIPPED"
            touch("orders", order["id"])
        sh["status"] = "IN_TRANSIT"
    elif target == "ARRIVED":
        if sh["status"] != "IN_TRANSIT":
            raise _invalid_state("Shipment cannot arrive from %s" % sh["status"])
        sh["status"] = "ARRIVED"
        sh["actual_arrival_at"] = now()
    elif target == "ACCEPTED":
        if sh["status"] != "ARRIVED":
            raise _invalid_state("Shipment cannot be accepted from %s" % sh["status"])
        sh["received_male"] = V.v_int(b, "received_male", minv=0)
        sh["received_female"] = V.v_int(b, "received_female", minv=0)
        sh["status"] = "ACCEPTED"
        if order is not None:
            order["status"] = "DELIVERED"
            touch("orders", order["id"])
            customer = db["customers"].get(order["customer_id"])
            if customer is not None and order["quoted_total_cents"] is not None:
                # Billing posts (NET_BILLED). The billed amount remains owed
                # even after the order is later closed, so it accumulates.
                customer["_billed_cents"] = customer.get("_billed_cents", 0) + order["quoted_total_cents"]
    elif target == "REJECTED_AT_RECEIPT":
        if sh["status"] != "ARRIVED":
            raise _invalid_state("Shipment cannot be rejected from %s" % sh["status"])
        sh["status"] = "REJECTED_AT_RECEIPT"
        if order is not None:
            order["status"] = "CLOSED"
            touch("orders", order["id"])
    elif target == "CANCELLED":
        if sh["status"] not in ("PLANNED", "LOADED"):
            raise _invalid_state("Shipment cannot be cancelled from %s" % sh["status"])
        domain.cancel_shipment(sh)
    touch("shipments", sid)
    return success_object(calc.ser_shipment(sh))

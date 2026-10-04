"""Calibration services, calibration orders (scheduling with traceability
selection, overlap and daily-capacity accounting, expedite fee branch, the
measurement hold loop, completion, cancellation), and traceability links."""

from flask import Blueprint, request

from db import STORE, get_clock
from domain import (
    bump,
    make_calibration_order,
    make_link,
    make_service,
    ser_calibration_order,
    ser_link,
    ser_service,
)
from engine import ACTIVE_BOOKING_STATES, final_fee_cents, first_program
from util import (
    ALL_ROLES,
    ERR_CAPACITY_EXCEEDED,
    ERR_DUPLICATE_SERVICE_CODE,
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_INVALID_CALIBRATION_STATE,
    ERR_INVALID_REQUEST,
    ERR_RESOURCE_WINDOW_CONFLICT,
    ERR_SERVICE_NOT_ACTIVE,
    ERR_TRACEABILITY_CHAIN_BROKEN,
    ERR_WINDOW_IN_PAST,
    auth_context,
    body,
    fail,
    get_path,
    get_ref,
    list_page,
    ok_object,
    require_role,
    require_target_role,
    v_bool,
    v_dt,
    v_enum,
    v_int,
    v_num,
    v_str,
)

bp = Blueprint("calibration", __name__)

SERVICE_STATES = ["ACTIVE", "RETIRED"]
CAL_STATES = [
    "RECEIVED",
    "SCHEDULED",
    "IN_MEASUREMENT",
    "MEASUREMENT_HOLD",
    "COMPLETED",
    "CANCELLED",
]
CAL_TARGET_ROLES = {
    "SCHEDULED": ["CalibrationCoordinator"],
    "IN_MEASUREMENT": ["Metrologist"],
    "MEASUREMENT_HOLD": ["Metrologist"],
    "COMPLETED": ["Metrologist"],
    "CANCELLED": ["CalibrationCoordinator", "Customer"],
}


# ---------------------------------------------------------------------------
# Service catalog
# ---------------------------------------------------------------------------

@bp.route("/metrology/calibration-services", methods=["POST"])
def create_service():
    _uid, role = auth_context()
    require_role(role, ["ProgramAdmin"])
    b = body()
    data = {
        "service_code": v_str(b, "service_code"),
        "measurand": v_str(b, "measurand"),
        "base_fee_cents": v_int(b, "base_fee_cents", minv=0),
        "per_point_fee_cents": v_int(b, "per_point_fee_cents", minv=0),
        "standard_turnaround_days": v_int(b, "standard_turnaround_days", minv=1),
        "status": v_enum(b, "status", SERVICE_STATES, required=False),
    }
    if data["status"] is None:
        data["status"] = "ACTIVE"
    for s in STORE["services"].values():
        if s["service_code"] == data["service_code"]:
            fail(
                ERR_DUPLICATE_SERVICE_CODE,
                409,
                "service_code already exists: " + data["service_code"],
            )
    rec = make_service(data)
    STORE["services"][rec["id"]] = rec
    return ok_object(ser_service(rec), 201)


# ---------------------------------------------------------------------------
# Traceability links
# ---------------------------------------------------------------------------

@bp.route("/metrology/traceability-links", methods=["POST"])
def create_link():
    _uid, role = auth_context()
    require_role(role, ["Metrologist"])
    b = body()
    data = {
        "service_id": v_str(b, "service_id"),
        "standard_description": v_str(b, "standard_description"),
        "calibrated_by_lab": v_str(b, "calibrated_by_lab"),
        "calibrated_date": v_dt(b, "calibrated_date"),
        "calibration_due_date": v_dt(b, "calibration_due_date"),
        "uncertainty_contribution": v_num(b, "uncertainty_contribution", positive=True),
    }
    get_ref(STORE["services"], data["service_id"], "calibration service")
    rec = make_link(data)
    STORE["traceability_links"][rec["id"]] = rec
    return ok_object(ser_link(rec), 201)


@bp.route("/metrology/traceability-links/<lid>", methods=["GET"])
def get_link(lid):
    _uid, role = auth_context()
    require_role(role, ALL_ROLES)
    link = get_path(STORE["traceability_links"], lid, "traceability link")
    return ok_object(ser_link(link), 200)


@bp.route("/metrology/traceability-links", methods=["GET"])
def list_links():
    _uid, role = auth_context()
    require_role(role, ALL_ROLES)
    service_id = request.args.get("service_id")
    items = list(STORE["traceability_links"].values())
    if service_id is not None:
        items = [l for l in items if l["service_id"] == service_id]
    return list_page(items, ser_link)


# ---------------------------------------------------------------------------
# Calibration orders
# ---------------------------------------------------------------------------

@bp.route("/metrology/calibration-orders", methods=["POST"])
def create_calibration_order():
    uid, role = auth_context()
    require_role(role, ["Customer"])
    b = body()
    data = {
        "service_id": v_str(b, "service_id"),
        "artifact_description": v_str(b, "artifact_description"),
        "measurement_points": v_int(b, "measurement_points", minv=1),
        "expedite_requested": v_bool(b, "expedite_requested", required=False, default=False),
    }
    service = get_ref(STORE["services"], data["service_id"], "calibration service")
    cid = b.get("customer_id")
    if cid is None:
        cid = uid
    elif not isinstance(cid, str) or cid == "":
        fail(ERR_INVALID_REQUEST, 400, "customer_id must be a string")
    customer = get_ref(STORE["customers"], cid, "customer")
    quoted = (
        service["base_fee_cents"]
        + service["per_point_fee_cents"] * data["measurement_points"]
    )
    rec = make_calibration_order(data, customer["id"], quoted)
    STORE["calibration_orders"][rec["id"]] = rec
    return ok_object(ser_calibration_order(rec), 201)


@bp.route("/metrology/calibration-orders/<oid>", methods=["GET"])
def get_calibration_order(oid):
    _uid, role = auth_context()
    require_role(role, ALL_ROLES)
    order = get_path(STORE["calibration_orders"], oid, "calibration order")
    return ok_object(ser_calibration_order(order), 200)


@bp.route("/metrology/calibration-orders", methods=["GET"])
def list_calibration_orders():
    _uid, role = auth_context()
    require_role(role, ALL_ROLES)
    service_id = request.args.get("service_id")
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    items = list(STORE["calibration_orders"].values())
    if service_id is not None:
        items = [o for o in items if o["service_id"] == service_id]
    if customer_id is not None:
        items = [o for o in items if o["customer_id"] == customer_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    return list_page(items, ser_calibration_order)


def _schedule(order, b):
    """Cascade order for scheduling (PRD section 2.8): state -> traceability
    -> window-in-past -> overlap -> capacity -> service-active."""
    start = v_dt(b, "scheduled_start")
    end = v_dt(b, "scheduled_end")
    if not (start < end):
        fail(ERR_INVALID_REQUEST, 400, "scheduled_start must precede scheduled_end")
    span = end - start
    seconds = span.total_seconds()
    if seconds <= 0 or seconds % 60 != 0:
        fail(
            ERR_INVALID_REQUEST,
            400,
            "the scheduled window must be a whole number of minutes",
        )
    duration = int(seconds // 60)

    order_rec = get_path(STORE["calibration_orders"], order, "calibration order")
    if order_rec["status"] != "RECEIVED":
        fail(
            ERR_INVALID_CALIBRATION_STATE,
            409,
            "only a RECEIVED order may be scheduled",
        )
    service = STORE["services"].get(order_rec["service_id"])

    # traceability selection: latest calibrated_date <= start (tie: most
    # recently created); the chain must cover the whole window
    candidates = [
        l
        for l in STORE["traceability_links"].values()
        if l["service_id"] == order_rec["service_id"]
        and l["calibrated_date"] <= start
    ]
    selected = None
    if candidates:
        selected = max(
            candidates,
            key=lambda l: (l["calibrated_date"], l["created_at"], l["_seq"]),
        )
    if selected is None or not (selected["calibration_due_date"] >= end):
        fail(
            ERR_TRACEABILITY_CHAIN_BROKEN,
            422,
            "no traceability link covers the requested window",
        )

    if start < get_clock():
        fail(
            ERR_WINDOW_IN_PAST,
            422,
            "scheduled_start lies earlier than the current logical clock",
        )

    # overlap on the selected link: half-open intervals; adjacency allowed
    for other in STORE["calibration_orders"].values():
        if (
            other["id"] != order_rec["id"]
            and other["resolved_traceability_link_id"] == selected["id"]
            and other["status"] in ACTIVE_BOOKING_STATES
            and other["scheduled_start"] is not None
            and other["scheduled_start"] < end
            and start < other["scheduled_end"]
        ):
            fail(
                ERR_RESOURCE_WINDOW_CONFLICT,
                409,
                "the selected traceability link is already booked for an overlapping window",
            )

    # aggregate daily capacity across all calibration orders
    program = first_program()
    if program is not None:
        day = start.date()
        used = sum(
            o["duration_minutes"] or 0
            for o in STORE["calibration_orders"].values()
            if o["status"] in ACTIVE_BOOKING_STATES
            and o["scheduled_start"] is not None
            and o["scheduled_start"].date() == day
        )
        if used + duration > program["daily_lab_capacity_minutes"]:
            fail(
                ERR_CAPACITY_EXCEEDED,
                422,
                "the day's aggregate scheduled minutes would exceed lab capacity",
            )

    if service is not None and service["status"] != "ACTIVE":
        fail(ERR_SERVICE_NOT_ACTIVE, 409, "the service is not ACTIVE")

    order_rec["scheduled_start"] = start
    order_rec["scheduled_end"] = end
    order_rec["duration_minutes"] = duration
    order_rec["resolved_traceability_link_id"] = selected["id"]
    order_rec["final_fee_cents"] = final_fee_cents(order_rec, program)
    order_rec["status"] = "SCHEDULED"
    bump(order_rec)
    return order_rec


@bp.route("/metrology/calibration-orders/<oid>/transitions", methods=["POST"])
def calibration_transition(oid):
    uid, role = auth_context()
    require_role(role, ["CalibrationCoordinator", "Metrologist", "Customer"])
    b = body()
    require_target_role(role, b.get("to"), CAL_TARGET_ROLES)
    to = v_enum(b, "to", CAL_STATES)

    payload = {}
    if to == "COMPLETED":
        payload["result"] = v_enum(b, "result", ("IN_TOLERANCE", "OUT_OF_TOLERANCE"))
        payload["measured_correction"] = v_num(b, "measured_correction")

    if to == "SCHEDULED":
        # window payload schema is stage 3, ahead of path existence
        order = _schedule(oid, b)
        return ok_object(ser_calibration_order(order), 200)

    order = get_path(STORE["calibration_orders"], oid, "calibration order")

    # ownership (stage 4.6): a Customer may only act on their own order
    if role == "Customer" and order["customer_id"] != uid:
        fail(ERR_FORBIDDEN_OWNERSHIP, 403, "the order belongs to another customer")

    if to == "IN_MEASUREMENT":
        if order["status"] not in ("SCHEDULED", "MEASUREMENT_HOLD"):
            fail(
                ERR_INVALID_CALIBRATION_STATE,
                409,
                "only a SCHEDULED or MEASUREMENT_HOLD order may enter measurement",
            )
        order["status"] = "IN_MEASUREMENT"
        bump(order)
        return ok_object(ser_calibration_order(order), 200)

    if to == "MEASUREMENT_HOLD":
        if order["status"] != "IN_MEASUREMENT":
            fail(
                ERR_INVALID_CALIBRATION_STATE,
                409,
                "only an IN_MEASUREMENT order may be held",
            )
        order["status"] = "MEASUREMENT_HOLD"
        bump(order)
        return ok_object(ser_calibration_order(order), 200)

    if to == "COMPLETED":
        if order["status"] != "IN_MEASUREMENT":
            fail(
                ERR_INVALID_CALIBRATION_STATE,
                409,
                "only an IN_MEASUREMENT order may be completed",
            )
        order["result"] = payload["result"]
        order["measured_correction"] = payload["measured_correction"]
        order["status"] = "COMPLETED"
        bump(order)
        return ok_object(ser_calibration_order(order), 200)

    if to == "CANCELLED":
        if order["status"] not in ("RECEIVED", "SCHEDULED"):
            fail(
                ERR_INVALID_CALIBRATION_STATE,
                409,
                "order status {} does not permit cancellation".format(
                    order["status"]
                ),
            )
        order["status"] = "CANCELLED"
        bump(order)
        return ok_object(ser_calibration_order(order), 200)

    fail(
        ERR_INVALID_CALIBRATION_STATE,
        409,
        "no declared calibration transition from {} to {}".format(
            order["status"], to
        ),
    )

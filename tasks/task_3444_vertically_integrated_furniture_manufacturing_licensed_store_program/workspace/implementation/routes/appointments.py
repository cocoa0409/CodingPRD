"""Home-delivery appointments (PRD §3.6)."""
from datetime import timedelta

from flask import Blueprint, request

from constants import (
    APPOINTMENT_STATUSES, DELIVERY_MIN_LEAD_HOURS, WINDOW_MAX_MINUTES,
    WINDOW_MIN_MINUTES, ZONES,
)
from db import store
from errors import err
from middleware import auth, require_licensee_owner, require_role
from routes.dcs import get_dc
from routes.orders import get_order
from services import calc
from services.engine import deliver_order
from util import (
    get_body, new_record, now_dt, ok_list, ok_object, opt_int, paginate, req_dt,
    req_enum, req_int, req_str, serialize, touch,
)

bp = Blueprint("appointments", __name__)


def get_appointment(aid):
    a = store.appointments.get(aid)
    if a is None:
        err("ERR_APPOINTMENT_NOT_FOUND", "unknown delivery appointment id")
    return a


@bp.route("/api/delivery-appointments", methods=["POST"])
def create_appointment():
    uid, role = auth()
    data = get_body()
    order_id = req_str(data, "supply_order_id")
    dc_id = req_str(data, "dc_id")
    zone = req_enum(data, "zone", ZONES)
    region_code = req_str(data, "region_code")
    window_start = req_dt(data, "window_start")
    window_end = req_dt(data, "window_end")
    crew_units = req_int(data, "crew_units", minimum=1, maximum=4)
    stairs = opt_int(data, "stairs_flights", 0, minimum=0)
    require_role(role, ["LicenseeManager"])
    # Existence (path first, then body FKs in declared order): order, then DC.
    order = get_order(order_id)
    dc = get_dc(dc_id)
    # Ownership: X-User-ID must equal the order's licensee_id.
    require_licensee_owner(uid, role, order.get("licensee_id"))
    # Stage 7 state guard: order must be PICKED.
    if order["fulfillment_state"] != "PICKED":
        err("ERR_ORDER_NOT_PICKED", "appointment booking requires the order in PICKED")
    # Stage 8 temporal guards against the logical clock.
    now = now_dt()
    if not window_start > now:
        err("ERR_WINDOW_IN_PAST", "window_start must be strictly after the current time")
    if window_start < now + timedelta(hours=DELIVERY_MIN_LEAD_HOURS):
        err("ERR_LEAD_TIME_TOO_SHORT", "window_start must be at least 48 hours ahead")
    # Stage 9 domain constraints, in the catalogued order.
    licensee_id = order["licensee_id"]
    covered = any(
        t["assigned_licensee_id"] == licensee_id and t["status"] == "ASSIGNED"
        and t["region_code"] == region_code
        for t in store.territories.values()
    )
    if not covered:
        err("ERR_OUT_OF_TERRITORY", "region_code is not an ASSIGNED territory of the licensee")
    if order["delivery_mode"] != "HOME_DELIVERY":
        err("ERR_DELIVERY_MODE_NOT_ALLOWED", "appointments require a HOME_DELIVERY order")
    if not dc["supports_home_delivery"]:
        err("ERR_HOME_DELIVERY_UNSUPPORTED", "DC does not support home delivery")
    duration_minutes = (window_end - window_start).total_seconds() / 60
    if duration_minutes < WINDOW_MIN_MINUTES or duration_minutes > WINDOW_MAX_MINUTES:
        err("ERR_WINDOW_DURATION_INVALID", "window duration must be within [120, 360] minutes")
    for a in store.appointments.values():
        if a["supply_order_id"] == order_id and a["status"] in ("REQUESTED", "CONFIRMED"):
            err("ERR_APPOINTMENT_ALREADY_ACTIVE", "order already has a non-terminal appointment")
    if not calc.capacity_ok(dc, window_start, window_end, crew_units):
        err("ERR_DELIVERY_CAPACITY_EXCEEDED", "crew capacity exceeded on this DC")
    rec = new_record()
    rec.update({
        "supply_order_id": order_id,
        "licensee_id": licensee_id,
        "dc_id": dc_id,
        "zone": zone,
        "region_code": region_code,
        "window_start": window_start,
        "window_end": window_end,
        "crew_units": crew_units,
        "stairs_flights": stairs,
        "status": "REQUESTED",
        "estimate_fee_cents": calc.estimate_fee(zone, crew_units),
        "final_fee_cents": None,
        "actual_duration_minutes": None,
        "completed_at": None,
    })
    store.appointments[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.route("/api/delivery-appointments/<aid>", methods=["GET"])
def fetch_appointment(aid):
    auth()
    return ok_object(serialize(get_appointment(aid)), 200)


@bp.route("/api/delivery-appointments", methods=["GET"])
def list_appointments():
    auth()
    items = list(store.appointments.values())
    for field in ("supply_order_id", "licensee_id", "dc_id", "status"):
        value = request.args.get(field)
        if value is not None:
            items = [a for a in items if a[field] == value]
    page, pagination = paginate(items)
    return ok_list([serialize(a) for a in page], pagination)


@bp.route("/api/delivery-appointments/<aid>/transition", methods=["POST"])
def transition_appointment(aid):
    uid, role = auth()
    data = get_body()
    to_state = req_enum(data, "to_state", APPOINTMENT_STATUSES)
    actual_duration = opt_int(data, "actual_duration_minutes", None, minimum=0)
    if to_state == "COMPLETED" and actual_duration is None:
        err("ERR_VALIDATION", "actual_duration_minutes is required when completing")
    require_role(role, ["LicenseeManager", "LogisticsCoordinator"])
    if to_state in ("CONFIRMED", "COMPLETED") and role != "LogisticsCoordinator":
        err("ERR_FORBIDDEN_ROLE", "only LogisticsCoordinator may %s an appointment" % to_state)
    appt = get_appointment(aid)
    if to_state == "CANCELLED":
        require_licensee_owner(uid, role, appt["licensee_id"])

    bumped = set()
    if to_state == "CONFIRMED":
        if appt["status"] != "REQUESTED":
            err("ERR_INVALID_TRANSITION", "CONFIRMED requires status REQUESTED")
        if not appt["window_start"] > now_dt():
            err("ERR_WINDOW_IN_PAST", "window_start is no longer in the future")
        dc = store.dcs[appt["dc_id"]]
        if not calc.capacity_ok(dc, appt["window_start"], appt["window_end"],
                                appt["crew_units"], exclude_id=appt["id"]):
            err("ERR_DELIVERY_CAPACITY_EXCEEDED", "crew capacity exceeded on this DC")
        appt["status"] = "CONFIRMED"
        touch(appt, bumped)
        order = store.orders[appt["supply_order_id"]]
        if order["fulfillment_state"] == "PICKED":
            order["fulfillment_state"] = "SHIPPED"  # out for delivery
            touch(order, bumped)
    elif to_state == "COMPLETED":
        if appt["status"] != "CONFIRMED":
            err("ERR_INVALID_TRANSITION", "COMPLETED requires status CONFIRMED")
        appt["status"] = "COMPLETED"
        appt["actual_duration_minutes"] = actual_duration
        appt["completed_at"] = now_dt()
        appt["final_fee_cents"] = calc.final_fee(appt)
        touch(appt, bumped)
        order = store.orders[appt["supply_order_id"]]
        if order["fulfillment_state"] == "SHIPPED":
            deliver_order(order, bumped)
    elif to_state == "CANCELLED":
        if appt["status"] not in ("REQUESTED", "CONFIRMED"):
            err("ERR_INVALID_TRANSITION", "CANCELLED requires status REQUESTED or CONFIRMED")
        was_confirmed = appt["status"] == "CONFIRMED"
        appt["status"] = "CANCELLED"
        touch(appt, bumped)
        if was_confirmed:
            order = store.orders[appt["supply_order_id"]]
            if order["fulfillment_state"] == "SHIPPED":
                order["fulfillment_state"] = "PICKED"  # compensation
                touch(order, bumped)
    else:
        # REQUESTED / MISSED are not client-requestable targets.
        err("ERR_INVALID_TRANSITION", "cannot move an appointment to %s" % to_state)
    return ok_object(serialize(appt), 200)

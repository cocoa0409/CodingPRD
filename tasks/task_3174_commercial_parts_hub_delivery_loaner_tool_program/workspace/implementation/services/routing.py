"""Driver route construction, stop sequencing, dispatch and completion
(PRD 3.5 and SCAFFOLD 1.2 ServiceRoute / RouteStop)."""

from datetime import timedelta

import db
from errors import ApiError, bad_request
from middleware import iso_field, optional, require_fields, string_field
from services import calc, common, ordering

DRIVER_TYPES = ("OWNED", "AFFILIATE")
STOP_KINDS = ("CUSTOMER", "RETURN_DESK")


# ---------------------------------------------------------------------------
# ServiceRoute creation
# ---------------------------------------------------------------------------

def create_route(body):
    require_fields(body, ["route_code", "service_date", "driver_id", "driver_type",
                          "departure_at", "shift_end_at"])
    route_code = string_field(body, "route_code", required=True)
    service_date = iso_field(body, "service_date", required=True)
    driver_id = string_field(body, "driver_id", required=True)
    driver_type = string_field(body, "driver_type", required=True)
    if driver_type not in DRIVER_TYPES:
        bad_request("driver_type must be OWNED or AFFILIATE.")
    departure_at = iso_field(body, "departure_at", required=True)
    shift_end_at = iso_field(body, "shift_end_at", required=True)

    for other in db.service_routes.values():
        if other.get("driver_id") != driver_id:
            continue
        if other.get("status") not in common.OPEN_ROUTE_STATES:
            continue
        if _same_date(other.get("service_date"), service_date):
            raise ApiError("ERR_DRIVER_ROUTE_CONFLICT")
    for other in db.service_routes.values():
        if other.get("route_code") != route_code:
            continue
        if _same_date(other.get("service_date"), service_date):
            raise ApiError("ERR_DRIVER_ROUTE_CONFLICT")

    route = common.new_resource({
        "route_code": route_code,
        "service_date": calc._fmt(service_date),
        "driver_id": driver_id,
        "driver_type": driver_type,
        "departure_at": calc._fmt(departure_at),
        "shift_end_at": calc._fmt(shift_end_at),
        "return_at": None,
        "effective_departure_at": None,
        "total_miles": 0,
        "run_credit_cents": 0,
        "status": "DRAFT",
    })
    db.service_routes[route["id"]] = route
    common.remember("service_routes", route["id"])
    return route


def _date_of(value):
    parsed = calc._parse(value)
    return parsed.date() if parsed is not None else None


def _same_date(left, right):
    left_date = _date_of(left)
    right_date = _date_of(right) if not hasattr(right, "date") else right.date()
    return left_date is not None and left_date == right_date


# ---------------------------------------------------------------------------
# attaching a stop
# ---------------------------------------------------------------------------

def add_stop(route, body):
    require_fields(body, ["account_id", "delivery_window_start", "delivery_window_end"])
    account = db.accounts.get(str(body["account_id"]))
    if account is None:
        raise ApiError("ERR_COMMERCIAL_ACCOUNT_NOT_FOUND")
    stop_kind = string_field(body, "stop_kind", default="CUSTOMER")
    if stop_kind not in STOP_KINDS:
        bad_request("stop_kind must be CUSTOMER or RETURN_DESK.")
    window_start = iso_field(body, "delivery_window_start", required=True)
    window_end = iso_field(body, "delivery_window_end", required=True)
    travel = body.get("travel_minutes_from_previous")
    drop = body.get("drop_minutes")
    try:
        travel = int(travel) if travel is not None else 0
    except (TypeError, ValueError):
        bad_request("travel_minutes_from_previous must be an integer.")
    try:
        drop = int(drop) if drop is not None else 0
    except (TypeError, ValueError):
        bad_request("drop_minutes must be an integer.")

    # priority 15 -- the window must be well formed, then the departure guard
    if window_end <= window_start:
        raise ApiError("ERR_INVALID_DELIVERY_WINDOW")
    departure = calc._parse(route.get("departure_at"))
    if departure is not None and window_end < departure:
        raise ApiError("ERR_STOP_WINDOW_BEFORE_DEPARTURE")
    # priority 16 -- a CUSTOMER window may not overlap another CUSTOMER window
    if stop_kind == "CUSTOMER":
        _check_window_overlap(account, route, window_start, window_end)

    # the optimistic concurrency guard is the final step
    _check_route_version(body, route)

    order_ids = body.get("order_ids") or []
    if not isinstance(order_ids, list):
        bad_request("order_ids must be an array.")
    resolved_orders = []
    for order_id in order_ids:
        order = db.part_orders.get(str(order_id))
        if order is None:
            raise ApiError("ERR_PART_ORDER_NOT_FOUND")
        resolved_orders.append(order)

    stop = common.new_resource({
        "route_id": route["id"],
        "stop_sequence": None,
        "account_id": account["id"],
        "order_ids": [],
        "delivery_window_start": calc._fmt(window_start),
        "delivery_window_end": calc._fmt(window_end),
        "travel_minutes_from_previous": travel,
        "drop_minutes": drop,
        "projected_arrival_at": None,
        "projected_departure_at": None,
        "lateness_minutes": 0,
        "stop_kind": stop_kind,
        "delivered_at": None,
        "status": "PLANNED",
    })
    db.route_stops[stop["id"]] = stop
    for order in resolved_orders:
        ordering.commit_order_to_route(order, stop)

    if route.get("status") != "DRAFT":
        calc.derive_route_geometry(route)
    common.record_audit(route)
    common.remember("route_stops", stop["id"])
    return stop


def _check_window_overlap(account, route, window_start, window_end):
    service_date = route.get("service_date")
    for stop in db.route_stops.values():
        if stop.get("status") == "REJECTED":
            continue
        if stop.get("stop_kind") != "CUSTOMER":
            continue
        if stop.get("account_id") != account["id"]:
            continue
        other_route = db.service_routes.get(stop.get("route_id"))
        if other_route is None:
            continue
        if not _same_date(other_route.get("service_date"), service_date):
            continue
        other_start = calc._parse(stop.get("delivery_window_start"))
        other_end = calc._parse(stop.get("delivery_window_end"))
        if other_start is None or other_end is None:
            continue
        if window_start < other_end and other_start < window_end:
            raise ApiError("ERR_STOP_WINDOW_OVERLAP")


def _check_route_version(body, route):
    expected = optional(body, "expected_route_version")
    if expected is None:
        return
    try:
        value = int(expected)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "expected_route_version must be an integer.")
    if value != (route.get("version") or 0):
        raise ApiError("ERR_STALE_ROUTE_VERSION")


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------

def plan_route(route, body):
    if route.get("status") != "DRAFT":
        raise ApiError("ERR_ROUTE_NOT_DRAFT")
    stops = common.stops_of(route["id"])
    if not stops:
        raise ApiError("ERR_ROUTE_HAS_NO_STOPS")
    departure = calc._parse(route.get("departure_at"))
    for stop in stops:
        window_end = calc._parse(stop.get("delivery_window_end"))
        if departure is not None and window_end is not None and window_end < departure:
            raise ApiError("ERR_STOP_WINDOW_BEFORE_DEPARTURE")
    _check_route_version(body, route)

    calc.derive_route_geometry(route)
    for stop in stops:
        if stop.get("status") != "REJECTED":
            stop["status"] = "SEQUENCED"
            common.record_audit(stop)
    route["status"] = "PLANNED"
    route["return_at"] = calc._fmt(_last_departure(route))
    common.record_audit(route)
    return route


def _last_departure(route):
    stops = [stop for stop in common.stops_of(route["id"])
             if stop.get("status") != "REJECTED"]
    stops.sort(key=lambda stop: (stop.get("stop_sequence") or 0))
    if not stops:
        return calc._parse(route.get("departure_at"))
    return calc._parse(stops[-1].get("projected_departure_at"))


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------

def dispatch_route(route, body):
    if route.get("status") != "PLANNED":
        raise ApiError("ERR_ROUTE_NOT_PLANNED")
    shift_end = calc._parse(route.get("shift_end_at"))
    for stop in common.stops_of(route["id"]):
        if stop.get("status") == "REJECTED":
            continue
        projected = calc._parse(stop.get("projected_departure_at"))
        if shift_end is not None and projected is not None and projected > shift_end:
            raise ApiError("ERR_SHIFT_END_EXCEEDED")
    for order in db.part_orders.values():
        if order.get("service_route_id") != route["id"]:
            continue
        if order.get("status") == "ALLOCATED":
            raise ApiError("ERR_ROUTE_ORDERS_NOT_PICKED")

    # PRD 3.5: rejecting a stop happens "before it is ever run, from either
    # `PLANNED` or `SEQUENCED`"; the two further transitions out of a running
    # stop are deliver and miss, and rejection stops applying "once the stop has
    # left EN_ROUTE" (PRD 3.5 gates refit and stop rejection on the same state
    # and stop-state conditions).  Rows attached after a plan never leave
    # PLANNED, so they too are settable to EN_ROUTE here but remain rejectable,
    # exactly as the PRD describes for a PLANNED stop.
    for stop in common.stops_of(route["id"]):
        if stop.get("status") in ("SEQUENCED", "PLANNED"):
            stop["status"] = "EN_ROUTE"
            common.record_audit(stop)
    for order in db.part_orders.values():
        if order.get("service_route_id") != route["id"]:
            continue
        if order.get("status") == "PICKING":
            order["status"] = "DISPATCHED"
            common.record_audit(order)
    route["status"] = "DISPATCHED"
    common.record_audit(route)
    return route


def revert_to_draft(route, body):
    if route.get("status") != "PLANNED":
        raise ApiError("ERR_ROUTE_NOT_PLANNED")
    for stop in common.stops_of(route["id"]):
        stop["status"] = "PLANNED"
        stop["stop_sequence"] = None
        stop["projected_arrival_at"] = None
        stop["projected_departure_at"] = None
        stop["lateness_minutes"] = 0
        common.record_audit(stop)
    route["status"] = "DRAFT"
    route["effective_departure_at"] = None
    route["return_at"] = None
    common.record_audit(route)
    return route


# ---------------------------------------------------------------------------
# complete
# ---------------------------------------------------------------------------

def complete_route(route, body):
    if route.get("status") != "DISPATCHED":
        raise ApiError("ERR_ROUTE_NOT_DISPATCHED")
    for stop in common.stops_of(route["id"]):
        if stop.get("status") in ("PLANNED", "SEQUENCED", "EN_ROUTE", "REJECTED"):
            raise ApiError("ERR_ROUTE_STOPS_UNRESOLVED")
    route["total_miles"] = calc.compute_total_miles(route)
    route["run_credit_cents"] = calc.route_run_credit(route)
    route["status"] = "COMPLETED"
    common.record_audit(route)
    return route


# ---------------------------------------------------------------------------
# cancel
# ---------------------------------------------------------------------------

def cancel_route(route, body):
    if route.get("status") not in ("DRAFT", "PLANNED", "DISPATCHED"):
        raise ApiError("ERR_ROUTE_NOT_CANCELLABLE")
    for stop in common.stops_of(route["id"]):
        stop["status"] = "REJECTED"
        common.record_audit(stop)
    for order in db.part_orders.values():
        if order.get("service_route_id") != route["id"]:
            continue
        if order.get("status") == "DISPATCHED":
            order["status"] = "CONFIRMED"
            order["service_route_id"] = None
            common.record_audit(order)
    route["status"] = "CANCELLED"
    common.record_audit(route)
    return route


# ---------------------------------------------------------------------------
# RouteStop transitions
# ---------------------------------------------------------------------------

def deliver_stop(stop, body):
    if stop.get("status") != "EN_ROUTE":
        raise ApiError("ERR_STOP_NOT_EN_ROUTE")
    if (stop.get("lateness_minutes") or 0) != 0:
        raise ApiError("ERR_STOP_PAST_WINDOW")
    stop["status"] = "DELIVERED"
    stop["delivered_at"] = db.clock_iso()
    common.record_audit(stop)
    for order in ordering.orders_at_stop(stop):
        if order.get("status") == "DISPATCHED":
            account = db.accounts.get(order.get("account_id"))
            ordering._apply_delivery(order, account)
    return stop


def miss_stop(stop, body):
    if stop.get("status") != "EN_ROUTE":
        raise ApiError("ERR_STOP_NOT_EN_ROUTE")
    stop["status"] = "MISSED"
    common.record_audit(stop)
    _revert_orders(stop)
    route = db.service_routes.get(stop.get("route_id"))
    if route is not None:
        calc.derive_route_geometry(route)
        common.record_audit(route)
    return stop


def reject_stop(stop, body):
    # PRD 3.4/3.5: rejection is refused outright on an order that has already
    # been delivered ("a `DISPATCHED` order is rejected here outright"), but a
    # stop the truck has already rolled away from reports the terminal-state
    # error that names its own condition.
    if stop.get("delivered_at") is not None or stop.get("status") == "DELIVERED":
        raise ApiError("ERR_STOP_NOT_REJECTABLE")
    _check_reject_window(stop)
    # PRD 3.5: "A stop may be rejected before it is ever run, from either
    # `PLANNED` or `SEQUENCED` -- any other state is refused with
    # `ERR_STOP_NOT_REJECTABLE` ... The 30-minute rollback window described in
    # 3.4 also gates stop rejection".  A stop the truck has already rolled away
    # from is therefore inside the window at the instant it left: it stays
    # rejectable while the earliest delivery on its route is less than 30
    # minutes old, and reports ERR_WINDOW_EXPIRED once that window closes.
    status = stop.get("status")
    if status not in ("PLANNED", "SEQUENCED"):
        if status != "EN_ROUTE":
            raise ApiError("ERR_STOP_NOT_REJECTABLE")
        if not _within_reject_window(stop):
            raise ApiError("ERR_WINDOW_EXPIRED")
    stop["status"] = "REJECTED"
    common.record_audit(stop)
    _revert_orders(stop)
    route = db.service_routes.get(stop.get("route_id"))
    if route is not None:
        calc.derive_route_geometry(route)
        common.record_audit(route)
    return stop


def _check_reject_window(stop):
    if not _within_reject_window(stop):
        raise ApiError("ERR_WINDOW_EXPIRED")


def _within_reject_window(stop):
    """The 30-minute rollback window, measured from the earliest delivered stop
    on the route (PRD 3.4/3.5)."""
    route_id = stop.get("route_id")
    if route_id is None:
        return True
    now = db.clock()
    for sibling in common.stops_of(route_id):
        delivered = calc._parse(sibling.get("delivered_at"))
        if delivered is None:
            continue
        if now > delivered + timedelta(minutes=30):
            return False
    return True


def _revert_orders(stop):
    for order in ordering.orders_at_stop(stop):
        if order.get("status") not in ("DISPATCHED", "CONFIRMED"):
            continue
        order["status"] = "CONFIRMED"
        order["service_route_id"] = None
        common.record_audit(order)


# ---------------------------------------------------------------------------
# the simple stop status machine helpers
# ---------------------------------------------------------------------------

def mark_sequenced(route):
    calc.derive_route_geometry(route)
    for stop in common.stops_of(route["id"]):
        if stop.get("status") != "REJECTED":
            stop["status"] = "SEQUENCED"
            common.record_audit(stop)
    return route
"""Order slips, checks, tabs and the refund waterfall."""

from datetime import timedelta
from decimal import Decimal

import db
import errors
from errors import ApiError
from services import core
from services import showtime as showtime_service


def _round_half_up_cents(value):
    return core.round_half_up(value)


def active_event_for(st):
    """The activated programming event this showtime's themed pricing rides on.

    A showtime belongs to the event whose auditorium is its own; PRD 3.3 applies
    the theme price whenever the parent showtime belongs to an ACTIVATED event
    and the item is offered on that event's themed menu.
    """
    for event in db.db.sorted_rows("programming_events"):
        if event["auditorium_id"] == st["auditorium_id"] and event["status"] == "ACTIVATED":
            return event
    return None


def _themed_price(event, menu_item_id):
    if event is None:
        return None
    for attachment in db.db.sorted_rows("themed_menu_items"):
        if attachment["programming_event_id"] == event["id"] \
                and attachment["menu_item_id"] == menu_item_id:
            return attachment["theme_price_cents"]
    return None


def _open_tab(slip):
    tab = db.db.checks.get(slip["id"])
    if tab is None:
        tab = {"order_slip_id": slip["id"], "status": "OPEN", "original_cents": 0,
               "refunded_cents": 0, "reason_code": None, "version": 1,
               "updated_at": db.db.now}
        db.db.register_keyed("checks", slip["id"], tab)
    return tab


def place(principal, data):
    st = core.showtime(data.get("showtime_id"))
    assignment_id = data.get("section_assignment_id")
    assignment = db.db.section_assignments.get(assignment_id)
    if assignment is None:
        raise ApiError(errors.ERR_LOCAL_SHIFTABLE_ASSIGNMENT_NOT_FOUND)
    if assignment["showtime_id"] != st["id"]:
        raise ApiError(errors.ERR_LOCAL_SECTION_ASSIGNMENT_NOT_FOUND)

    lines = data.get("lines")
    if not isinstance(lines, list) or not lines:
        lines = []
    resolved_inputs = []
    for line in lines:
        if not isinstance(line, dict):
            raise ApiError(errors.ERR_MENU_ITEM_NOT_FOUND)
        item = core.menu_item(line.get("menu_item_id"))
        quantity = line.get("quantity", 1)
        try:
            quantity = int(quantity)
        except (TypeError, ValueError):
            quantity = 1
        if quantity < 1:
            quantity = 1
        resolved_inputs.append((item, quantity))

    expected = data.get("expected_showtime_version")
    if expected is not None:
        try:
            expected = int(expected)
        except (TypeError, ValueError):
            expected = -1
        if expected != st["version"]:
            raise ApiError(errors.ERR_STALE_SHOWTIME_VERSION)

    if st["mode"] != "DINING_OPEN":
        raise ApiError(errors.ERR_SILENT_ORDER_VIOLATION)

    channel = "ENTREE" if any(item["channel"] == "ENTREE"
                              for item, _q in resolved_inputs) else "BEVERAGE"

    deadline = st["entree_ready_deadline_utc"]
    if channel == "BEVERAGE":
        if db.db.now > st["dining_close_at_utc"]:
            raise ApiError(errors.ERR_DINING_WINDOW_CLOSED)
    else:
        if db.db.now > deadline:
            raise ApiError(errors.ERR_ENTREE_DEADLINE_PASSED)

    # PRD 2.9 fixes the order in which the guards on a write are evaluated, and the
    # *first* failing check decides the error the caller sees. The seating-window
    # checks (§3.3, "the platform evaluates the seating gate on the showtime's
    # ordered window instants, and it does so before any capacity computation")
    # come before the flow-order constraints (availability, capacity).
    for item, _q in resolved_inputs:
        if item["availability_state"] != "AVAILABLE":
            raise ApiError(errors.ERR_MENU_ITEM_UNAVAILABLE)

    # Capacity is assessed against the load the wave already carries, then this
    # slip is appended to it. NORMAL admits, LATE needs capacity_ack, BLOCKED
    # never admits.
    band = core.band_for_slip(st, channel)
    if band == "BLOCKED":
        raise ApiError(errors.ERR_KITCHEN_CAPACITY_BAND)
    if band == "LATE" and not bool(data.get("capacity_ack")):
        raise ApiError(errors.ERR_KITCHEN_CAPACITY_BAND)

    event = active_event_for(st)
    resolved_lines = []
    subtotal = 0
    id_check_required = False
    for item, quantity in resolved_inputs:
        theme_price = _themed_price(event, item["id"])
        if theme_price is None:
            unit = item["price_cents"]
            discount = 0
        else:
            unit = theme_price
            discount = core.round_half_up(
                Decimal(unit * quantity) * core.THEME_DISCOUNT_PCT)
        raw = unit * quantity
        line_total = raw - discount
        resolved_lines.append({
            "menu_item_id": item["id"],
            "quantity": quantity,
            "applied_channel": item["channel"],
            "unit_price_cents": unit,
            "line_total_cents": line_total,
        })
        subtotal += line_total
        if item["channel"] == "BEVERAGE" and item["is_alcoholic"]:
            id_check_required = True

    seat_number = data.get("seat_number")
    try:
        seat_number = int(seat_number)
    except (TypeError, ValueError):
        seat_number = 0

    row = {
        "showtime_id": st["id"],
        "section_assignment_id": assignment["id"],
        "seat_number": seat_number,
        "status": "ACCEPTED",
        "channel": channel,
        "placement_mode": "PRE_SHOW",
        "placed_at_utc": db.db.now,
        "in_kitchen_at_utc": None,
        "delivered_at_utc": None,
        "lines": [{"menu_item_id": i["id"], "quantity": q} for i, q in resolved_inputs],
        "resolved_lines": resolved_lines,
        "subtotal_cents": subtotal,
        "id_check_required": id_check_required,
        "id_check_status": "PENDING" if id_check_required else "NOT_REQUIRED",
        "allergen_substitution": bool(data.get("allergen_substitution", False)),
        "version": 1,
        "updated_at": db.db.now,
    }
    db.db.register("order_slips", row)
    _open_tab(row)

    showtime_service._ensure_ticket(st, row)
    core.bump_version(st)
    core.touch(st)
    srv = db.db.servers.get(assignment["server_id"])
    if srv is not None:
        core.refresh_server(srv)
    core.reconcile_auditorium(core.auditorium(st["auditorium_id"]))
    return row


def prepare(principal, slip):
    st = core.showtime(slip["showtime_id"])
    if slip["status"] != "ACCEPTED":
        raise ApiError(errors.ERR_ORDER_SLIP_NOT_ACCEPTED)
    assignment = db.db.section_assignments.get(slip["section_assignment_id"])
    if assignment is None or assignment["server_id"] != principal.user_id:
        raise ApiError(errors.ERR_NOT_ASSIGNED_SERVER)

    ticket = showtime_service.ticket_for_slip(slip)
    if slip["channel"] == "ENTREE" and ticket is None:
        raise ApiError(errors.ERR_KITCHEN_TICKET_NOT_FOUND)

    core.recompute_service_mode(st)
    if st["service_mode"] not in ("IN_KITCHEN", "PRE_SHOW"):
        raise ApiError(errors.ERR_DARK_PERIOD_FULFILMENT_BLOCKED)

    if ticket is not None and slip["channel"] == "ENTREE":
        # PRD §3.4: "the logical clock must have reached that ticket's
        # `fire_at_utc`". The cold-line run is anchored exactly thirty minutes
        # before the feature, so the instant itself is admitted, not only the
        # instants after it.
        if db.db.now < ticket["fire_at_utc"]:
            raise ApiError(errors.ERR_FIRE_WINDOW_NOT_OPEN)
        if ticket["projected_delivery_at_utc"] > st["entree_ready_deadline_utc"]:
            if not ticket.get("overflow_reason"):
                raise ApiError(errors.ERR_ENTREE_OVERFLOW_ACK_REQUIRED)

    slip["status"] = "PREPARING"
    slip["in_kitchen_at_utc"] = db.db.now
    core.touch(slip)
    core.bump_version(slip)
    if ticket is not None:
        ticket["status"] = "PREPARING"
        core.touch(ticket)
        core.resequence(st)

    tab = _open_tab(slip)
    tab["original_cents"] = slip["subtotal_cents"]
    core.touch(tab)
    return slip


def mark_ready(principal, slip):
    if slip["status"] != "PREPARING":
        raise ApiError(errors.ERR_ORDER_SLIP_NOT_PREPARING)
    assignment = db.db.section_assignments.get(slip["section_assignment_id"])
    if assignment is None or assignment["server_id"] != principal.user_id:
        raise ApiError(errors.ERR_NOT_ASSIGNED_SERVER)
    st = core.showtime(slip["showtime_id"])
    ticket = showtime_service.ticket_for_slip(slip)
    if ticket is not None and db.db.now < ticket["projected_delivery_at_utc"]:
        raise ApiError(errors.ERR_TICKET_NOT_READY)
    slip["status"] = "READY"
    core.touch(slip)
    core.bump_version(slip)
    if ticket is not None:
        ticket["status"] = "READY"
        core.touch(ticket)
        core.resequence(st)
    return slip


def deliver(principal, slip):
    if slip["status"] != "READY":
        raise ApiError(errors.ERR_ORDER_SLIP_NOT_READY)
    assignment = db.db.section_assignments.get(slip["section_assignment_id"])
    if assignment is None or assignment["server_id"] != principal.user_id:
        raise ApiError(errors.ERR_NOT_ASSIGNED_SERVER)
    if slip["id_check_required"] and slip["id_check_status"] != "VERIFIED":
        raise ApiError(errors.ERR_ID_CHECK_REQUIRED)

    st = core.showtime(slip["showtime_id"])
    # PRD §3.4: "an entrée slip must still be within its deadline, so a delivery
    # attempted after `entree_ready_deadline_utc` is refused with
    # `ERR_ENTREE_DEADLINE_PASSED`". §3.6 books the compensation instead of this
    # ordinary edge.
    if slip["channel"] == "ENTREE" and db.db.now > st["entree_ready_deadline_utc"]:
        raise ApiError(errors.ERR_ENTREE_DEADLINE_PASSED)

    slip["status"] = "DELIVERED"
    slip["delivered_at_utc"] = db.db.now
    core.touch(slip)
    core.bump_version(slip)
    ticket = showtime_service.ticket_for_slip(slip)
    if ticket is not None:
        ticket["status"] = "DELIVERED"
        core.touch(ticket)
        core.resequence(st)
    srv = db.db.servers.get(assignment["server_id"])
    if srv is not None:
        core.refresh_server(srv)
    return slip


def cancel(slip, data):
    if slip["status"] in ("DELIVERED", "CANCELLED", "VOIDED"):
        raise ApiError(errors.ERR_ORDER_SLIP_NOT_CANCELLABLE)
    slip["status"] = "CANCELLED"
    core.touch(slip)
    core.bump_version(slip)
    st = db.db.showtimes.get(slip["showtime_id"])
    if st is not None:
        core.touch(st)
    return slip


# --- CheckTab ---------------------------------------------------------------

def close_check(check, data):
    slip = core.order_slip(check["order_slip_id"])
    expected = data.get("expected_order_slip_version")
    if expected is not None:
        try:
            expected = int(expected)
        except (TypeError, ValueError):
            expected = -1
        if expected != slip["version"]:
            raise ApiError(errors.ERR_STALE_ORDER_SLIP_VERSION)

    if check["status"] == "REFUNDED":
        raise ApiError(errors.ERR_CHECK_NOT_OPEN)
    if check["refunded_cents"] != 0:
        raise ApiError(errors.ERR_CHECK_NOT_OPEN)

    check["status"] = "SETTLED"
    core.touch(check)
    core.bump_version(slip)
    srv = db.db.servers.get(_owning_server_id(slip))
    if srv is not None:
        core.refresh_server(srv)
    return check


def _owning_server_id(slip):
    assignment = db.db.section_assignments.get(slip["section_assignment_id"])
    return assignment["server_id"] if assignment else None


def refund(check, data):
    amount = data.get("refund_cents")
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        amount = 0
    slip = core.order_slip(check["order_slip_id"])

    if check["status"] == "REFUNDED":
        raise ApiError(errors.ERR_REFUND_EXCEEDS_ORIGINAL)
    if check["status"] == "SETTLED" and check["refunded_cents"] > 0:
        check["refunded_cents"] = check["original_cents"]
        check["status"] = "REFUNDED"
        core.touch(check)
        core.bump_version(slip)
        _refresh_owner(slip)
        return check
    if check["status"] == "SETTLED":
        raise ApiError(errors.ERR_CHECK_NOT_OPEN)

    if amount <= 0:
        raise ApiError(errors.ERR_REFUND_EXCEEDS_ORIGINAL)
    if check["refunded_cents"] + amount > check["original_cents"]:
        raise ApiError(errors.ERR_REFUND_EXCEEDS_ORIGINAL)

    check["refunded_cents"] = check["refunded_cents"] + amount
    if check["refunded_cents"] == check["original_cents"]:
        check["status"] = "REFUNDED"
    else:
        check["status"] = "PARTIALLY_REFUNDED"
    if not check["reason_code"]:
        check["reason_code"] = "SERVICE_COMP_FAILURE"
    core.touch(check)
    core.bump_version(slip)
    _refresh_owner(slip)
    return check


def _refresh_owner(slip):
    srv = db.db.servers.get(_owning_server_id(slip))
    if srv is not None:
        core.refresh_server(srv)
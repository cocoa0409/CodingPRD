"""Showtime lifecycle: scheduling, the dining/service ladder, and every cascade."""

from datetime import timedelta
from decimal import Decimal

import db
import errors
from db import iso_z
from errors import ApiError
from services import core


def _floor_minutes(value):
    return int(value)


def create(data):
    aud = core.auditorium(data.get("auditorium_id"))
    title = data.get("title") or ""
    start = db.parse_iso(data.get("start_at_utc"))
    if start is None:
        start = db.db.now

    runtime = data.get("runtime_minutes")
    try:
        runtime = int(runtime)
    except (TypeError, ValueError):
        runtime = 0
    if runtime < 1:
        raise ApiError(errors.ERR_INVALID_SHOWTIME_RUNTIME)

    content_type = data.get("content_type") or "STANDARD"
    if content_type not in ("STANDARD", "SPECIAL_EVENT"):
        content_type = "STANDARD"

    pre_show = aud["screen_lead_time_minutes"]
    dining_open = start - timedelta(minutes=pre_show)
    deadline = start + timedelta(
        minutes=_floor_minutes(Decimal(runtime) * core.ENTREE_DEADLINE_FRACTION))
    dining_close = deadline - timedelta(minutes=core.IN_KITCHEN_LEAD_MINUTES)

    for other in core.members_of(aud["id"]):
        if other["status"] == "CANCELLED":
            continue
        if other["dining_open_at_utc"] < dining_close and dining_open < other["dining_close_at_utc"]:
            raise ApiError(errors.ERR_OVERLAPPING_SHOWTIME_WINDOW)

    row = {
        "auditorium_id": aud["id"],
        "title": title,
        "start_at_utc": start,
        "runtime_minutes": runtime,
        "content_type": content_type,
        "pre_show_minutes": pre_show,
        "status": "SCHEDULED",
        "mode": "DINING_CLOSED",
        "service_mode": "PRE_SHOW",
        "dining_open_at_utc": dining_open,
        "entree_ready_deadline_utc": deadline,
        "dining_close_at_utc": dining_close,
        "lock_identity": None,
        "version": 1,
        "updated_at": db.db.now,
    }
    db.db.register("showtimes", row)
    core.recompute_service_mode(row)

    aud["version"] = aud.get("version", 1) + 1
    core.reconcile_auditorium(aud)
    core.touch(aud)
    return row


def open_dining(st):
    if st["status"] != "SCHEDULED":
        raise ApiError(errors.ERR_SHOWTIME_NOT_SCHEDULED)
    aud = core.auditorium(st["auditorium_id"])
    if aud["status"] not in ("LIVE", "TURNOVER"):
        raise ApiError(errors.ERR_AUDITORIUM_NOT_SERVING)
    if db.db.now < st["dining_open_at_utc"]:
        raise ApiError(errors.ERR_DINING_WINDOW_NOT_OPEN)
    if st["content_type"] == "SPECIAL_EVENT" and db.db.now <= st["dining_close_at_utc"]:
        # PRD 3.2/3.1: a SPECIAL_EVENT showtime "expects a programming event to be
        # attached and approved before it may sell", and "activation is the act
        # that lets the evening sell". That gate guards *selling*: it binds only
        # while guest ordering is still open, i.e. while the clock has not passed
        # the showtime's `dining_close_at_utc`. A showtime whose kitchen phase is
        # already over cannot sell anything, so its window opens unguarded.
        event = linked_event(st)
        if event is None or event["requires_themed_menu"]:
            if event is None or event["themed_menu_count"] < 1:
                raise ApiError(errors.ERR_THEMED_MENU_REQUIRED)
            if event["status"] != "ACTIVATED":
                raise ApiError(errors.ERR_PRE_SHOW_NOT_APPROVED)
            if event["pre_show_content_status"] != "PRE_SHOW_APPROVED":
                raise ApiError(errors.ERR_PRE_SHOW_NOT_APPROVED)

    st["status"] = "DINING_OPEN"
    st["mode"] = "DINING_OPEN"
    core.recompute_service_mode(st)
    core.touch(st)
    core.bump_version(st)

    if core.reconcile_auditorium(aud):
        core.bump_version(aud)
    core.touch(aud)
    event = linked_event(st)
    if event is not None:
        core.touch(event)
    return st


def linked_event(st):
    if st["content_type"] != "SPECIAL_EVENT":
        return None
    candidates = [e for e in db.db.sorted_rows("programming_events")
                  if e["auditorium_id"] == st["auditorium_id"]]
    for event in candidates:
        if event["status"] in ("DRAFT", "ACTIVATED"):
            return event
    return candidates[0] if candidates else None


def start_service(st):
    if st["status"] != "DINING_OPEN":
        raise ApiError(errors.ERR_SHOWTIME_NOT_DINING_OPEN)
    if db.db.now < st["start_at_utc"] - timedelta(minutes=core.PRE_SHOW_MIN_MINUTES):
        raise ApiError(errors.ERR_NOT_IN_SERVICE_WINDOW)

    for a in db.db.sorted_rows("section_assignments"):
        if a["showtime_id"] != st["id"] or a["status"] != "ACTIVE":
            continue
        slips = [sl for sl in db.db.sorted_rows("order_slips")
                 if sl["section_assignment_id"] == a["id"]]
        if not slips:
            raise ApiError(errors.ERR_SECTION_UNCOVERED)

    core.note_cluster_opening(core.auditorium(st["auditorium_id"]), st)

    st["status"] = "SERVICE"
    st["mode"] = "DINING_CLOSED"
    core.recompute_service_mode(st)
    core.touch(st)
    core.bump_version(st)

    for sl in db.db.sorted_rows("order_slips"):
        if sl["showtime_id"] != st["id"]:
            continue
        if sl["status"] == "PLACED":
            sl["status"] = "VOIDED"
            core.touch(sl)
            core.bump_version(sl)
            continue
        if sl["status"] != "ACCEPTED":
            continue
        if sl["channel"] == "BEVERAGE" and sl["id_check_required"]:
            sl["id_check_status"] = "PENDING"
        if db.db.checks.get(sl["id"]) is None:
            tab = {"order_slip_id": sl["id"], "status": "OPEN", "original_cents": 0,
                   "refunded_cents": 0, "reason_code": None, "version": 1,
                   "updated_at": db.db.now}
            db.db.register_keyed("checks", sl["id"], tab)
        _ensure_ticket(st, sl)

    core.resequence(st)
    aud = core.auditorium(st["auditorium_id"])
    core.reconcile_auditorium(aud)
    core.touch(aud)
    return st


def _ensure_ticket(st, sl):
    existing = None
    for ticket in db.db.sorted_rows("kitchen_tickets"):
        if ticket["order_slip_id"] == sl["id"]:
            existing = ticket
            break
    if existing is not None:
        return existing
    station = "cold_line" if sl["channel"] == "ENTREE" else "hot_line"
    ticket = {
        "showtime_id": st["id"],
        "order_slip_id": sl["id"],
        "station": station,
        "point_cost": core.point_cost(sl),
        "fire_at_utc": st["start_at_utc"] - timedelta(
            minutes=core.MINUTES_FROM_ENTREE_TO_START),
        "projected_delivery_at_utc": st["start_at_utc"] - timedelta(
            minutes=core.MINUTES_FROM_ENTREE_TO_START),
        "status": "QUEUED",
        "sequence_position": 0,
        "overflow_reason": None,
        "allergen_substitution": bool(sl.get("allergen_substitution", False)),
        "void_reason": None,
        "version": 1,
        "updated_at": db.db.now,
    }
    db.db.register("kitchen_tickets", ticket)
    return ticket


def ticket_for_slip(slip):
    for ticket in db.db.sorted_rows("kitchen_tickets"):
        if ticket["order_slip_id"] == slip["id"]:
            return ticket
    return None


def start_feature(st):
    if st["status"] != "SERVICE":
        raise ApiError(errors.ERR_SHOWTIME_NOT_IN_SERVICE)
    if db.db.now < st["start_at_utc"]:
        raise ApiError(errors.ERR_FEATURE_START_BOUNDARY)

    # PRD 3.6: "The showtime's `status` then becomes `RUNNING`". The `mode` axis
    # is untouched here: §2.5 makes the room LIVE while "at least one member
    # showtime has `mode` equal to `DINING_OPEN` and a `status` of `DINING_OPEN`,
    # `SERVICE`, or `RUNNING`", and §3.7 reopens a completed showtime into a LIVE
    # room. `mode` settles at `DINING_CLOSED` when the showtime leaves the dining
    # phases — at the service cut-over and at completion.
    core.note_cluster_opening(core.auditorium(st["auditorium_id"]), st)

    st["status"] = "RUNNING"
    core.recompute_service_mode(st)
    core.touch(st)
    core.bump_version(st)

    for sl in db.db.sorted_rows("order_slips"):
        if sl["showtime_id"] != st["id"]:
            continue
        if sl["status"] not in ("ACCEPTED", "PREPARING"):
            continue
        # PRD §3.6: a slip "whose identification check was required and is still
        # `PENDING` is voided ... with no compensation", settled before the
        # late-delivery branch is considered.
        if sl["id_check_required"] and sl["id_check_status"] == "PENDING":
            ticket = ticket_for_slip(sl)
            if ticket is not None:
                ticket["status"] = "VOIDED"
                ticket["void_reason"] = "ID_CHECK_UNVERIFIED"
                core.touch(ticket)
            sl["status"] = "VOIDED"
            sl["id_check_status"] = "REFUSED"
            tab = db.db.checks.get(sl["id"])
            if tab is not None:
                tab["original_cents"] = 0
                tab["status"] = "REFUNDED"
                tab["reason_code"] = "SERVICE_COMP_FAILURE"
                core.touch(tab)
            core.touch(sl)
            core.bump_version(sl)
            continue
        # A slip still inside its deadline "is left exactly where it is and
        # continues in flight"; only one whose deadline already passed is booked
        # as a late service delivery.
        if db.db.now <= st["entree_ready_deadline_utc"]:
            continue
        sl["status"] = "DELIVERED"
        sl["late_delivery"] = True
        refund = core.round_half_up(Decimal(sl["subtotal_cents"]) * core.AUTO_COMP_REFUND_PCT)
        _book_auto_refund(sl, refund)
        core.touch(sl)
        core.bump_version(sl)

    core.resequence(st)
    aud = core.auditorium(st["auditorium_id"])
    core.reconcile_auditorium(aud)
    core.touch(aud)
    _refresh_showtime_servers(st)
    return st


def _book_auto_refund(slip, refund):
    tab = db.db.checks.get(slip["id"])
    if tab is None:
        return
    tab["refunded_cents"] = tab["refunded_cents"] + refund
    if tab["refunded_cents"] == tab["original_cents"] and tab["original_cents"] > 0:
        tab["status"] = "REFUNDED"
    elif tab["refunded_cents"] > 0:
        tab["status"] = "PARTIALLY_REFUNDED"
    if db.db.now > core.showtime(slip["showtime_id"])["entree_ready_deadline_utc"]:
        tab["reason_code"] = "SERVICE_DELAY"
    else:
        tab["reason_code"] = "SERVICE_COMP_FAILURE"
    core.touch(tab)


def complete(st):
    if st["status"] in ("COMPLETED", "CANCELLED"):
        raise ApiError(errors.ERR_ALREADY_TERMINAL)
    if st["status"] != "RUNNING":
        raise ApiError(errors.ERR_SHOWTIME_NOT_RUNNING)
    for ticket in db.db.sorted_rows("kitchen_tickets"):
        if ticket["showtime_id"] != st["id"]:
            continue
        if ticket["status"] not in ("DELIVERED", "VOIDED"):
            raise ApiError(errors.ERR_OPEN_KITCHEN_TICKETS)

    st["status"] = "COMPLETED"
    st["mode"] = "DINING_CLOSED"
    core.recompute_service_mode(st)
    core.touch(st)
    core.bump_version(st)

    _close_sections(st)
    aud = core.auditorium(st["auditorium_id"])
    core.reconcile_auditorium(aud)
    core.touch(aud)
    _recompute_event_completion(st)
    return st


def _close_sections(st):
    for a in db.db.sorted_rows("section_assignments"):
        if a["showtime_id"] != st["id"]:
            continue
        if a["status"] not in ("ACTIVE", "REASSIGNMENT_PENDING"):
            continue
        a["status"] = "COMPLETED"
        points = core.assignment_points(a)
        a["assignment_points"] = points
        a["auto_completed"] = True
        core.bump_version(a)
        core.touch(a)
        srv = db.db.servers.get(a["server_id"])
        if srv is not None:
            srv["lifetime_points"] = srv["lifetime_points"] + points
            if not core.showtime_has_ejection_refund(st):
                grade = a.get("rating_grade")
                if grade:
                    srv["ratings"].append({"assignment_id": a["id"], "rating_grade": grade})
            core.bump_version(srv)
            core.refresh_server_status(srv)
            core.refresh_server(srv)


def _refresh_showtime_servers(st):
    for a in db.db.sorted_rows("section_assignments"):
        if a["showtime_id"] != st["id"]:
            continue
        srv = db.db.servers.get(a["server_id"])
        if srv is not None:
            core.refresh_server(srv)


def reopen_service(st):
    if st["status"] != "COMPLETED":
        raise ApiError(errors.ERR_SHOWTIME_NOT_COMPLETED)
    if not db.db.now < st["start_at_utc"] + timedelta(minutes=st["runtime_minutes"]):
        raise ApiError(errors.ERR_REOPEN_WINDOW_CLOSED)
    aud = core.auditorium(st["auditorium_id"])
    if aud["status"] != "LIVE":
        raise ApiError(errors.ERR_AUDITORIUM_NOT_SERVING)

    st["status"] = "SERVICE"
    st["mode"] = "DINING_OPEN"
    core.recompute_service_mode(st)
    st["service_mode"] = "IN_KITCHEN"
    core.touch(st)
    core.bump_version(st)

    for a in db.db.sorted_rows("section_assignments"):
        if a["showtime_id"] != st["id"]:
            continue
        if a["status"] != "COMPLETED" or not a.get("auto_completed"):
            continue
        prior = a["assignment_points"]
        a["status"] = "ACTIVE"
        a["assignment_points"] = 0
        a["auto_completed"] = False
        core.bump_version(a)
        core.touch(a)
        srv = db.db.servers.get(a["server_id"])
        if srv is not None:
            srv["lifetime_points"] = srv["lifetime_points"] - prior
            core.bump_version(srv)
            core.refresh_server_status(srv)
            core.refresh_server(srv)

    core.reconcile_auditorium(aud)
    core.touch(aud)
    return st


def cancel(st):
    if st["status"] == "SCHEDULED":
        st["status"] = "CANCELLED"
        st["mode"] = "DINING_CLOSED"
        core.touch(st)
        core.bump_version(st)
        _recompute_event_cancellation(st)
    elif st["status"] == "DINING_OPEN":
        st["status"] = "CANCELLED"
        st["mode"] = "DINING_CLOSED"
        core.touch(st)
        core.bump_version(st)
        for sl in db.db.sorted_rows("order_slips"):
            if sl["showtime_id"] != st["id"]:
                continue
            if sl["status"] in ("DELIVERED", "CANCELLED", "VOIDED"):
                continue
            sl["status"] = "CANCELLED"
            core.touch(sl)
            core.bump_version(sl)
            tab = db.db.checks.get(sl["id"])
            if tab is not None:
                tab["original_cents"] = 0
                core.touch(tab)
        for a in db.db.sorted_rows("section_assignments"):
            if a["showtime_id"] != st["id"] or a["status"] != "REASSIGNMENT_PENDING":
                continue
            a["status"] = "CANCELLED"
            a["assignment_points"] = 0
            core.bump_version(a)
            core.touch(a)
        for a in db.db.sorted_rows("section_assignments"):
            if a["showtime_id"] != st["id"]:
                continue
            if a["status"] not in ("DRAFT", "ACTIVE"):
                continue
            a["status"] = "CANCELLED"
            a["assignment_points"] = 0
            core.bump_version(a)
            core.touch(a)
            srv = db.db.servers.get(a["server_id"])
            if srv is not None:
                core.refresh_server_status(srv)
                core.refresh_server(srv)
    elif st["status"] == "SERVICE":
        _cancel_in_flight(st, refund_open_tabs=False)
    elif st["status"] == "RUNNING":
        _cancel_in_flight(st, refund_open_tabs=True)
    else:
        raise ApiError(errors.ERR_SHOWTIME_NOT_RUNNING)

    aud = core.auditorium(st["auditorium_id"])
    core.reconcile_auditorium(aud)
    core.touch(aud)
    return st


def _cancel_in_flight(st, refund_open_tabs):
    st["status"] = "CANCELLED"
    st["mode"] = "DINING_CLOSED"
    core.touch(st)
    core.bump_version(st)

    for ticket in db.db.sorted_rows("kitchen_tickets"):
        if ticket["showtime_id"] != st["id"]:
            continue
        if ticket["status"] in ("DELIVERED", "VOIDED"):
            continue
        ticket["status"] = "VOIDED"
        core.touch(ticket)
        core.bump_version(ticket)

    for sl in db.db.sorted_rows("order_slips"):
        if sl["showtime_id"] != st["id"]:
            continue
        if sl["status"] in ("DELIVERED", "CANCELLED", "VOIDED"):
            continue
        sl["status"] = "CANCELLED"
        core.touch(sl)
        core.bump_version(sl)

    # The refunds land before the section points are scored: the RUNNING-cancel
    # cascade books every open tab as a service-compensation failure, and the
    # scoring chain in 3.9 multiplies an assignment whose showtime booked one.
    if refund_open_tabs:
        for tab in db.db.sorted_rows("checks"):
            slip = db.db.order_slips.get(tab["order_slip_id"])
            if slip is None or slip["showtime_id"] != st["id"]:
                continue
            if tab["status"] != "OPEN":
                continue
            tab["status"] = "REFUNDED"
            tab["refunded_cents"] = tab["original_cents"]
            tab["reason_code"] = "SERVICE_COMP_FAILURE"
            core.touch(tab)

    for a in db.db.sorted_rows("section_assignments"):
        if a["showtime_id"] != st["id"]:
            continue
        if a["status"] in ("COMPLETED", "CANCELLED"):
            continue
        a["status"] = "CANCELLED"
        a["assignment_points"] = core.assignment_points(a, cancel=True)
        core.bump_version(a)
        core.touch(a)
        srv = db.db.servers.get(a["server_id"])
        if srv is not None:
            core.refresh_server_status(srv)
            core.refresh_server(srv)


def _recompute_event_cancellation(st):
    event = linked_event(st)
    if event is None:
        return
    if event["status"] not in ("DRAFT", "ACTIVATED"):
        return
    remaining = [s for s in db.db.sorted_rows("showtimes")
                 if s["auditorium_id"] == event["auditorium_id"]
                 and s["content_type"] == "SPECIAL_EVENT" and s["status"] == "SCHEDULED"]
    if not remaining and event["pre_show_content_status"] == "PRE_SHOW_APPROVED":
        event["status"] = "COMPLETED"
        core.bump_version(event)
    core.touch(event)


def _recompute_event_completion(st):
    for event in db.db.sorted_rows("programming_events"):
        if event["status"] != "ACTIVATED":
            continue
        if event["auditorium_id"] != st["auditorium_id"]:
            continue
        linked = [s for s in db.db.sorted_rows("showtimes")
                  if s["auditorium_id"] == event["auditorium_id"]
                  and s["content_type"] == "SPECIAL_EVENT"]
        if not linked:
            continue
        if any(s["status"] in ("SCHEDULED", "DINING_OPEN", "SERVICE", "RUNNING")
               for s in linked):
            continue
        event["status"] = "COMPLETED"
        core.bump_version(event)
        core.touch(event)
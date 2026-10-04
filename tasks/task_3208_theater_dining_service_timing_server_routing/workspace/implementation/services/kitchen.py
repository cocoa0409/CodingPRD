"""Kitchen tickets: overflow acknowledgement, ID verification, refresh, void."""

import db
import errors
from errors import ApiError
from services import core
from services import showtime as showtime_service


def ack_overflow(ticket, data):
    reason = data.get("overflow_reason")
    ticket["overflow_reason"] = "" if reason is None else str(reason)
    st = core.showtime(ticket["showtime_id"])
    core.resequence(st)
    core.touch(ticket)
    core.bump_version(ticket)
    return ticket


def verify_id(ticket, data):
    result = data.get("id_result")
    slip = core.order_slip(ticket["order_slip_id"])
    passed = str(result).upper() in ("PASS", "PASSED", "VERIFIED", "TRUE", "OK") \
        if result is not None else False
    if passed:
        slip["id_check_status"] = "VERIFIED"
    else:
        slip["id_check_status"] = "REFUSED"
        slip["status"] = "VOIDED"
        ticket["status"] = "VOIDED"
        ticket["void_reason"] = "ID_CHECK_REFUSED"
        tab = db.db.checks.get(slip["id"])
        if tab is not None:
            tab["original_cents"] = 0
            core.touch(tab)
        core.touch(ticket)
    core.bump_version(slip)
    core.touch(slip)
    srv = db.db.servers.get(_owner(slip))
    if srv is not None:
        core.refresh_server(srv)
    return ticket


def _owner(slip):
    assignment = db.db.section_assignments.get(slip["section_assignment_id"])
    return assignment["server_id"] if assignment else None


def refresh(ticket):
    st = core.showtime(ticket["showtime_id"])
    core.resequence(st)
    core.touch(ticket)
    core.bump_version(ticket)
    return ticket


def void(ticket, data):
    st = core.showtime(ticket["showtime_id"])
    ticket["status"] = "VOIDED"
    reason = data.get("reason_code")
    if reason is not None:
        ticket["void_reason"] = str(reason)
    core.touch(ticket)
    core.bump_version(ticket)

    slip = db.db.order_slips.get(ticket["order_slip_id"])
    if slip is not None and slip["status"] in ("PLACED", "ACCEPTED", "PREPARING"):
        slip["status"] = "CANCELLED"
        core.touch(slip)
        core.bump_version(slip)
    core.resequence(st)
    return ticket
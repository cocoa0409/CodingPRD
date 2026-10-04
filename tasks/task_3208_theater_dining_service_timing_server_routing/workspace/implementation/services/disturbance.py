"""Disturbance reports, the strike ladder, and ejection compensation."""

from datetime import timedelta

import db
import errors
from errors import ApiError
from services import core

STAGES = ("WARNING", "FINAL_WARNING", "EJECTION")


def create(principal, data):
    slip = core.order_slip(data.get("order_slip_id"))
    kind = data.get("kind")
    if kind not in ("NO_TALKING", "NO_TEXTING"):
        kind = "NO_TALKING"
    row = {
        "order_slip_id": slip["id"],
        "kind": kind,
        "stage": "WARNING",
        "prior_stage": None,
        "stage_version": 1,
        "occurred_at_utc": db.db.now,
        "ejected_occupant_id": principal.user_id,
    }
    db.db.register("disturbance_events", row)
    _refresh_owner(slip)
    return row


def amend(principal, event, data):
    requested = data.get("stage")
    if requested not in STAGES:
        raise ApiError(errors.ERR_DISTURBANCE_NOT_AMENDABLE)
    if core.STAGE_ORDER.get(event["stage"], 0) >= core.STAGE_ORDER.get(requested, 0):
        raise ApiError(errors.ERR_DISTURBANCE_NOT_AMENDABLE)

    event["prior_stage"] = data.get("prior_stage")
    event["stage"] = requested
    event["stage_version"] = core.STAGE_ORDER.get(requested, 1) + 1
    event["occurred_at_utc"] = db.db.now
    slip = db.db.order_slips.get(event["order_slip_id"])
    if slip is not None:
        _refresh_owner(slip)
    _refresh_strike_ladder(event)
    return event


def _refresh_strike_ladder(event):
    """Re-derive this report's own stage against the ladder's window.

    PRD §3.10: "the window is an instant window exactly one day long", and a
    live stage is one "whose `occurred_at_utc` falls inside the window". Staging a
    report at or before the window's start puts its stage outside it — after a
    day rollover the constant-length window no longer reaches the preceding day's
    report, "so an occupant who had been carrying `FINAL_WARNING` drops back to
    `WARNING`". Amending re-stamps `occurred_at_utc`, so the same evaluation runs
    on that write.
    """
    window_start = db.db.now - timedelta(days=core.STRIKE_WINDOW_DAYS)
    if event["kind"] != "NO_TALKING" or event["stage"] == "EJECTION":
        return
    if event["occurred_at_utc"] <= window_start:
        event["stage"] = "WARNING"


def approve_ejection(event):
    slip = core.order_slip(event["order_slip_id"])

    occupant = event.get("ejected_occupant_id")
    if occupant is None:
        raise ApiError(errors.ERR_EJECTED_OCCUPANT_NOT_ON_SLIP)
    if _assigned_server_id(slip) != occupant:
        raise ApiError(errors.ERR_EJECTED_OCCUPANT_NOT_ON_SLIP)

    event["stage"] = "EJECTION"
    event["stage_version"] = core.STAGE_ORDER["EJECTION"] + 1
    event["occurred_at_utc"] = db.db.now

    tab = db.db.checks.get(slip["id"])
    if tab is None:
        raise ApiError(errors.ERR_CHECK_NOT_FOUND)
    if tab["status"] == "REFUNDED":
        raise ApiError(errors.ERR_REFUND_EXCEEDS_ORIGINAL)
    tab["refunded_cents"] = tab["original_cents"]
    tab["status"] = "REFUNDED"
    if event["kind"] == "NO_TALKING":
        tab["reason_code"] = "EJECTION_NO_TALKING"
    else:
        tab["reason_code"] = "EJECTION_NO_TEXTING"
    core.touch(tab)
    core.bump_version(slip)
    core.touch(slip)

    # The ejected seat leaves the kitchen queue and stops consuming line capacity.
    for ticket in db.db.sorted_rows("kitchen_tickets"):
        if ticket["order_slip_id"] != slip["id"]:
            continue
        if ticket["status"] in ("DELIVERED", "VOIDED"):
            continue
        ticket["status"] = "VOIDED"
        ticket["void_reason"] = "EJECTION"
        core.touch(ticket)
        core.bump_version(ticket)
    st = db.db.showtimes.get(slip["showtime_id"])
    if st is not None:
        core.resequence(st)

    _refresh_owner(slip)
    return event


def _assigned_server_id(slip):
    assignment = db.db.section_assignments.get(slip["section_assignment_id"])
    return assignment["server_id"] if assignment else None


def _refresh_owner(slip):
    server_id = _assigned_server_id(slip)
    srv = db.db.servers.get(server_id) if server_id else None
    if srv is not None:
        core.refresh_server(srv)


def proposed_stage(occupant_id):
    """The stage the strike ladder proposes for an occupant right now."""
    window_start = db.db.now - timedelta(days=core.STRIKE_WINDOW_DAYS)
    live = set()
    for event in db.db.sorted_rows("disturbance_events"):
        if event["kind"] != "NO_TALKING":
            continue
        if event.get("ejected_occupant_id") != occupant_id:
            continue
        if event["occurred_at_utc"] < window_start or event["occurred_at_utc"] > db.db.now:
            continue
        live.add(event["stage"])
    count = len(live)
    if count == 0:
        return "WARNING"
    if count == 1:
        return "FINAL_WARNING"
    return "EJECTION"


def stage_for_strike_count(count):
    if count == 0:
        return "WARNING"
    if count == 1:
        return "FINAL_WARNING"
    return "EJECTION"


def expire_stages():
    """Expire a frozen stage whose window no longer reaches its report.

    The ladder's window is an instant window exactly one service day long, so
    once the clock rolls past that span the window no longer reaches the
    preceding day's report and an occupant who had been carrying FINAL_WARNING
    drops back to WARNING on the next read. This is evaluation, not a batch job.
    """
    window_start = db.db.now - timedelta(days=core.STRIKE_WINDOW_DAYS)
    for event in db.db.sorted_rows("disturbance_events"):
        if event["kind"] != "NO_TALKING":
            continue
        if event["stage"] == "EJECTION":
            continue
        if event["occurred_at_utc"] <= window_start:
            event["stage"] = "WARNING"
    return None
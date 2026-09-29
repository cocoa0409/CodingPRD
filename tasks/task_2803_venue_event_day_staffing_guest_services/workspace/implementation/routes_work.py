"""Bidding, direct assignment, attendance and the backfill pool."""

from datetime import timedelta

from flask import Blueprint

import calc
import services as svc
from core import (
    ALL_ROLES,
    all_rows,
    auth,
    body_dict,
    conflict,
    db,
    err,
    invalid,
    lookup,
    minutes_between,
    new_record,
    not_owner,
    now,
    pagination,
    q_enum,
    q_str,
    req_enum,
    req_str,
    respond,
    respond_list,
    role_not_permitted,
    touch,
    update,
    MISSING,
)
from serialize import (
    backfill_request_json,
    shift_bid_json,
    staff_assignment_json,
)

bp = Blueprint("work", __name__)

BID_STATUSES = ("SUBMITTED", "WAITLISTED", "AWARDED", "DECLINED_BY_SYSTEM", "WITHDRAWN")
ATTENDANCE_STATUSES = (
    "SCHEDULED",
    "CHECKED_IN",
    "COMPLETED",
    "NO_SHOW",
    "RELEASED",
    "CANCELLED",
)
PAYOUT_STATUSES = ("PENDING", "ACCRUED", "GRATUITY_ALLOCATED", "PAID", "VOIDED")
SOURCES = ("BID_AWARD", "MANUAL", "BACKFILL")
BACKFILL_STATUSES = ("OPEN", "FILLED", "UNFILLABLE", "CANCELLED")
ACTIONS = ("CHECK_IN", "CHECK_OUT", "NO_SHOW", "RELEASE")
TERMINAL_ATTENDANCE = ("COMPLETED", "NO_SHOW", "RELEASED", "CANCELLED")

READ_ROLES = (
    "GuestExperienceDirector",
    "StaffingCoordinator",
    "GuestServicesSupervisor",
)


def _eligibility_ladder(slot, member, position_type):
    """§3.5, in the pinned rung order: 11, 12, 13, 14, 17."""
    if member["status"] != "ACTIVE":
        raise conflict(
            "ERR_STAFF_MEMBER_NOT_ACTIVE",
            "The worker stands in %s, not ACTIVE." % member["status"],
        )
    missing = svc.missing_certs(member["id"], position_type)
    if missing:
        raise conflict(
            "ERR_CERTIFICATION_MISSING",
            "The worker holds no VALID %s credential." % ", ".join(missing),
        )
    if svc.has_live_assignment_on_slot(member["id"], slot):
        raise conflict(
            "ERR_DUPLICATE_ASSIGNMENT",
            "The worker already holds a live assignment on this shift block.",
        )
    if svc.violates_rest_buffer(member["id"], slot, include_same_slot=False):
        raise conflict(
            "ERR_SHIFT_REST_CONFLICT",
            "The shift leaves less than %d minutes of rest."
            % calc.REST_BUFFER_MINUTES,
        )
    if not svc.has_capacity(slot):
        raise conflict(
            "ERR_SLOT_CAPACITY_FULL",
            "The shift block has already reached its required headcount.",
        )


# ---------------------------------------------------------------------------
# shift bids
# ---------------------------------------------------------------------------

@bp.post("/shift-bids")
def create_shift_bid():
    user_id, role = auth("StaffMember", "StaffingCoordinator")
    body = body_dict()
    member_id = req_str(body, "staff_member_id")
    slot_id = req_str(body, "position_slot_id")
    member = lookup("staff_members", member_id)
    slot = lookup("position_slots", slot_id)
    if role == "StaffMember" and user_id != member["id"]:
        raise not_owner("A worker may only file a bid for their own record.")
    event = svc.event_of_slot(slot)
    if event["status"] not in ("PLANNED", "IN_PROGRESS"):
        raise conflict(
            "ERR_EVENT_STATE_INVALID",
            "Bidding requires the event to stand in PLANNED or IN_PROGRESS.",
        )
    for existing in svc.bids_of_slot(slot):
        if existing["staff_member_id"] == member["id"] and existing["status"] in svc.LIVE_BID:
            raise conflict(
                "ERR_DUPLICATE_BID",
                "The worker already holds a live bid on this shift block.",
            )
    row = new_record(
        "shift_bids",
        {
            "staff_member_id": member["id"],
            "position_slot_id": slot["id"],
            "submitted_at": now(),
            "rank_score": None,
            "decision_reason": None,
            "status": "SUBMITTED",
        },
    )
    return respond(shift_bid_json(row), 201)


@bp.get("/shift-bids/<bid_id>")
def read_shift_bid(bid_id):
    auth(*ALL_ROLES)
    return respond(shift_bid_json(lookup("shift_bids", bid_id)))


@bp.get("/shift-bids")
def list_shift_bids():
    auth(*ALL_ROLES)
    member_id = q_str("staff_member_id")
    slot_id = q_str("position_slot_id")
    status = q_enum("status", BID_STATUSES)
    limit, offset = pagination()
    rows = all_rows("shift_bids")
    if member_id is not None:
        rows = [r for r in rows if r["staff_member_id"] == member_id]
    if slot_id is not None:
        rows = [r for r in rows if r["position_slot_id"] == slot_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    window = rows[offset:offset + limit]
    return respond_list(
        [shift_bid_json(r) for r in window], limit, offset, len(rows)
    )


@bp.post("/shift-bids/<bid_id>/award")
def award_shift_bid(bid_id):
    auth("StaffingCoordinator")
    bid = lookup("shift_bids", bid_id)
    if bid["status"] != "SUBMITTED":
        raise conflict(
            "ERR_BID_STATE_INVALID",
            "Only a SUBMITTED bid can be awarded manually (this one is %s)."
            % bid["status"],
        )
    slot = db.position_slots[bid["position_slot_id"]]
    if slot["status"] == "CLOSED":
        raise conflict(
            "ERR_SLOT_STATE_INVALID", "The shift block is CLOSED."
        )
    plan = svc.plan_of_slot(slot)
    if plan["status"] != "ACTIVE":
        raise conflict(
            "ERR_PLAN_STATE_INVALID",
            "A manual award requires the owning plan to stand in ACTIVE.",
        )
    member = db.staff_members[bid["staff_member_id"]]
    position_type = svc.position_type_of_slot(slot)
    _eligibility_ladder(slot, member, position_type)
    svc.create_assignment(slot, member, "BID_AWARD", shift_bid_id=bid["id"])
    update(bid, status="AWARDED", decision_reason="MANUAL_AWARD")
    return respond(shift_bid_json(bid))


@bp.post("/shift-bids/<bid_id>/withdraw")
def withdraw_shift_bid(bid_id):
    user_id, _ = auth("StaffMember")
    bid = lookup("shift_bids", bid_id)
    if user_id != bid["staff_member_id"]:
        raise not_owner("A worker may only withdraw their own bid.")
    if bid["status"] not in svc.LIVE_BID:
        raise conflict(
            "ERR_BID_STATE_INVALID",
            "A %s bid can no longer be withdrawn." % bid["status"],
        )
    update(bid, status="WITHDRAWN", decision_reason="WITHDRAWN_BY_MEMBER")
    return respond(shift_bid_json(bid))


# ---------------------------------------------------------------------------
# staff assignments
# ---------------------------------------------------------------------------

@bp.post("/staff-assignments")
def create_staff_assignment():
    auth("StaffingCoordinator")
    body = body_dict()
    slot_id = req_str(body, "position_slot_id")
    member_id = req_str(body, "staff_member_id")
    slot = lookup("position_slots", slot_id)
    member = lookup("staff_members", member_id)
    event = svc.event_of_slot(slot)
    if event["status"] not in ("PLANNED", "IN_PROGRESS"):
        raise conflict(
            "ERR_EVENT_STATE_INVALID",
            "A direct assignment requires the event in PLANNED or IN_PROGRESS.",
        )
    plan = svc.plan_of_slot(slot)
    if plan["status"] not in ("ACTIVE", "LOCKED"):
        raise conflict(
            "ERR_PLAN_STATE_INVALID",
            "A direct assignment requires the plan in ACTIVE or LOCKED.",
        )
    position_type = svc.position_type_of_slot(slot)
    _eligibility_ladder(slot, member, position_type)
    row = svc.create_assignment(slot, member, "MANUAL")
    return respond(staff_assignment_json(row), 201)


@bp.get("/staff-assignments/<assignment_id>")
def read_staff_assignment(assignment_id):
    auth(*ALL_ROLES)
    return respond(staff_assignment_json(lookup("staff_assignments", assignment_id)))


@bp.get("/staff-assignments")
def list_staff_assignments():
    auth(*ALL_ROLES)
    slot_id = q_str("position_slot_id")
    member_id = q_str("staff_member_id")
    bid_id = q_str("shift_bid_id")
    attendance_status = q_enum("attendance_status", ATTENDANCE_STATUSES)
    payout_status = q_enum("payout_status", PAYOUT_STATUSES)
    source = q_enum("source", SOURCES)
    limit, offset = pagination()
    rows = all_rows("staff_assignments")
    if slot_id is not None:
        rows = [r for r in rows if r["position_slot_id"] == slot_id]
    if member_id is not None:
        rows = [r for r in rows if r["staff_member_id"] == member_id]
    if bid_id is not None:
        rows = [r for r in rows if r["shift_bid_id"] == bid_id]
    if attendance_status is not None:
        rows = [r for r in rows if r["attendance_status"] == attendance_status]
    if payout_status is not None:
        rows = [r for r in rows if r["payout_status"] == payout_status]
    if source is not None:
        rows = [r for r in rows if r["source"] == source]
    window = rows[offset:offset + limit]
    return respond_list(
        [staff_assignment_json(r) for r in window], limit, offset, len(rows)
    )


@bp.post("/staff-assignments/<assignment_id>/attendance")
def mark_attendance(assignment_id):
    user_id, role = auth("StaffingCoordinator", "StaffMember")
    body = body_dict()
    action = req_enum(body, "action", ACTIONS)
    if role == "StaffMember" and action in ("NO_SHOW", "RELEASE"):
        raise role_not_permitted(
            "%s is reserved for a StaffingCoordinator." % action
        )
    assignment = lookup("staff_assignments", assignment_id)
    if role == "StaffMember" and user_id != assignment["staff_member_id"]:
        raise not_owner("A worker may only mark their own attendance.")

    if assignment["attendance_status"] in TERMINAL_ATTENDANCE:
        raise conflict(
            "ERR_ASSIGNMENT_STATE_INVALID",
            "The assignment already stands in %s." % assignment["attendance_status"],
        )
    if action == "CHECK_OUT" and assignment["attendance_status"] != "CHECKED_IN":
        raise conflict(
            "ERR_ASSIGNMENT_STATE_INVALID", "A check-out requires a checked-in row."
        )
    if action != "CHECK_OUT" and assignment["attendance_status"] != "SCHEDULED":
        raise conflict(
            "ERR_ASSIGNMENT_STATE_INVALID",
            "%s is not declared from %s."
            % (action, assignment["attendance_status"]),
        )

    slot = svc.slot_of_assignment(assignment)
    member = svc.member_of_assignment(assignment)
    event = svc.event_of_slot(slot)

    if action in ("CHECK_IN", "NO_SHOW") and event["status"] != "IN_PROGRESS":
        raise conflict(
            "ERR_EVENT_STATE_INVALID",
            "%s requires the event to stand exactly in IN_PROGRESS." % action,
        )
    if action in ("CHECK_IN", "RELEASE") and slot["status"] == "CLOSED":
        raise conflict("ERR_SLOT_STATE_INVALID", "The shift block is CLOSED.")

    if action == "CHECK_IN":
        stamp = now()
        grace = slot["shift_start"] + timedelta(minutes=calc.LATE_GRACE_MINUTES)
        update(
            assignment,
            attendance_status="CHECKED_IN",
            check_in_at=stamp,
            late_check_in=stamp > grace,
        )
    elif action == "CHECK_OUT":
        stamp = now()
        worked = minutes_between(assignment["check_in_at"], stamp)
        base = calc.worked_pay(worked, member["hourly_rate_cents"])
        update(
            assignment,
            attendance_status="COMPLETED",
            payout_status="ACCRUED",
            checked_out_at=stamp,
            worked_minutes=worked,
            base_pay_cents=base,
            total_payout_cents=base + assignment["gratuity_cents"],
        )
        svc.settle_reliability(
            member,
            {
                "completed_assignment_count": member["completed_assignment_count"] + 1
            },
            triggering_assignment=assignment,
        )
    elif action == "NO_SHOW":
        update(
            assignment,
            attendance_status="NO_SHOW",
            payout_status="VOIDED",
            total_payout_cents=0,
        )
        svc.recount_slot(slot)
        svc.open_backfill_request(slot, assignment)
        svc.settle_reliability(
            member,
            {"no_show_strikes": member["no_show_strikes"] + 1},
            triggering_assignment=assignment,
        )
    else:
        update(
            assignment,
            attendance_status="RELEASED",
            payout_status="VOIDED",
            total_payout_cents=0,
        )
        svc.recount_slot(slot)
        if assignment["source"] == "BACKFILL":
            request_row = svc.backfill_of_filled_assignment(assignment)
            if request_row is not None and request_row["status"] == "FILLED":
                update(
                    request_row,
                    status="OPEN",
                    selected_staff_member_id=None,
                    filled_assignment_id=None,
                )
    return respond(staff_assignment_json(assignment))


# ---------------------------------------------------------------------------
# backfill requests (never created by a client)
# ---------------------------------------------------------------------------

@bp.get("/backfill-requests/<request_id>")
def read_backfill_request(request_id):
    auth(*READ_ROLES)
    return respond(backfill_request_json(lookup("backfill_requests", request_id)))


@bp.get("/backfill-requests")
def list_backfill_requests():
    auth(*READ_ROLES)
    slot_id = q_str("position_slot_id")
    triggering_id = q_str("triggering_assignment_id")
    filled_id = q_str("filled_assignment_id")
    member_id = q_str("selected_staff_member_id")
    status = q_enum("status", BACKFILL_STATUSES)
    limit, offset = pagination()
    rows = all_rows("backfill_requests")
    if slot_id is not None:
        rows = [r for r in rows if r["position_slot_id"] == slot_id]
    if triggering_id is not None:
        rows = [r for r in rows if r["triggering_assignment_id"] == triggering_id]
    if filled_id is not None:
        rows = [r for r in rows if r["filled_assignment_id"] == filled_id]
    if member_id is not None:
        rows = [r for r in rows if r["selected_staff_member_id"] == member_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    window = rows[offset:offset + limit]
    return respond_list(
        [backfill_request_json(r) for r in window], limit, offset, len(rows)
    )


@bp.post("/backfill-requests/<request_id>/auto-fill")
def auto_fill_backfill_request(request_id):
    auth("StaffingCoordinator")
    row = lookup("backfill_requests", request_id)
    if row["status"] != "OPEN":
        raise conflict(
            "ERR_BACKFILL_NOT_OPEN",
            "A %s backfill request accepts no further attempt." % row["status"],
        )
    slot = db.position_slots[row["position_slot_id"]]
    if slot["status"] == "CLOSED":
        raise conflict("ERR_SLOT_STATE_INVALID", "The shift block is CLOSED.")
    plan = svc.plan_of_slot(slot)
    if plan["status"] not in ("ACTIVE", "LOCKED"):
        raise conflict(
            "ERR_PLAN_STATE_INVALID",
            "Auto-fill requires the owning plan in ACTIVE or LOCKED.",
        )
    event = svc.event_of_plan(plan)
    if event["status"] not in ("PLANNED", "IN_PROGRESS"):
        raise conflict(
            "ERR_EVENT_STATE_INVALID",
            "Auto-fill requires the event in PLANNED or IN_PROGRESS.",
        )

    position_type = svc.position_type_of_slot(slot)
    triggering = db.staff_assignments.get(row["triggering_assignment_id"])
    excluded = triggering["staff_member_id"] if triggering else None
    candidates = svc.backfill_candidates(slot, position_type, excluded)
    attempts = row["attempt_count"] + 1
    if not candidates:
        update(row, attempt_count=attempts, status="UNFILLABLE")
        if slot["status"] in ("OPEN", "PARTIALLY_FILLED"):
            update(slot, status="UNDERSTAFFED_ESCALATED")
        return respond(backfill_request_json(row))

    winner = candidates[0]
    assignment = svc.create_assignment(slot, winner, "BACKFILL")
    update(
        row,
        attempt_count=attempts,
        status="FILLED",
        selected_staff_member_id=winner["id"],
        filled_assignment_id=assignment["id"],
    )
    return respond(backfill_request_json(row))


@bp.post("/backfill-requests/<request_id>/cancel")
def cancel_backfill_request(request_id):
    auth("StaffingCoordinator")
    body = body_dict()
    reason = req_str(body, "cancel_reason")
    row = lookup("backfill_requests", request_id)
    if row["status"] != "OPEN":
        raise conflict(
            "ERR_BACKFILL_NOT_OPEN",
            "Only an OPEN backfill request can be abandoned.",
        )
    update(row, status="CANCELLED", cancel_reason=reason)
    return respond(backfill_request_json(row))

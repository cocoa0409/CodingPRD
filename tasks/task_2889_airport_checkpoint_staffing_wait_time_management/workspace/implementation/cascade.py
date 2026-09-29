"""Transitive cascades and shared side-effect helpers (PRD section 2.10)."""

from flask import g

import consts
import derive
import store
from util import whole_minutes


# ---------------------------------------------------------------------------
# version bumping (at most one bump per parent per request)
# ---------------------------------------------------------------------------
def _bumped(kind):
    seen = getattr(g, kind, None)
    if seen is None:
        seen = set()
        setattr(g, kind, seen)
    return seen


def bump_checkpoint(checkpoint):
    if checkpoint is None:
        return
    seen = _bumped("_bumped_checkpoints")
    if checkpoint["id"] in seen:
        return
    seen.add(checkpoint["id"])
    store.touch(checkpoint)


def bump_officer(officer):
    if officer is None:
        return
    store.touch(officer)


def checkpoint_of_lane(lane):
    return store.get("checkpoints", lane["checkpoint_id"])


def checkpoint_of_plan(plan):
    return store.get("checkpoints", plan["checkpoint_id"])


# ---------------------------------------------------------------------------
# posture settlement
# ---------------------------------------------------------------------------
def latest_observation(checkpoint_id, lane_type):
    samples = [
        o
        for o in store.rows("wait_time_observations")
        if o["checkpoint_id"] == checkpoint_id and o["lane_type"] == lane_type
    ]
    if not samples:
        return None
    return sorted(samples, key=lambda o: (o["observed_at_utc"], o["_seq"]))[-1]


def _maybe_raise_posture_ticket(checkpoint):
    latest = latest_observation(checkpoint["id"], "STANDARD")
    if latest is None or latest["published_wait_minutes_snapshot"] is None:
        return
    if latest["published_wait_minutes_snapshot"] < checkpoint["wait_threshold_minutes_standard"]:
        return
    for ticket in store.rows("escalation_tickets"):
        if (
            ticket["checkpoint_id"] == checkpoint["id"]
            and ticket["trigger_reason"] == "POSTURE_DEGRADATION"
            and ticket["state"] in ("RAISED", "ACKNOWLEDGED")
        ):
            return
    create_ticket(
        checkpoint,
        "POSTURE_DEGRADATION",
        "ALL",
        latest["published_wait_minutes_snapshot"],
    )


def create_ticket(checkpoint, trigger_reason, lane_type_scope, snapshot):
    row = store.base()
    row.update(
        {
            "checkpoint_id": checkpoint["id"],
            "resolved_lane_id": None,
            "acknowledged_by_officer_id": None,
            "trigger_reason": trigger_reason,
            "lane_type_scope": lane_type_scope,
            "state": "RAISED",
            "published_wait_minutes_at_raise": snapshot,
            "diverted_pax_count": None,
            "resolution_note": None,
            "raised_at_utc": store.now(),
            "acknowledged_at_utc": None,
            "resolved_at_utc": None,
        }
    )
    return store.add("escalation_tickets", row)


def settle_posture(checkpoint, before):
    after = derive.posture(checkpoint)
    if before == "NORMAL" and after == "ELEVATED":
        _maybe_raise_posture_ticket(checkpoint)
        after = derive.posture(checkpoint)
    checkpoint["posture"] = after
    derive.refresh_checkpoint(checkpoint)
    return after


# ---------------------------------------------------------------------------
# assignment side effects
# ---------------------------------------------------------------------------
def lane_assignments(lane_id, states):
    return [
        a
        for a in store.rows("lane_assignments")
        if a["lane_id"] == lane_id and a["assignment_state"] in states
    ]


def plan_assignments(plan_id, states):
    return [
        a
        for a in store.rows("lane_assignments")
        if a["staffing_plan_id"] == plan_id and a["assignment_state"] in states
    ]


def end_break(assignment):
    if assignment["break_state"] != "ON_BREAK":
        return
    started = assignment["break_started_at_utc"]
    now = store.now()
    if started is not None:
        assignment["break_minutes_taken"] += max(0, whole_minutes(started, now))
    assignment["break_ended_at_utc"] = now
    assignment["break_baseline_utc"] = now
    assignment["break_state"] = "COMPLETED"
    officer = store.get("officers", assignment["officer_id"])
    if officer is not None and officer["duty_status"] == "ON_BREAK":
        officer["duty_status"] = "ON_DUTY"
        bump_officer(officer)


def release_assignment(assignment):
    end_break(assignment)
    assignment["assignment_state"] = "RELEASED"
    assignment["released_at_utc"] = store.now()
    store.touch(assignment)


def cancel_assignment(assignment):
    assignment["assignment_state"] = "CANCELLED"
    store.touch(assignment)


def settle_officer(officer_id, retire=False):
    officer = store.get("officers", officer_id)
    if officer is None:
        return
    derive.refresh_officer(officer)
    if (
        retire
        and officer["duty_status"] == "ON_DUTY"
        and officer["committed_duty_minutes"] == 0
    ):
        officer["duty_status"] = "OFF_DUTY"
        bump_officer(officer)


# ---------------------------------------------------------------------------
# lane transitions driven by the system
# ---------------------------------------------------------------------------
def pause_lane(lane, reason_code):
    lane["lane_state"] = "PAUSED"
    lane["paused_reason_code"] = reason_code
    store.touch(lane)
    touched = set()
    for assignment in lane_assignments(lane["id"], ("CHECKED_IN",)):
        assignment["assignment_state"] = "REASSIGN_PENDING"
        store.touch(assignment)
        touched.add(assignment["officer_id"])
    for officer_id in touched:
        settle_officer(officer_id)


def close_lane(lane, reason_code=None):
    was_open = lane["lane_state"] == "OPEN"
    lane["lane_state"] = "CLOSED"
    if reason_code is not None:
        lane["paused_reason_code"] = reason_code
    store.touch(lane)
    states = ("CHECKED_IN", "REASSIGN_PENDING") if was_open else ("REASSIGN_PENDING",)
    touched = set()
    for assignment in lane_assignments(lane["id"], states):
        release_assignment(assignment)
        touched.add(assignment["officer_id"])
    for officer_id in touched:
        settle_officer(officer_id, retire=True)


def reopen_lane(lane):
    lane["lane_state"] = "OPEN"
    lane["opened_at_utc"] = store.now()
    lane["paused_reason_code"] = None
    store.touch(lane)
    for assignment in lane_assignments(lane["id"], ("REASSIGN_PENDING",)):
        plan = store.get("staffing_plans", assignment["staffing_plan_id"])
        if plan is not None and plan["state"] == "ACTIVATED":
            assignment["assignment_state"] = "CHECKED_IN"
            assignment["break_baseline_utc"] = store.now()
            store.touch(assignment)
            settle_officer(assignment["officer_id"])


def suspend_checkpoint(checkpoint):
    for lane in derive.checkpoint_lanes(checkpoint["id"]):
        if lane["lane_state"] == "OPEN":
            pause_lane(lane, "SECURITY_INCIDENT")


# ---------------------------------------------------------------------------
# equipment fault cascade (depth 4)
# ---------------------------------------------------------------------------
def equipment_cascade(lane):
    """Links 2-4: pause an OPEN lane whose equipment went OUT_OF_SERVICE."""
    if lane["lane_state"] != "OPEN":
        return False
    if derive.lane_equipment_state(lane) != "OUT_OF_SERVICE":
        return False
    pause_lane(lane, "EQUIPMENT_FAULT")
    return True


# ---------------------------------------------------------------------------
# plan cascades
# ---------------------------------------------------------------------------
def retire_plan_assignments(plan):
    touched = set()
    for assignment in plan_assignments(plan["id"], ("SCHEDULED",)):
        cancel_assignment(assignment)
        touched.add(assignment["officer_id"])
    for assignment in plan_assignments(plan["id"], ("CHECKED_IN", "REASSIGN_PENDING")):
        release_assignment(assignment)
        touched.add(assignment["officer_id"])
    for officer_id in touched:
        settle_officer(officer_id, retire=True)


def supersede_other_plans(plan):
    for other in store.rows("staffing_plans"):
        if other["id"] == plan["id"]:
            continue
        if other["checkpoint_id"] != plan["checkpoint_id"]:
            continue
        if other["operational_date"] != plan["operational_date"]:
            continue
        if other["state"] not in ("APPROVED", "ACTIVATED"):
            continue
        other["state"] = "SUPERSEDED"
        other["superseded_by_staffing_plan_id"] = plan["id"]
        store.touch(other)
        retire_plan_assignments(other)


# ---------------------------------------------------------------------------
# wait-time escalation cascade
# ---------------------------------------------------------------------------
def breach_counter_field(lane_type):
    if lane_type == "EXPEDITED":
        return "consecutive_breach_count_expedited"
    return "consecutive_breach_count_standard"


def open_wait_ticket(checkpoint, lane_type, states=("RAISED", "ACKNOWLEDGED")):
    for ticket in store.rows("escalation_tickets"):
        if (
            ticket["checkpoint_id"] == checkpoint["id"]
            and ticket["trigger_reason"] == "WAIT_THRESHOLD_BREACH"
            and ticket["lane_type_scope"] == lane_type
            and ticket["state"] in states
        ):
            return ticket
    return None


def handle_observation(checkpoint, lane_type, snapshot, breached):
    field = breach_counter_field(lane_type)
    if breached:
        checkpoint[field] = checkpoint[field] + 1
        if checkpoint[field] == consts.ESCALATION_BREACH_COUNT_REQUIRED:
            if open_wait_ticket(checkpoint, lane_type) is None:
                create_ticket(checkpoint, "WAIT_THRESHOLD_BREACH", lane_type, snapshot)
    else:
        checkpoint[field] = 0
        ticket = open_wait_ticket(checkpoint, lane_type, ("RAISED",))
        if ticket is not None:
            ticket["state"] = "EXPIRED"
            ticket["resolved_at_utc"] = store.now()
            store.touch(ticket)
